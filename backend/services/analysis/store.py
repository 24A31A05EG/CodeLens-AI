"""
Persist and load the analysis of ONE project.

``ensure_analysis`` is the single entry point used by routers: it returns the
stored analysis, or (re)builds it from the project's files on disk when it is
missing or was produced by an older analyzer version. Rebuilding stamps a new
``created_at``, which invalidates older cached explanations/docs/diagrams for
that project (see ``is_stale``).
"""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from models.db_models import FileAnalysis, Project, ProjectAnalysis
from services.analysis.pipeline import ANALYSIS_VERSION, analyze_files
from services.parser import walk_repo

logger = logging.getLogger(__name__)


def save_analysis(db: Session, project_id: str, analysis: Dict) -> ProjectAnalysis:
    db.query(FileAnalysis).filter(FileAnalysis.project_id == project_id).delete()
    db.query(ProjectAnalysis).filter(ProjectAnalysis.project_id == project_id).delete()
    row = ProjectAnalysis(
        project_id=project_id, version=analysis["version"],
        context=analysis["context"], graph=analysis["graph"], created_at=datetime.utcnow(),
    )
    db.add(row)
    for path, facts in analysis["files"].items():
        db.add(FileAnalysis(project_id=project_id, path=path, facts=facts))
    db.commit()
    return row


def load_analysis(db: Session, project_id: str) -> Optional[Dict]:
    row = db.query(ProjectAnalysis).filter(ProjectAnalysis.project_id == project_id).first()
    if row is None or row.version != ANALYSIS_VERSION:
        return None
    files = {
        r.path: r.facts
        for r in db.query(FileAnalysis).filter(FileAnalysis.project_id == project_id).all()
    }
    return {"version": row.version, "created_at": row.created_at, "context": row.context,
            "graph": row.graph, "files": files}


def ensure_analysis(db: Session, project: Project, repo_path: str) -> Optional[Dict]:
    """Stored analysis, rebuilt from disk if missing/outdated. ``None`` if impossible."""
    existing = load_analysis(db, project.id)
    if existing is not None:
        return existing
    if not os.path.isdir(repo_path):
        return None
    try:
        analysis = analyze_files(walk_repo(repo_path), project.name)
        if analysis is None:
            return None
        row = save_analysis(db, project.id, analysis)
    except Exception:
        db.rollback()
        logger.exception("could not build analysis for project %s", project.id)
        return None
    analysis["created_at"] = row.created_at
    return analysis


def is_stale(cached_at: Optional[datetime], analysis: Optional[Dict]) -> bool:
    """A cached artifact older than the current analysis must be regenerated."""
    if analysis is None or cached_at is None:
        return False
    created = analysis.get("created_at")
    return bool(created and cached_at < created)


def chunk_pairs(db: Session, project_id: str) -> List[Tuple[str, str]]:
    from models.db_models import Chunk
    return [(c.file_path, c.chunk_text)
            for c in db.query(Chunk).filter(Chunk.project_id == project_id).all()]
