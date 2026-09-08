from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import Project, ProjectFile, GeneratedArtifact
from services.ai_client import generate_mermaid_diagram

router = APIRouter()


class DiagramRequest(BaseModel):
    project_id: str
    # Set to True to bypass the cache and force a fresh diagram.
    force_regenerate: bool = False


@router.post("")
def generate_diagram(req: DiagramRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == req.project_id).first()
    if not project:
        raise HTTPException(404, "Project not found.")

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
                GeneratedArtifact.kind == "diagram",
            )
            .order_by(GeneratedArtifact.created_at.desc())
            .first()
        )
        if cached:
            return {"mermaid": cached.content, "cached": True}

    # ── Generate ──────────────────────────────────────────────────────────────
    files = db.query(ProjectFile).filter(ProjectFile.project_id == req.project_id).all()
    dependency_graph = {f.path: f.imports for f in files}

    mermaid_code = generate_mermaid_diagram(dependency_graph)

    db.add(
        GeneratedArtifact(
            project_id=req.project_id, 
            kind="diagram", 
            content=mermaid_code,
        )
    )
    db.commit()
    log_action(
    db=db,
    action="GENERATE_DIAGRAM",
    project_id=req.project_id,
    details={
        "type": "mermaid",
    },
)

    return {"mermaid": mermaid_code, "cached": False}
