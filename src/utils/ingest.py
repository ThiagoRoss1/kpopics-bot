import uuid

from utils.database_operations import (
    get_idol_ids_by_keys,
    insert_photo,
    set_photo_ready,
    link_photo_idols,
    delete_photo,
)
from utils.storage import upload_bytes, delete_object

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def ingest_photo(image_bytes, ext, idol_keys, source,
                 source_url=None, date=None, urgent=None,
                 copies=0, combo=None, album_id=None):
    # Shared ingestion path for both the API endpoints and the scraper.
    # Idol identification comes from source metadata (no face recognition): if no known
    # idol matches, the photo is auto-rejected and nothing is inserted or uploaded.
    id_map = get_idol_ids_by_keys(idol_keys)
    if not id_map:
        print(f"Ingest rejected: no known idols in {idol_keys}.")
        return None

    # Order matters for atomicity: row first (as 'uploading'), then upload, then finalize.
    photo_id = insert_photo(
        source=source, source_url=source_url, date=date,
        urgent=urgent, copies=copies, combo=combo, album_id=album_id,
    )
    if photo_id is None:
        return None

    r2_key = f"analysis/{uuid.uuid4().hex}.{ext}"

    if not upload_bytes(r2_key, image_bytes, CONTENT_TYPES.get(ext)):
        delete_photo(photo_id)  # clean up the orphaned row
        return None

    if not set_photo_ready(photo_id, r2_key):
        delete_object(r2_key)
        delete_photo(photo_id)
        return None

    link_photo_idols(photo_id, list(id_map.values()))
    print(f"Ingested photo {photo_id} ({r2_key}) idols={list(id_map.keys())}.")
    return photo_id
