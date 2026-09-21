from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import ProjectFile, GeneratedArtifact, User
from services.access import get_current_user, get_owned_project
import os

from routers.upload import STORAGE_ROOT
from services.ai_client import generate_mermaid_diagram
from services.analysis.docgen import diagram_payload
from services.analysis.store import ensure_analysis, is_stale
from services.audit import log_action

router = APIRouter()


class DiagramRequest(BaseModel):
    project_id: str
    # Set to True to bypass the cache and force a fresh diagram.
    force_regenerate: bool = False


@router.post("")
def generate_diagram(
    req: DiagramRequest,
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
            GeneratedArtifact.kind == "diagram",
        )
        .order_by(GeneratedArtifact.created_at.desc())
        .first()
    )
    cache_ok = cached is not None and not req.force_regenerate and not is_stale(cached.created_at, analysis)

    extra = {}
    if analysis:
        payload = diagram_payload(analysis)
        extra = {k: payload[k] for k in ("tree", "entry_points", "stats", "legend")}

    if cache_ok:
        return {"mermaid": cached.content, "cached": True, **extra}

    # ── Generate ──────────────────────────────────────────────────────────────
    if analysis:
        mermaid_code = payload["mermaid"]
    else:  # legacy fallback: import-string based diagram
        files = db.query(ProjectFile).filter(ProjectFile.project_id == req.project_id).all()
        mermaid_code = generate_mermaid_diagram({f.path: f.imports for f in files})

    if cached is not None:
        cached.content = mermaid_code
        cached.created_at = datetime.utcnow()
    else:
        db.add(GeneratedArtifact(project_id=req.project_id, kind="diagram", content=mermaid_code))
    db.commit()
    log_action(
        db=db,
        action="GENERATE_DIAGRAM",
        project_id=req.project_id,
        details={"type": "mermaid"},
    )

    return {"mermaid": mermaid_code, "cached": False, **extra}
