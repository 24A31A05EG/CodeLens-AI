"""Change Impact Analyzer and Safe Refactor Planner.

Both features are grounded in the project's stored static relationship graph. Gemini
is used only to explain the verified impact/plan; it does not invent graph edges.
"""
import os
from collections import deque
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import User
from services.access import get_current_user, get_owned_project
from routers.upload import STORAGE_ROOT
from services.analysis.store import ensure_analysis
from services.ai_client import _call_model

router = APIRouter()


def _analysis(db: Session, project):
    return ensure_analysis(db, project, os.path.join(STORAGE_ROOT, project.id))


def _graph_impact(analysis: dict, path: str) -> dict:
    graph = analysis["graph"]
    nodes = graph.get("nodes", {})
    edges = graph.get("edges", [])
    if path not in nodes:
        return None

    incoming: Dict[str, List[dict]] = {}
    outgoing: Dict[str, List[dict]] = {}
    for edge in edges:
        if edge.get("source") in nodes and edge.get("target") in nodes:
            outgoing.setdefault(edge["source"], []).append(edge)
            incoming.setdefault(edge["target"], []).append(edge)

    direct = incoming.get(path, [])
    dependencies = outgoing.get(path, [])

    # Reverse traversal: files that depend on the selected file, then dependents
    # of those files. This models the blast radius of changing the selected file.
    distance: Dict[str, int] = {path: 0}
    queue = deque([path])
    while queue:
        current = queue.popleft()
        for edge in incoming.get(current, []):
            nxt = edge["source"]
            if nxt not in distance:
                distance[nxt] = distance[current] + 1
                queue.append(nxt)

    impacted = [
        {"path": p, "distance": d, "via": incoming.get(p, [{}])[0].get("type", "depends")}
        for p, d in sorted(distance.items(), key=lambda x: (x[1], x[0]))
        if p != path
    ]

    entry_paths = {e.get("path") for e in graph.get("entry_points", [])}
    entry_involved = path in entry_paths or any(x["path"] in entry_paths for x in impacted)

    direct_count = len({e["source"] for e in direct})
    indirect_count = len({x["path"] for x in impacted if x["distance"] > 1})
    endpoint_count = sum(1 for e in graph.get("endpoints", []) if e.get("file") == path)

    # Deterministic score, intentionally simple and explainable.
    score = min(100, direct_count * 12 + indirect_count * 5 + (25 if entry_involved else 0) + endpoint_count * 10)
    if score >= 70:
        level = "HIGH"
    elif score >= 35:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {
        "file": path,
        "role": nodes[path].get("kind") or nodes[path].get("category"),
        "subsystem": nodes[path].get("subsystem"),
        "entry_point": path in entry_paths,
        "direct_dependents": [
            {"path": e["source"], "relation": e.get("type"), "evidence": (e.get("evidence") or [""])[0]}
            for e in direct
        ],
        "dependencies": [
            {"path": e["target"], "relation": e.get("type"), "evidence": (e.get("evidence") or [""])[0]}
            for e in dependencies
        ],
        "impacted_files": impacted[:60],
        "counts": {
            "direct_dependents": direct_count,
            "indirect_dependents": indirect_count,
            "total_impacted": len(impacted),
            "dependencies": len(dependencies),
            "endpoints": endpoint_count,
        },
        "entry_point_involvement": entry_involved,
        "impact_score": score,
        "impact_level": level,
    }


def _gemini_impact(impact: dict, question: str = "") -> Optional[str]:
    prompt = (
        "You are CodeLens-AI's software change-impact assistant. Explain only the verified facts below. "
        "Do not invent files, dependencies, tests, runtime behavior, or relationships. "
        "Give a concise developer-friendly impact assessment with: why the file matters, what is directly affected, "
        "what may be indirectly affected, and what should be checked before changing it. "
        "Distinguish graph evidence from reasonable engineering caution.\n\n"
        f"Verified impact data:\n{impact}\n\n"
        f"Developer request: {question or 'Explain the change impact.'}"
    )
    return _call_model(prompt)


class ImpactRequest(BaseModel):
    project_id: str
    file_path: str
    question: str = ""


class RefactorRequest(BaseModel):
    project_id: str
    file_path: str
    proposed_change: str


@router.post("/impact")
def change_impact(
    req: ImpactRequest,
    include_ai: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(req.project_id, db, current_user)
    if project.status != "ready":
        raise HTTPException(400, "Project is not ready for impact analysis.")
    analysis = _analysis(db, project)
    if not analysis:
        raise HTTPException(400, "Project architecture analysis is not available.")
    impact = _graph_impact(analysis, req.file_path)
    if impact is None:
        raise HTTPException(404, "File was not found in the analyzed project.")
    # Deterministic impact analysis is returned immediately by default. Gemini is
    # an optional enhancement so a slow model/network call cannot block the UI.
    ai = _gemini_impact(impact, req.question) if include_ai else None
    return {**impact, "ai_explanation": ai, "source": "ai-assisted (Google Gemini)" if ai else "static-analysis", "ai_pending": not include_ai}


@router.post("/safe-refactor")
def safe_refactor(
    req: RefactorRequest,
    include_ai: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(req.project_id, db, current_user)
    if project.status != "ready":
        raise HTTPException(400, "Project is not ready for refactor planning.")
    analysis = _analysis(db, project)
    if not analysis:
        raise HTTPException(400, "Project architecture analysis is not available.")
    impact = _graph_impact(analysis, req.file_path)
    if impact is None:
        raise HTTPException(404, "File was not found in the analyzed project.")

    affected = [x["path"] for x in impact["impacted_files"]]
    plan = []
    plan.append(f"Review the proposed change to `{req.file_path}`: {req.proposed_change}.")
    plan.append(f"Check {len(impact['direct_dependents'])} direct dependent file(s) first.")
    if affected:
        plan.append("Verify affected files in dependency order: " + ", ".join(affected[:12]) + (" and more." if len(affected) > 12 else "."))
    else:
        plan.append("No dependent files were detected by the current project graph.")
    if impact["entry_point_involvement"]:
        plan.append("Because the change touches the entry-point path or its dependents, run the application smoke test after the change.")
    if impact["counts"]["endpoints"]:
        plan.append("The selected file is associated with detected API endpoints; verify those endpoint flows after the change.")
    plan.append("Run the project's detected test/lint/build commands before merging when available.")

    ai_prompt = (
        "Create a safe, concise refactor plan using ONLY these verified CodeLens facts. "
        "Do not claim that tests exist unless stated. Do not modify code. Include: pre-change checks, ordered affected files, "
        "validation steps, and rollback considerations.\n\n"
        f"Selected file: {req.file_path}\nProposed change: {req.proposed_change}\n"
        f"Verified impact graph: {impact}\n"
    )
    ai = _call_model(ai_prompt) if include_ai else None
    return {
        "file": req.file_path,
        "proposed_change": req.proposed_change,
        "impact": impact,
        "plan": plan,
        "ai_plan": ai,
        "source": "ai-assisted (Google Gemini)" if ai else "static-analysis",
        "ai_pending": not include_ai,
    }
