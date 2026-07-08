import os
import sys

import requests
from dotenv import load_dotenv

# Runs on the LOCAL PC, talking to the Railway API over HTTP. It pulls photos that
# still need an aesthetic score, scores them on the GPU, and posts the scores back. On-demand:
# run it whenever you want the queue scored — it does not need to stay running.
load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL").rstrip("/")
API_TOKEN = os.getenv("API_TOKEN")

def _headers():
    return {"Authorization": f"Bearer {API_TOKEN}"}

def fetch_pending():
    response = requests.get(f"{API_BASE_URL}/photos/pending-score", headers=_headers(), timeout=30)
    response.raise_for_status()
    return response.json().get("photos", [])

def fetch_image(photo_id):
    response = requests.get(f"{API_BASE_URL}/photos/{photo_id}/image", headers=_headers(), timeout=60)
    response.raise_for_status()
    return response.content

def post_score(photo_id, score, reasoning=None):
    response = requests.patch(
        f"{API_BASE_URL}/photos/{photo_id}/score", headers=_headers(),
        json={"ai_score": round(float(score), 2), "ai_reasoning": reasoning}, timeout=30)
    response.raise_for_status()
    return response.json()

def run(scorer):
    # Score every pending photo and post the result back. A per-photo failure is logged and skipped,
    # so one bad image never aborts the batch. `scorer` is anything with .score(image_bytes) -> float.
    pending = fetch_pending()
    print(f"{len(pending)} photo(s) to score.")

    scored = 0
    for photo in pending:
        photo_id = photo["id"]
        try:
            score = scorer.score(fetch_image(photo_id))
            post_score(photo_id, score)
            scored += 1
            print(f"  photo {photo_id}: {score:.2f}")

        except Exception as e:
            print(f"  photo {photo_id}: skipped ({e})")

    print(f"Done — scored {scored}/{len(pending)}.")
    return scored

def main():
    if not API_TOKEN:
        print("API_TOKEN not set (add it to worker/.env or the environment).")
        sys.exit(1)

    # Heavy import (torch + CLIP) only when actually running — keeps the orchestration importable
    # and testable without the ML stack installed.
    from aesthetic import AestheticScorer

    run(AestheticScorer())

if __name__ == "__main__":
    main()
