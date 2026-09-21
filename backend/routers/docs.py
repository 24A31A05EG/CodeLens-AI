import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import ProjectFile, GeneratedArtifact, User
from services.access import get_current_user, get_owned_project
from routers.upload import STORAGE_ROOT
from services.ai_client import generate_readme, generate_api_docs
from services.analysis.docgen import generate_api_docs as analysis_api_docs
from services.analysis.docgen import generate_readme as analysis_readme
from services.analysis.store import ensure_analysis, is_stale
from services.audit import log_action

router = APIRouter()


class DocsRequest(BaseModel):
    project_id: str
    # Literal replaces the manual if/else kind check that was in the route body.
    kind: Literal["readme", "api_docs"] = "readme"
    # Set to True to bypass the cache and force the AI to regenerate.
    force_regenerate: bool = False


@router.post("")
def generate_docs(
    req: DocsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(req.project_id, db, current_user)

    # ── Status guard ─────────────────────────────────────────────────────────
    if project.status == "processing":
        return JSONResponse(
            status_code=202,
            content={"detail": "Project is still being parsed."},
        )
    if project.status == "failed":
        raise HTTPException(400, "Project parsing failed; please re-upload.")

    analysis = ensure_analysis(db, project, os.path.join(STORAGE_ROOT, project.id))

    # ── Cache check ───────────────────────────────────────────────────────────
    cached = (
        db.query(GeneratedArtifact)
        .filter(
            GeneratedArtifact.project_id == req.project_id,
            GeneratedArtifact.kind == req.kind,
        )
        .order_by(GeneratedArtifact.created_at.desc())
        .first()
    )
    if cached is not None and not req.force_regenerate and not is_stale(cached.created_at, analysis):
        return {"kind": cached.kind, "content": cached.content, "cached": True}

    # ── Generate ──────────────────────────────────────────────────────────────
    if analysis:
        content = analysis_readme(analysis) if req.kind == "readme" else analysis_api_docs(analysis)
    else:  # legacy fallback when no analysis can be built
        files = db.query(ProjectFile).filter(ProjectFile.project_id == req.project_id).all()
        summary = {
            "name": project.name,
            "files": [{"path": f.path, "language": f.language, "symbols": f.symbols} for f in files],
        }
        content = generate_readme(summary) if req.kind == "readme" else generate_api_docs(summary)

    if cached is not None:
        cached.content = content
        cached.created_at = datetime.utcnow()
    else:
        db.add(GeneratedArtifact(project_id=req.project_id, kind=req.kind, content=content))
    db.commit()
    log_action(
        db=db,
        action="GENERATE_DOCUMENTATION",
        project_id=req.project_id,
        details={"kind": req.kind},
    )

    return {"kind": req.kind, "content": content, "cached": False}
