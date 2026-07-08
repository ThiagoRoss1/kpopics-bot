import os
from fastapi import Header, HTTPException
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")

# Single-user personal project: a fixed Bearer token from the environment, no login/session.
def require_token(authorization: str = Header(None)):
    if not API_TOKEN:
        raise HTTPException(status_code=500, detail="API_TOKEN not configured.")
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized.")
