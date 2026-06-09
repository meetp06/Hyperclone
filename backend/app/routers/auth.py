from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.schemas.auth import DevLoginRequest, TokenResponse
from app.services.auth import encode_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-login", response_model=TokenResponse)
def dev_login(req: DevLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Dev-only login: look up a seeded user by email and mint a JWT.

    SCALE: replace with real OAuth (Google/GitHub/email-link). Same
    `current_user` dep will work; only the token issuance changes.
    """
    email = req.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found — run seed.py")
    return TokenResponse(access_token=encode_token(user.id))
