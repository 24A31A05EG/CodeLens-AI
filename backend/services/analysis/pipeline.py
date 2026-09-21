"""
Run the full static-analysis pipeline for ONE project directory:
walk -> per-file facts -> relationship graph -> project context.
"""

import logging
from typing import Dict, List, Optional

from services.analysis.context import build_project_context
from services.analysis.extractors import build_import_lines, build_symbols, extract_file
from services.analysis.graph import build_graph

ANALYSIS_VERSION = 1
MAX_ANALYZED_FILES = 3000
logger = logging.getLogger(__name__)


def analyze_files(parsed_files: List[Dict], project_name: str) -> Optional[Dict]:
    """``parsed_files``: output of ``parser.walk_repo`` ({path, language, full_path})."""
    facts: Dict[str, Dict] = {}
    for item in parsed_files[:MAX_ANALYZED_FILES]:
        try:
            f = extract_file(item["path"], item["language"], item["full_path"])
        except Exception:  # one bad file must never sink the project
            logger.exception("analysis failed for a file; skipping it")
            f = None
        if f is not None:
            facts[item["path"]] = f
    if not facts:
        return None
    graph = build_graph(facts)
    context = build_project_context(project_name, facts, graph)
    return {"version": ANALYSIS_VERSION, "files": facts, "graph": graph, "context": context}


def legacy_columns(facts: Dict):
    """(symbols, import_lines, chunk_symbol_lines) for the legacy ProjectFile/Chunk columns."""
    symbols, lines = build_symbols(facts)
    return symbols, build_import_lines(facts), lines
