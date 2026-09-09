from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import Project, User
from services.user_service import get_or_create_default_user


USER_CONTEXT_HEADER = "X-CodeLens-User"


def get_current_user(
    user_context: Optional[str] = Header(default=None, alias=USER_CONTEXT_HEADER),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the current development user context.

    Existing clients without the header remain mapped to the local demo user.
    Supplying the header selects an existing user by username; it is an
    ownership context, not a replacement for production authentication.
    """
    if user_context is None:
        return get_or_create_default_user(db)

    username = user_context.strip()
    if not username:
        raise HTTPException(401, "Invalid user context.")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(401, "Unknown user context.")

    return user


def get_owned_project(
    project_id: str,
    db: Session,
    current_user: User,
) -> Project:
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.user_id == current_user.id,
        )
        .first()
    )

    if not project:
        raise HTTPException(404, "Project not found.")

    return project
