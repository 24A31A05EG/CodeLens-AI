from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import ProjectFile, GeneratedArtifact, User
from services.access import get_current_user, get_owned_project
from services.ai_client import generate_readme, generate_api_docs
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

    # ── Cache check ───────────────────────────────────────────────────────────
    if not req.force_regenerate:
        cached = (
            db.query(GeneratedArtifact)
            .filter(
                GeneratedArtifact.project_id == req.project_id,
                GeneratedArtifact.kind == req.kind,
            )
            .order_by(GeneratedArtifact.created_at.desc())
            .first()
        )
        if cached:
            return {"kind": cached.kind, "content": cached.content, "cached": True}

    # ── Generate ──────────────────────────────────────────────────────────────
    files = db.query(ProjectFile).filter(ProjectFile.project_id == req.project_id).all()
    summary = {
        "name": project.name,
        "files": [
            {"path": f.path, "language": f.language, "symbols": f.symbols}
            for f in files
        ],
    }

    content = generate_readme(summary) if req.kind == "readme" else generate_api_docs(summary)

    db.add(
        GeneratedArtifact(
            project_id=req.project_id, 
            kind=req.kind, 
            content=content,
        )
    )
    db.commit()
    log_action(
    db=db,
    action="GENERATE_DOCUMENTATION",
    project_id=req.project_id,
    details={
        "kind": req.kind,
    },
)

    return {"kind": req.kind, "content": content, "cached": False}
