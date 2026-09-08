import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import Explanation, Project, ProjectFile
from routers.upload import STORAGE_ROOT
from services.ai_client import explain_code

router = APIRouter()


class ExplainRequest(BaseModel):
    project_id: str
    file_path: Optional[str] = None
    level: Literal["beginner", "developer", "technical"] = "developer"


def _guard_project_ready(project: Project):
    if project.status == "processing":
        return JSONResponse(
            status_code=202,
            content={"detail": "Project is still being parsed."},
        )
    if project.status == "failed":
        raise HTTPException(400, "Project parsing failed; please re-upload.")
    return None


def _resolve_project_file(project_id: str, file_path: str) -> str:
    normalized_path = file_path.replace("\\", "/").strip("/")
    project_root = os.path.realpath(os.path.join(STORAGE_ROOT, project_id))
    full_path = os.path.realpath(os.path.join(project_root, normalized_path))
    if os.path.commonpath([project_root, full_path]) != project_root:
        raise HTTPException(400, "Invalid file_path.")
    if not os.path.isfile(full_path):
        raise HTTPException(404, "File not found in project.")
    return full_path


def _explain_one(project_id: str, file_path: str, level: str, db: Session) -> dict:
    normalized_path = file_path.replace("\\", "/").strip("/")
    cached = (
        db.query(Explanation)
        .filter(
            Explanation.project_id == project_id,
            Explanation.file_path == normalized_path,
            Explanation.level == level,
        )
        .first()
    )
    if cached:
        return {
            "file_path": cached.file_path,
            "level": cached.level,
            "explanation": cached.content,
            "cached": True,
        }

    full_path = _resolve_project_file(project_id, normalized_path)
    with open(full_path, "r", encoding="utf-8", errors="ignore") as source_file:
        code = source_file.read()

    explanation_text = explain_code(code, level, file_path=normalized_path)
    db.add(
        Explanation(
            project_id=project_id,
            file_path=normalized_path,
            level=level,
            content=explanation_text,
        )
    )
    db.commit()
    log_action(
    db=db,
    action="EXPLAIN_CODE",
    project_id=project_id,
    details={
        "file_path": normalized_path,
        "level": level,
    },
)

    return {
        "file_path": normalized_path,
        "level": level,
        "explanation": explanation_text,
        "cached": False,
    }


@router.post("")
def explain(req: ExplainRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == req.project_id).first()
    if not project:
        raise HTTPException(404, "Project not found.")

    guard_response = _guard_project_ready(project)
    if guard_response:
        return guard_response

    if req.file_path is not None:
        if not req.file_path.strip():
            raise HTTPException(400, "file_path must not be empty when provided.")
        result = _explain_one(req.project_id, req.file_path, req.level, db)
        return {"project_id": req.project_id, **result}

    project_files = (
        db.query(ProjectFile)
        .filter(ProjectFile.project_id == req.project_id)
        .order_by(ProjectFile.path.asc())
        .all()
    )
    if not project_files:
        raise HTTPException(404, "No parsed files found for this project.")

    explanations = [
        _explain_one(req.project_id, project_file.path, req.level, db)
        for project_file in project_files
    ]

    return {
        "project_id": req.project_id,
        "level": req.level,
        "cached": all(item["cached"] for item in explanations),
        "explanations": explanations,
    }
