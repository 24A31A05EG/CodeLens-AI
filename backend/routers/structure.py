from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import Project, ProjectFile

router = APIRouter()


@router.get("/{project_id}/structure")
def get_structure(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found.")

    files = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()
    language_counts = Counter(f.language for f in files if f.language)

    return {
        "project_id": project_id,
        "status": project.status,
        "file_count": len(files),
        "languages": dict(language_counts),
        "files": [
            {"path": f.path, "language": f.language, "symbol_count": len(f.symbols or [])}
            for f in files
        ],
    }
