import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Membership, User, Workspace
from app.services.auth import decode_token


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = _bearer(authorization)
    try:
        payload = decode_token(token)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e
    try:
        uid = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token sub") from e
    user = db.scalar(select(User).where(User.id == uid))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


def current_workspace(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Workspace:
    """Resolve caller's default workspace.

    SCALE: today picks the first membership; later this comes from a
    workspace claim in the JWT, or an explicit X-Workspace-Id header
    validated against memberships.
    """
    m = db.scalar(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.id).limit(1)
    )
    if m is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no workspace for user")
    ws = db.get(Workspace, m.workspace_id)
    if ws is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace missing")
    return ws
