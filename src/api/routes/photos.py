import requests
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
from api.security import require_token
from utils.ingest import ingest_photo
from utils.database_operations import (
    get_pending_photos,
    get_photo,
    set_photo_approved,
    set_photo_rejected,
    set_photo_urgent,
    create_combo,
    clear_combo,
    get_photos_pending_score,
    set_photo_score,
)
from utils.storage import copy_object, delete_object, get_object_bytes

router = APIRouter(prefix="/photos", tags=["photos"])

IMAGE_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}

class PhotoIn(BaseModel):
    image_url: str
    idols: list[str]
    source: str = "kpopping"
    source_url: str | None = None
    date: str | None = None       # ISO YYYY-MM-DD
    urgent: int | None = None
    copies: int = 0
    combo: str | None = None
    album_id: str | None = None

class UrgentIn(BaseModel):
    urgent: bool

class ComboIn(BaseModel):
    photo_ids: list[int]

class ScoreIn(BaseModel):
    ai_score: float
    ai_reasoning: str | None = None

def _download(url):
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    return response.content

def _ext_from_url(url, default="jpg"):
    tail = url.split("?")[0].rsplit(".", 1)
    if len(tail) == 2 and 1 <= len(tail[1]) <= 5 and tail[1].isalnum():
        return tail[1].lower()
    
    return default


@router.post("", dependencies=[Depends(require_token)])
def create_photo(payload: PhotoIn):
    try:
        image_bytes = _download(payload.image_url)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not download image: {e}")

    photo_id = ingest_photo(
        image_bytes=image_bytes,
        ext=_ext_from_url(payload.image_url),
        idol_keys=[key.lower() for key in payload.idols],
        source=payload.source,
        source_url=payload.source_url or payload.image_url,
        date=payload.date,
        urgent=payload.urgent,
        copies=payload.copies,
        combo=payload.combo,
        album_id=payload.album_id,
    )
    if photo_id is None:
        raise HTTPException(status_code=422, detail="Rejected: no known idols matched.")

    return {"id": photo_id, "status": "pending"}


# Approval loop (webapp)

@router.get("/pending", dependencies=[Depends(require_token)])
def list_pending():
    # The approval queue the webapp renders.
    return {"photos": get_pending_photos()}

@router.get("/{photo_id}/image", dependencies=[Depends(require_token)])
def get_photo_image(photo_id: int):
    # Streams the raw bytes from R2 (private bucket) so the webapp can preview a pending photo.
    # The page fetches this with the Bearer token and shows it via a blob URL, so no token leaks
    # into an <img src>.
    photo = get_photo(photo_id)
    if not photo or not photo["r2_key"]:
        raise HTTPException(status_code=404, detail="Photo or image not found.")

    data = get_object_bytes(photo["r2_key"])
    if data is None:
        raise HTTPException(status_code=502, detail="Could not read image from storage.")

    ext = photo["r2_key"].rsplit(".", 1)[-1].lower()
    return Response(content=data, media_type=IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream"))

@router.patch("/{photo_id}/approve", dependencies=[Depends(require_token)])
def approve_photo(photo_id: int):
    # Promote analysis -> approved: copy the object, repoint the row, then drop the old copy.
    photo = get_photo(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found.")
    if photo["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Photo is not pending (status={photo['status']}).")

    src_key = photo["r2_key"]
    if not src_key:
        raise HTTPException(status_code=409, detail="Photo has no image to approve.")

    dst_key = "approved/" + src_key.split("/", 1)[-1]

    if not copy_object(src_key, dst_key):
        raise HTTPException(status_code=502, detail="Could not promote image in storage.")

    if not set_photo_approved(photo_id, dst_key):
        delete_object(dst_key)  # roll back the copy so storage matches the DB
        raise HTTPException(status_code=500, detail="Could not update photo record.")

    delete_object(src_key)  # orphan-safe: the DB already points at dst_key
    return {"id": photo_id, "status": "approved"}

@router.patch("/{photo_id}/reject", dependencies=[Depends(require_token)])
def reject_photo(photo_id: int):
    # Reject: delete the bytes immediately, keep the row as 'rejected' for dedup.
    photo = get_photo(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found.")
    if photo["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Photo is not pending (status={photo['status']}).")

    if photo["r2_key"]:
        delete_object(photo["r2_key"])

    set_photo_rejected(photo_id)
    return {"id": photo_id, "status": "rejected"}


# Approval metadata (webapp): urgent + auto-combo

@router.patch("/{photo_id}/urgent", dependencies=[Depends(require_token)])
def set_urgent(photo_id: int, payload: UrgentIn):
    photo = get_photo(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found.")
    if photo["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Photo is not pending (status={photo['status']}).")

    set_photo_urgent(photo_id, payload.urgent)
    return {"id": photo_id, "urgent": bool(payload.urgent)}

@router.post("/combo", dependencies=[Depends(require_token)])
def make_combo(payload: ComboIn):
    result = create_combo(payload.photo_ids)
    if result is None:
        raise HTTPException(status_code=400, detail="Pick 2-4 pending photos of the same idol to make a combo.")

    return result

@router.delete("/combo/{combo}", dependencies=[Depends(require_token)])
def remove_combo(combo: str):
    clear_combo(combo)
    return {"combo": combo, "status": "cleared"}


# AI aesthetic score (local worker)

@router.get("/pending-score", dependencies=[Depends(require_token)])
def list_pending_score():
    # The local AI worker's queue: pending photos without an aesthetic score yet.
    return {"photos": get_photos_pending_score()}

@router.patch("/{photo_id}/score", dependencies=[Depends(require_token)])
def score_photo(photo_id: int, payload: ScoreIn):
    # The worker posts back the computed aesthetic score (advisory; nothing auto-filters on it).
    if not set_photo_score(photo_id, payload.ai_score, payload.ai_reasoning):
        raise HTTPException(status_code=404, detail="Photo not found.")

    return {"id": photo_id, "ai_score": payload.ai_score}


@router.post("/manual", dependencies=[Depends(require_token)])
def create_photo_manual(
    idols: list[str] = Form(...),
    image_url: str | None = Form(None),
    file: UploadFile | None = File(None),
    date: str | None = Form(None),
    urgent: int | None = Form(None),
    copies: int = Form(0),
    combo: str | None = Form(None),
    album_id: str | None = Form(None),
):
    
    if file is not None:
        image_bytes = file.file.read()
        ext = _ext_from_url(file.filename or "", default="jpg")

    elif image_url:
        try:
            image_bytes = _download(image_url)

        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not download image: {e}")
        ext = _ext_from_url(image_url)
        
    else:
        raise HTTPException(status_code=400, detail="Provide either a file or image_url.")

    photo_id = ingest_photo(
        image_bytes=image_bytes,
        ext=ext,
        idol_keys=[key.lower() for key in idols],
        source="twitter-manual",
        source_url=image_url,
        date=date,
        urgent=urgent,
        copies=copies,
        combo=combo,
        album_id=album_id,
    )
    if photo_id is None:
        raise HTTPException(status_code=422, detail="Rejected: no known idols matched.")

    return {"id": photo_id, "status": "pending"}
