from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import GeneratedArtifact, Explanation, Project, ProjectFile

router = APIRouter()


def _project_history_payload(project_id: str, db: Session) -> dict:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found.")

    explanations = (
        db.query(Explanation)
        .filter(Explanation.project_id == project_id)
        .order_by(Explanation.created_at.desc())
        .all()
    )
    artifacts = (
        db.query(GeneratedArtifact)
        .filter(GeneratedArtifact.project_id == project_id)
        .order_by(GeneratedArtifact.created_at.desc())
        .all()
    )
    files = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()

    return {
        "project": {
            "project_id": project.id,
            "name": project.name,
            "source": project.source,
            "source_ref": project.source_ref,
            "status": project.status,
            "created_at": project.created_at,
            "file_count": len(files),
        },
        "explanations": [
            {
                "file_path": explanation.file_path,
                "level": explanation.level,
                "created_at": explanation.created_at,
            }
            for explanation in explanations
        ],
        "artifacts": [
            {"kind": artifact.kind, "created_at": artifact.created_at}
            for artifact in artifacts
        ],
    }


@router.get("/history")
def list_history(
    project_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if project_id:
        return _project_history_payload(project_id, db)

    projects = db.query(Project).order_by(Project.created_at.desc()).limit(50).all()
    items = []
    for project in projects:
        file_count = db.query(ProjectFile).filter(ProjectFile.project_id == project.id).count()
        explanation_count = db.query(Explanation).filter(Explanation.project_id == project.id).count()
        artifact_count = db.query(GeneratedArtifact).filter(GeneratedArtifact.project_id == project.id).count()
        items.append(
            {
                "project_id": project.id,
                "name": project.name,
                "source": project.source,
                "source_ref": project.source_ref,
                "status": project.status,
                "created_at": project.created_at,
                "file_count": file_count,
                "explanation_count": explanation_count,
                "artifact_count": artifact_count,
            }
        )

    return {"projects": items}


@router.get("/history/{project_id}")
@router.get("/projects/{project_id}/history", include_in_schema=False)
def get_project_history(project_id: str, db: Session = Depends(get_db)):
    return _project_history_payload(project_id, db)
