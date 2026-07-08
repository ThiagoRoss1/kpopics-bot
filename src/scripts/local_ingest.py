import os
import sys
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load THIS script's own env before importing utils.storage (which reads R2_BUCKET_NAME at import
# time). load_dotenv doesn't override already-set vars, so these values win over any src/.env and
# prod R2 creds stay out of the API's local-dev env. local_ingest.env holds R2_* + API_BASE_URL +
# API_TOKEN and is gitignored.
BASE_DIR = Path(__file__).resolve().parent.parent          # src/
sys.path.insert(0, str(BASE_DIR))                          # runnable from anywhere, like migrate_json
load_dotenv(Path(__file__).resolve().parent / "local_ingest.env")

# Pure, DB-free parsing/fetch helpers reused from the server scraper (no DB_FILE needed) + the R2
# uploader. scrapers.kpopping's DB imports are now lazy, so importing it here triggers no DB.
from scrapers.kpopping import (
    fetch_album,
    parse_album,
    list_recent_album_urls,
    _download_image,
    _ext_from_url,
)
from utils.storage import upload_bytes

API_BASE_URL = (os.getenv("API_BASE_URL") or "").rstrip("/")
API_TOKEN = os.getenv("API_TOKEN")

# 5-line dup of ingest.CONTENT_TYPES (which lives in the DB-coupled ingest.py we deliberately avoid).
CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


# --- Railway API (metadata only; no bytes ever traverse Railway) ---

def _headers():
    return {"Authorization": f"Bearer {API_TOKEN}"}

def _discovery_ids():
    # The DB lives on Railway, so this endpoint is the only way to learn which idols to poll.
    try:
        response = requests.get(f"{API_BASE_URL}/idols/discovery", headers=_headers(), timeout=25)
        response.raise_for_status()
        return response.json().get("idols", [])

    except Exception as e:
        print(f"Error fetching discovery idols: {e}.")
        return []

def _already_exists(source_url):
    # Cheap pre-check so a duplicate is never re-downloaded/re-uploaded.
    try:
        response = requests.get(f"{API_BASE_URL}/photos/exists", params={"source_url": source_url},
                                headers=_headers(), timeout=25)
        response.raise_for_status()
        return bool(response.json().get("exists"))

    except Exception as e:
        print(f"Error checking exists for {source_url}: {e}.")
        return False   # on error, fall through and let /register re-dedup

def _register(payload):
    # Post metadata for a photo whose bytes are already in R2. Returns the JSON body (or None).
    try:
        response = requests.post(f"{API_BASE_URL}/photos/register", json=payload,
                                 headers=_headers(), timeout=25)
        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(f"Error registering {payload.get('r2_key')}: {e}.")
        return None


# --- Orchestrate (HTTP twin of scrape_album / scrape_idol / poll_all_idols) ---

def ingest_album(url, limit=None):
    # Download one album's full-res photos over the PC's bandwidth, upload straight to R2, then
    # POST metadata to Railway. Group-only / unknown-idol albums are rejected server-side by
    # /register (and locally here when there's no member tag at all).
    summary = {"album_id": None, "ingested": 0, "skipped": 0, "rejected_reason": None}

    html = fetch_album(url)
    if html is None:
        summary["rejected_reason"] = "fetch failed"
        return summary

    parsed = parse_album(html, url)
    if parsed is None:
        summary["rejected_reason"] = "parse failed"
        return summary

    summary["album_id"] = parsed["album_id"]

    if not parsed["idol_names"]:
        summary["rejected_reason"] = "group-only / no member tag"
        print(f"Rejected {url}: group-only album (no member tag).")
        return summary

    image_urls = parsed["image_urls"]
    if limit:
        image_urls = image_urls[:limit]

    for image_url in image_urls:
        if _already_exists(image_url):
            summary["skipped"] += 1
            continue

        try:
            image_bytes = _download_image(image_url)

        except Exception as e:
            print(f"Error downloading {image_url}: {e}.")
            summary["skipped"] += 1
            continue

        ext = _ext_from_url(image_url)
        r2_key = f"analysis/{uuid.uuid4().hex}.{ext}"

        if not upload_bytes(r2_key, image_bytes, CONTENT_TYPES.get(ext)):
            summary["skipped"] += 1
            continue

        result = _register({
            "r2_key": r2_key,
            "idols": parsed["idol_names"],
            "source": "kpopping",
            "source_url": image_url,
            "date": parsed["date"],
            "album_id": parsed["album_id"],
        })
        if result and result.get("id"):
            summary["ingested"] += 1
        else:
            # duplicate (server-side race), reject, or error: /register already deleted the orphan.
            summary["skipped"] += 1

    print(f"Ingested {summary['album_id']}: ingested={summary['ingested']} skipped={summary['skipped']}.")
    return summary

def ingest_idol(kpopping_id, limit_albums=5, limit_images=None):
    summary = {"kpopping_id": kpopping_id, "albums": 0, "ingested": 0, "skipped": 0}

    for album_url in list_recent_album_urls(kpopping_id, limit=limit_albums):
        result = ingest_album(album_url, limit=limit_images)
        summary["albums"] += 1
        summary["ingested"] += result.get("ingested", 0)
        summary["skipped"] += result.get("skipped", 0)

    print(f"Ingested idol {kpopping_id}: albums={summary['albums']} "
          f"ingested={summary['ingested']} skipped={summary['skipped']}.")
    return summary

def poll_all_idols(limit_albums=5, limit_images=None):
    # The full local poll: every idol Railway reports as discoverable (has a Kpopping UUID).
    total = {"idols": 0, "albums": 0, "ingested": 0, "skipped": 0}

    for idol in _discovery_ids():
        result = ingest_idol(idol["kpopping_id"], limit_albums=limit_albums, limit_images=limit_images)
        total["idols"] += 1
        total["albums"] += result["albums"]
        total["ingested"] += result["ingested"]
        total["skipped"] += result["skipped"]

    print(f"Poll complete: idols={total['idols']} albums={total['albums']} "
          f"ingested={total['ingested']} skipped={total['skipped']}.")
    return total


if __name__ == "__main__":
    if not API_BASE_URL or not API_TOKEN:
        sys.exit("Missing API_BASE_URL / API_TOKEN — populate src/scripts/local_ingest.env.")

    # CLI mirrors the server scraper:
    #   no args               -> poll every discoverable idol (5 albums each).
    #   `poll [albums] [imgs]` -> a capped poll, handy for a quick test (e.g. `poll 1 3`).
    #   `<album_url> [imgs]`   -> ingest a single album manually.
    args = sys.argv[1:]
    if not args:
        print(poll_all_idols())
    elif args[0] == "poll":
        albums = int(args[1]) if len(args) > 1 else 5
        images = int(args[2]) if len(args) > 2 else None
        print(poll_all_idols(limit_albums=albums, limit_images=images))
    else:
        limit = int(args[1]) if len(args) > 1 else None
        print(ingest_album(args[0], limit=limit))
