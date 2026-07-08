from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.security import require_token
from utils.database_operations import (
    get_all_idols, get_all_groups, idol_exists, create_idol, set_idol_kpopping,
    get_idols_for_discovery,
)
from scrapers.kpopping import resolve_idol_id

router = APIRouter(prefix="/idols", tags=["idols"])

class IdolIn(BaseModel):
    key: str
    idol_names: list[str]
    name_tags: str | None = None
    group_key: str
    group_names: list[str] | None = None   # only used when the group is new
    group_tags: str | None = None          # only used when the group is new
    kpopping_url: str | None = None        # idol profile URL; UUID is resolved for auto-scraping


@router.get("", dependencies=[Depends(require_token)])
def list_idols():
    # Feeds both the manual-ingest idol picker and the register-idol form's group dropdown.
    return {"idols": get_all_idols(), "groups": get_all_groups()}


@router.get("/discovery", dependencies=[Depends(require_token)])
def list_discovery_idols():
    # The local ingestion script's only way to learn which idols to poll (the DB lives on Railway).
    # Returns [{key, kpopping_id}, ...] — unlike GET /idols, this exposes the Kpopping UUID.
    return {"idols": get_idols_for_discovery()}


@router.post("", dependencies=[Depends(require_token)])
def register_idol(payload: IdolIn):
    key = payload.key.strip().lower()
    group_key = (payload.group_key or "").strip().lower()
    names = [name.strip() for name in payload.idol_names if name.strip()]

    if not key:
        raise HTTPException(status_code=400, detail="Idol key is required.")
    if not names:
        raise HTTPException(status_code=400, detail="At least one idol name is required.")
    if not group_key:
        raise HTTPException(status_code=400, detail="Group key is required.")
    if idol_exists(key):
        raise HTTPException(status_code=409, detail=f"Idol '{key}' already exists.")

    new_id = create_idol(
        key=key,
        idol_names=names,
        name_tags=payload.name_tags,
        group_key=group_key,
        group_names=payload.group_names,
        group_tags=payload.group_tags,
    )
    if new_id is None:
        raise HTTPException(status_code=500, detail="Could not create idol.")

    # Optional: link the idol to Kpopping for auto-scraping. Resolution failure doesn't fail the
    # registration — the idol is created either way; it just won't be polled until a URL resolves.
    kpopping_id = None
    kpopping_url = (payload.kpopping_url or "").strip()
    if kpopping_url:
        kpopping_id = resolve_idol_id(kpopping_url)
        set_idol_kpopping(key, kpopping_url, kpopping_id)

    return {"id": new_id, "key": key, "status": "created", "kpopping_linked": kpopping_id is not None}
