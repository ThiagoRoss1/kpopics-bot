import re
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

from utils.database_operations import (
    get_idol_keys_by_names,
    photo_exists_by_source_url,
    get_idols_for_discovery,
)
from utils.ingest import ingest_photo

# Kpopping serves 403 to the default library user-agent but 200 to a normal browser one.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Per-idol discovery: the idol's kpics feed is a JSON API filtered by their Kpopping
# UUID; album pages themselves live at ALBUM_BASE + slug.
API_KPICS = "https://kpopping.com/api/kpics"
ALBUM_BASE = "https://kpopping.com/kpics/"

# --- Fetch ---

def fetch_album(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=25)
        if response.status_code != 200:
            print(f"Error fetching {url}: HTTP {response.status_code}.")
            return None

        return response.text

    except Exception as e:
        print(f"Error fetching {url}: {e}.")
        return None

def _download_image(url):
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()

    return response.content

# --- Parse ---

def _album_id_from_url(url):
    # The URL slug is the natural album id (there is no numeric id on the page).
    return urlparse(url).path.rstrip("/").split("/")[-1].lower()

def _ext_from_url(url, default="jpg"):
    tail = url.split("?")[0].rsplit(".", 1)
    if len(tail) == 2 and 1 <= len(tail[1]) <= 5 and tail[1].isalnum():
        return tail[1].lower()

    return default

def _extract_idol_names(soup):
    # Member albums carry <a href="/profiles/idol/...">Name•group</a>; the Kpopping slug is not
    # our key, so we take the display name (before the • bullet) and resolve it against idol_names.
    # A group-only album has no idol link, so this returns [] and the album is later rejected.
    names = []
    for anchor in soup.find_all("a", href=True):
        if "/profiles/idol/" in anchor["href"]:
            name = anchor.get_text(strip=True).split("•")[0].strip()
            if name and name not in names:
                names.append(name)
                
    return names

def _event_date_from_title(title):
    # Kpopping event/fansite album titles start with the real event date as YYMMDD
    # (e.g. "250930 - aespa KARINA ..." -> 2025-09-30). The JSON-LD datePublished is only the
    # re-upload timestamp, so it is ignored. No YYMMDD prefix (e.g. comeback concept sets) -> None.
    if not title:
        return None

    match = re.match(r"\s*(\d{2})(\d{2})(\d{2})(?:\D|$)", title)
    if not match:
        return None

    yy, mm, dd = match.groups()
    if not ("01" <= mm <= "12" and "01" <= dd <= "31"):
        return None

    return f"20{yy}-{mm}-{dd}"

def _is_album_photo(src):
    # A full-res album photo: a legacy "-documents-" original, or a newer cdn.kpopping.com / *.r2.dev
    # "/kpics/YYYY/MM/..." file. Icons/logos/avatars (not under /kpics/, no -documents-) are excluded.
    parsed = urlparse(src)
    host, path = parsed.netloc, parsed.path
    if "legacy.kpopping.com" in host and "-documents-" in path:
        return True
    if ("kpopping.com" in host or host.endswith(".r2.dev")) and "/kpics/" in path:
        return True

    return False

def _extract_image_urls(soup):
    # This album's photos. An <img> src may be wrapped by an image optimizer (/_next/image or
    # /api/kpics-image) carrying the real file in a `url=` param — decode it. Keep legacy
    # "-documents-" originals and newer cdn.kpopping.com / r2.dev "/kpics/..." files. Skip the
    # "More photos of <idol>" related strip (its thumbnails are wrapped in an <a> that links to a
    # different /kpics/ album; this album's own gallery uses <button>, not links). Dedup by file
    # path, since the same photo can appear on two hosts (e.g. the cover on r2.dev + gallery on cdn).
    originals = []
    seen_paths = set()
    for img in soup.find_all("img"):
        if img.find_parent("a", href=re.compile(r"/kpics/")):
            continue

        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue

        query = urlparse(src).query
        if query:
            wrapped = parse_qs(query).get("url", [None])[0]
            if wrapped:
                src = unquote(wrapped)

        if _is_album_photo(src):
            path = urlparse(src).path
            if path not in seen_paths:
                seen_paths.add(path)
                originals.append(src)

    return originals

def parse_album(html, url):
    try:
        soup = BeautifulSoup(html, "lxml")
        heading = soup.find("h1")
        title = heading.get_text(strip=True) if heading else None

        return {
            "title": title,
            "idol_names": _extract_idol_names(soup),
            "date": _event_date_from_title(title),
            "album_id": _album_id_from_url(url),
            "image_urls": _extract_image_urls(soup),
        }

    except Exception as e:
        print(f"Error parsing album {url}: {e}.")
        return None


# --- Orchestrate ---

def scrape_album(url, limit=None):
    # Ingest full-res photos of one Kpopping album into the pipeline (status='pending'), tagged
    # with the album's known member(s). Group-only or unknown-idol albums are rejected.
    # `limit` caps how many images are ingested (handy for a quick test); None = the whole album.
    summary = {"album_id": _album_id_from_url(url), "ingested": 0, "skipped": 0, "rejected_reason": None}

    html = fetch_album(url)
    if html is None:
        summary["rejected_reason"] = "fetch failed"
        return summary

    parsed = parse_album(html, url)
    if parsed is None:
        summary["rejected_reason"] = "parse failed"
        return summary

    if not parsed["idol_names"]:
        summary["rejected_reason"] = "group-only / no member tag"
        print(f"Rejected {url}: group-only album (no member tag).")
        return summary

    idol_keys = get_idol_keys_by_names(parsed["idol_names"])
    if not idol_keys:
        summary["rejected_reason"] = "no known idol"
        print(f"Rejected {url}: names {parsed['idol_names']} match no known idol.")
        return summary

    image_urls = parsed["image_urls"]
    if limit:
        image_urls = image_urls[:limit]

    for image_url in image_urls:
        if photo_exists_by_source_url(image_url):
            summary["skipped"] += 1
            continue

        try:
            image_bytes = _download_image(image_url)

        except Exception as e:
            print(f"Error downloading {image_url}: {e}.")
            summary["skipped"] += 1
            continue

        photo_id = ingest_photo(
            image_bytes=image_bytes,
            ext=_ext_from_url(image_url),
            idol_keys=idol_keys,
            source="kpopping",
            source_url=image_url,
            date=parsed["date"],
            album_id=parsed["album_id"],
        )
        if photo_id is None:
            summary["skipped"] += 1
        else:
            summary["ingested"] += 1

    print(f"Scraped {summary['album_id']}: ingested={summary['ingested']} skipped={summary['skipped']}.")
    return summary


# Per-idol discovery

def resolve_idol_id(profile_url):
    # Pull an idol's Kpopping UUID out of their profile page's "Photos" link
    # (/kpics?idol=<uuid>&idolName=...). Returns the UUID string, or None if not found.
    html = fetch_album(profile_url)
    if html is None:
        return None

    try:
        soup = BeautifulSoup(html, "lxml")
        for anchor in soup.find_all("a", href=True):
            idol = parse_qs(urlparse(anchor["href"]).query).get("idol", [None])[0]
            if idol and re.fullmatch(r"[0-9a-fA-F-]{36}", idol):
                return idol

        print(f"No Kpopping idol id found on {profile_url}.")
        return None

    except Exception as e:
        print(f"Error resolving idol id from {profile_url}: {e}.")
        return None

def list_recent_album_urls(kpopping_id, limit=5):
    # Query the idol's kpics feed (JSON, newest first) and return the album page URLs of their most
    # recent posts, capped at `limit`. The correct filter param is `idolId` (not `idol`).
    try:
        response = requests.get(API_KPICS, params={"idolId": kpopping_id}, headers=HEADERS, timeout=25)
        response.raise_for_status()

        urls = []
        for item in response.json().get("kpics", []):
            slug = item.get("slug")
            if slug:
                urls.append(ALBUM_BASE + slug)
            if limit and len(urls) >= limit:
                break

        return urls

    except Exception as e:
        print(f"Error listing albums for idol {kpopping_id}: {e}.")
        return []

def scrape_idol(kpopping_id, limit_albums=5, limit_images=None):
    # Discover an idol's most recent albums and scrape each into the pipeline. Dedup
    # (photo_exists_by_source_url, inside scrape_album) makes re-polling cheap and repeat-free.
    summary = {"kpopping_id": kpopping_id, "albums": 0, "ingested": 0, "skipped": 0}

    for album_url in list_recent_album_urls(kpopping_id, limit=limit_albums):
        result = scrape_album(album_url, limit=limit_images)
        summary["albums"] += 1
        summary["ingested"] += result.get("ingested", 0)
        summary["skipped"] += result.get("skipped", 0)

    print(f"Scraped idol {kpopping_id}: albums={summary['albums']} "
          f"ingested={summary['ingested']} skipped={summary['skipped']}.")
    return summary

def poll_all_idols(limit_albums=5, limit_images=None):
    # The scheduled job: scrape the recent albums of every idol that has a Kpopping id registered.
    total = {"idols": 0, "albums": 0, "ingested": 0, "skipped": 0}

    for idol in get_idols_for_discovery():
        result = scrape_idol(idol["kpopping_id"], limit_albums=limit_albums, limit_images=limit_images)
        total["idols"] += 1
        total["albums"] += result["albums"]
        total["ingested"] += result["ingested"]
        total["skipped"] += result["skipped"]

    print(f"Poll complete: idols={total['idols']} albums={total['albums']} "
          f"ingested={total['ingested']} skipped={total['skipped']}.")
    return total

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    # Default (no args): the automatic per-idol poll — same behavior as the scheduled job.
    # Optional manual one-off: pass a single <album_url> [image_limit] to scrape just that album.
    if len(sys.argv) >= 2:
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(scrape_album(sys.argv[1], limit=limit))
    else:
        print(poll_all_idols())
