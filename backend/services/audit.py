from typing import Optional

from sqlalchemy.orm import Session

from models.db_models import AuditLog


def log_action(
    db: Session,
    action: str,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    details: Optional[dict] = None,
):
    audit_log = AuditLog(
        user_id=user_id,
        project_id=project_id,
        action=action,
        details=details,
    )

    db.add(audit_log)
    db.commit()

    return audit_log
