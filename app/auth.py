from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey


def get_current_key(
    authorization: str = Header(...),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Resolve the Bearer virtual key in the Authorization header to an ApiKey row.

    Real provider keys never leave this service: callers only ever see a
    virtual key (e.g. "sk-relay-...") that we map to a real provider key
    server-side. Revoking access is just flipping is_active to False.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    virtual_key = authorization.removeprefix("Bearer ").strip()
    key = db.query(ApiKey).filter(ApiKey.virtual_key == virtual_key).first()

    if key is None or not key.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    return key
