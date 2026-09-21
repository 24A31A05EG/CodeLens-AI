import os
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import ProjectFile, User
from routers.upload import STORAGE_ROOT
from services.access import get_current_user, get_owned_project
from services.analysis.store import ensure_analysis

router = APIRouter()


def _ready_analysis(project, db):
    """(analysis, early_response). Shared guard for the analysis-backed endpoints."""
    if project.status == "processing":
        return None, JSONResponse(status_code=202, content={"detail": "Project is still being parsed."})
    if project.status == "failed":
        raise HTTPException(400, "Project parsing failed; please re-upload.")
    analysis = ensure_analysis(db, project, os.path.join(STORAGE_ROOT, project.id))
    if analysis is None:
        raise HTTPException(404, "No analysis is available for this project.")
    return analysis, None


@router.get("/{project_id}/structure")
def get_structure(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(project_id, db, current_user)

    files = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()
    language_counts = Counter(f.language for f in files if f.language)

    nodes = {}
    if project.status == "ready":
        analysis = ensure_analysis(db, project, os.path.join(STORAGE_ROOT, project.id))
        if analysis:
            nodes = analysis["graph"]["nodes"]

    def describe(f):
        item = {"path": f.path, "language": f.language, "symbol_count": len(f.symbols or [])}
        node = nodes.get(f.path)
        if node:
            item.update({"kind": node["kind"], "category": node["category"],
                         "subsystem": node["subsystem"], "entry": node["entry"]})
        return item

    return {
        "project_id": project_id,
        "status": project.status,
        "file_count": len(files),
        "languages": dict(language_counts),
        "files": [describe(f) for f in files],
        "analysis_available": bool(nodes),
    }


@router.get("/{project_id}/overview")
def get_overview(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Project-level understanding: type, stack, entry points, subsystems, API, commands."""
    project = get_owned_project(project_id, db, current_user)
    analysis, early = _ready_analysis(project, db)
    if early:
        return early
    return {"project_id": project_id, **analysis["context"]}


@router.get("/{project_id}/graph")
def get_graph(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """File relationship graph (nodes, typed edges with evidence, endpoints, entry points)."""
    project = get_owned_project(project_id, db, current_user)
    analysis, early = _ready_analysis(project, db)
    if early:
        return early
    g = analysis["graph"]
    return {
        "project_id": project_id,
        "nodes": list(g["nodes"].values()),
        "edges": [{k: e[k] for k in ("source", "target", "type", "kinds", "evidence", "confidence")} for e in g["edges"]],
        "endpoints": g["endpoints"],
        "entry_points": g["entry_points"],
        "stats": g["stats"],
    }
