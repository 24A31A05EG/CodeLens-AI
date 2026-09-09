from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import AuditLog, Project, User
from services.access import get_current_user, get_owned_project


router = APIRouter()


@router.get("/audit-logs")
def get_audit_logs(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if project_id:
        get_owned_project(project_id, db, current_user)

    query = (
        db.query(AuditLog)
        .outerjoin(Project, AuditLog.project_id == Project.id)
        .filter(
            (AuditLog.user_id == current_user.id)
            | (Project.user_id == current_user.id)
        )
    )

    if project_id:
        query = query.filter(
            AuditLog.project_id == project_id
        )

    logs = (
        query
        .order_by(AuditLog.created_at.desc())
        .limit(100)
        .all()
    )

    return {
        "logs": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "project_id": log.project_id,
                "action": log.action,
                "details": log.details,
                "created_at": log.created_at,
            }
            for log in logs
        ]
    }
