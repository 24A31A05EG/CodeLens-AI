"""
POST /ask — "Ask Your Codebase" semantic Q&A endpoint.

Flow (project analysis available - the normal case):
  1. Load the project's stored analysis (facts + relationship graph + context)
  2. Detect the question intent and rank files by path/symbol/tag/lexical
     relevance plus graph neighbourhood
  3. Compose an answer from the graph and facts (startup trace, file location,
     dependencies, stack, API, overview or concept explanation)
  4. Return the answer, ranked sources with reasons, and the detected intent

Legacy flow (only when no analysis can be built for the project):
  embed the question, rank chunks by cosine similarity, answer from the top chunk.
  NOTE: the bundled embedding is a mock, so this path is retrieval-by-accident;
  it exists only as a fallback.

JUDGMENT CALLS documented inline:
  - k=5 top chunks
  - similarity threshold = 0.0 (no hard cutoff for the demo — all chunks
    are considered; raise to e.g. 0.3 when using real embeddings to avoid
    irrelevant context)
  - Cosine similarity computed in-process (pure Python, fine for demo scale
    of a few hundred chunks per project).  When you move to Postgres+pgvector,
    replace the in-process ranking with a single SQL ORDER BY ... <=> query.
"""

import math
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.db_models import Chunk, User
from services.access import get_current_user, get_owned_project
from routers.upload import STORAGE_ROOT
from services.ai_client import answer_project_question, answer_question, embed_text
from services.analysis.store import chunk_pairs, ensure_analysis

router = APIRouter()

TOP_K = int(os.getenv("ASK_TOP_K", "5"))
SIMILARITY_THRESHOLD = float(os.getenv("ASK_SIMILARITY_THRESHOLD", "0.0"))


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Pure-Python cosine similarity for demo-scale chunk counts."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class AskRequest(BaseModel):
    project_id: str
    question: str


@router.post("")
def ask(
    req: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not req.question.strip():
        raise HTTPException(400, "question must not be empty.")

    project = get_owned_project(req.project_id, db, current_user)

    # ── Status guard ─────────────────────────────────────────────────────────
    if project.status == "processing":
        return JSONResponse(
            status_code=202,
            content={"detail": "Project is still being parsed."},
        )
    if project.status == "failed":
        raise HTTPException(400, "Project parsing failed; please re-upload.")

    # ── Project-aware path (analysis available) ───────────────────────────────
    analysis = ensure_analysis(db, project, os.path.join(STORAGE_ROOT, project.id))
    if analysis:
        pairs = chunk_pairs(db, req.project_id)
        if not pairs:
            raise HTTPException(
                404,
                "No searchable chunks found for this project. "
                "The project may still be indexing or the files contained no parseable code.",
            )
        result = answer_project_question(
            analysis, pairs, req.question, top_k=TOP_K, threshold=SIMILARITY_THRESHOLD
        )
        return {
            "answer": result["answer"],
            "sources": [
                {"file_path": s["file_path"], "score": round(s["score"], 4), "reason": s.get("reason")}
                for s in result["sources"]
            ],
            "intent": result["intent"],
            "related_files": result["related_files"],
            "answer_source": result["answer_source"],
        }

    # ── Legacy path: embed the question ───────────────────────────────────────
    try:
        q_embedding = embed_text(req.question)
    except Exception as exc:
        raise HTTPException(500, f"Embedding failed: {exc}") from exc

    # ── Load chunks (only those that have embeddings) ────────────────────────
    chunks = (
        db.query(Chunk)
        .filter(Chunk.project_id == req.project_id, Chunk.embedding.isnot(None))
        .all()
    )

    if not chunks:
        raise HTTPException(
            404,
            "No searchable chunks found for this project. "
            "The project may still be indexing or the files contained no parseable code.",
        )

    # ── Rank by cosine similarity ─────────────────────────────────────────────
    scored = [
        (chunk, _cosine_similarity(q_embedding, chunk.embedding))
        for chunk in chunks
    ]
    scored.sort(key=lambda t: t[1], reverse=True)

    top = [
        (chunk, score)
        for chunk, score in scored[:TOP_K]
        if score >= SIMILARITY_THRESHOLD
    ]

    if not top:
        return {
            "answer": "No sufficiently relevant code was found for your question.",
            "sources": [],
        }

    # ── Build context and call the model ──────────────────────────────────────
    context_chunks = [
        f"# {chunk.file_path}\n{chunk.chunk_text}"
        for chunk, _ in top
    ]
    answer = answer_question(req.question, context_chunks)

    # De-duplicate source paths while preserving rank order
    seen: set[str] = set()
    sources = []
    for chunk, score in top:
        if chunk.file_path not in seen:
            seen.add(chunk.file_path)
            sources.append({"file_path": chunk.file_path, "score": round(score, 4)})

    return {"answer": answer, "sources": sources}
