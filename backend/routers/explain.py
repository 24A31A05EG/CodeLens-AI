import os
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import Explanation, Project, ProjectFile, User
from routers.upload import STORAGE_ROOT
from services.access import get_current_user, get_owned_project
from services.ai_client import explain_code, explain_file
from services.analysis.redact import redact_secrets
from services.analysis.store import ensure_analysis, is_stale
from services.audit import log_action


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
        raise HTTPException(
            400,
            "Project parsing failed; please re-upload.",
        )

    return None


def _resolve_project_file(project_id: str, file_path: str) -> str:
    normalized_path = file_path.replace("\\", "/").strip("/")

    project_root = os.path.realpath(
        os.path.join(STORAGE_ROOT, project_id)
    )

    full_path = os.path.realpath(
        os.path.join(project_root, normalized_path)
    )

    if os.path.commonpath(
        [project_root, full_path]
    ) != project_root:
        raise HTTPException(
            400,
            "Invalid file_path.",
        )

    if not os.path.isfile(full_path):
        raise HTTPException(
            404,
            "File not found in project.",
        )

    return full_path


def _explain_one(
    project: Project,
    file_path: str,
    level: str,
    db: Session,
    analysis: Optional[dict] = None,
) -> dict:
    project_id = project.id
    normalized_path = file_path.replace("\\", "/").strip("/")

    # Path safety first (400 traversal / 404 missing), before any cache lookup.
    full_path = _resolve_project_file(project_id, normalized_path)

    # Only files that were ingested for THIS project may be explained. This keeps
    # files that are deliberately skipped (.env, keys, lockfiles ...) unreadable
    # through this endpoint even though they exist on disk.
    known = (
        db.query(ProjectFile)
        .filter(ProjectFile.project_id == project_id, ProjectFile.path == normalized_path)
        .first()
        is not None
    )
    if not known:
        raise HTTPException(404, "File not found in project.")

    cached = (
        db.query(Explanation)
        .filter(
            Explanation.project_id == project_id,
            Explanation.file_path == normalized_path,
            Explanation.level == level,
        )
        .first()
    )
    fresh_cache = cached is not None and not is_stale(cached.created_at, analysis)

    result = None
    if analysis and normalized_path in analysis["files"]:
        result = explain_file(analysis, normalized_path, level)

    if fresh_cache:
        explanation_text = cached.content
        cache_hit = True
    else:
        if result is not None:
            explanation_text = result["text"]
        else:  # no analysis available: legacy single-file template
            with open(full_path, "r", encoding="utf-8", errors="ignore") as source_file:
                code = redact_secrets(source_file.read())
            explanation_text = explain_code(code, level, file_path=normalized_path)
        if cached is not None:  # stale: refresh in place
            cached.content = explanation_text
            cached.created_at = datetime.utcnow()
        else:
            db.add(
                Explanation(
                    project_id=project_id,
                    file_path=normalized_path,
                    level=level,
                    content=explanation_text,
                )
            )
        db.commit()
        cache_hit = False

    log_action(
        db=db,
        action="EXPLAIN_CODE",
        project_id=project_id,
        details={"file_path": normalized_path, "level": level, "cached": cache_hit},
    )

    payload = {
        "file_path": normalized_path,
        "level": level,
        "explanation": explanation_text,
        "cached": cache_hit,
        "source": result["source"] if result else "legacy-template",
    }
    if result is not None:
        payload["analysis"] = result["relations"]
    return payload


def _repo_path(project_id: str) -> str:
    return os.path.join(STORAGE_ROOT, project_id)


@router.post("")
def explain(
    req: ExplainRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(req.project_id, db, current_user)

    guard_response = _guard_project_ready(project)

    if guard_response:
        return guard_response

    if req.file_path is not None:

        if not req.file_path.strip():
            raise HTTPException(
                400,
                "file_path must not be empty when provided.",
            )

        analysis = ensure_analysis(db, project, _repo_path(project.id))
        result = _explain_one(
            project,
            req.file_path,
            req.level,
            db,
            analysis,
        )

        return {
            "project_id": req.project_id,
            **result,
        }

    project_files = (
        db.query(ProjectFile)
        .filter(
            ProjectFile.project_id == req.project_id
        )
        .order_by(ProjectFile.path.asc())
        .all()
    )

    if not project_files:
        raise HTTPException(
            404,
            "No parsed files found for this project.",
        )

    analysis = ensure_analysis(db, project, _repo_path(project.id))
    explanations = [
        _explain_one(
            project,
            project_file.path,
            req.level,
            db,
            analysis,
        )
        for project_file in project_files
    ]

    return {
        "project_id": req.project_id,
        "level": req.level,
        "cached": all(
            item["cached"]
            for item in explanations
        ),
        "explanations": explanations,
    }