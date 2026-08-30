import os
from typing import List

# Directories to skip while walking an uploaded/cloned repo.
IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", ".next", ".idea", ".vscode",
}

EXT_TO_LANG = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".cpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".php": "PHP",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
}


def walk_repo(root_path: str):
    """
    Walks a directory and returns a list of {path, language, full_path} dicts,
    skipping common noise directories. `path` is relative to root_path.
    """
    files = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_path).replace("\\", "/")
            ext = os.path.splitext(filename)[1].lower()
            language = EXT_TO_LANG.get(ext)
            if language is None:
                continue  # skip binary/unrecognized files for now
            files.append({"path": rel_path, "language": language, "full_path": full_path})
    return files


def extract_symbols(full_path: str, language: str):
    """
    Regex/line-scan symbol extractor. Returns (symbols, imports) lists.
    Supports Python, JS/TS, Java, Go, Rust, C/C++, C#, etc.
    """
    symbols, imports = [], []
    symbol_prefixes = (
        "def ", "async def ", "class ", "function ", "async function ",
        "export function ", "export async function ", "export class ",
        "export const ", "export let ", "export var ",
        "public ", "private ", "protected ", "static ",
        "fn ", "pub fn ", "func ", "interface ", "struct ", "type "
    )
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith(symbol_prefixes):
                    cleaned = stripped.split("{")[0].split("(")[0].strip()
                    if cleaned and len(cleaned) < 100:
                        symbols.append(cleaned)
                elif stripped.startswith(("import ", "from ", "#include", "require(")):
                    imports.append(stripped)
    except OSError:
        pass
    return symbols, imports


def chunk_file(full_path: str, symbols: List[str], max_lines: int = 60) -> List[str]:
    """
    Split a source file into text chunks suitable for embedding.

    Strategy (judgment call — see notes in ask.py):
    1. If the file has extracted symbols, split on symbol boundaries so each
       chunk starts at a recognised function/class definition.  This keeps
       semantically coherent units together.
    2. Fallback: fixed-size sliding window of `max_lines` lines with a 10-line
       overlap so context isn't lost at boundaries.

    JUDGMENT CALL — max_lines=60: at ~40 chars/line that's ≈2 400 chars /
    chunk, well inside typical embedding model context windows (512 tokens).
    Tune downward if you see truncation warnings from the real embedder.
    """
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return []

    if not lines:
        return []

    # Build a set of line numbers where a symbol starts (0-indexed)
    symbol_starts: list[int] = []
    if symbols:
        symbol_set = set(symbols)
        for i, line in enumerate(lines):
            stripped = line.strip()
            name = stripped.split("(")[0].split("{")[0].strip()
            if name in symbol_set:
                symbol_starts.append(i)

    if symbol_starts:
        # Chunk per symbol: from this symbol's line to the next symbol's line
        boundaries = symbol_starts + [len(lines)]
        return [
            "".join(lines[boundaries[i]: boundaries[i + 1]])
            for i in range(len(symbol_starts))
            if "".join(lines[boundaries[i]: boundaries[i + 1]]).strip()
        ]

    # Fallback: fixed-size window with 10-line overlap
    overlap = 10
    step = max(max_lines - overlap, 1)
    chunks = []
    start = 0
    while start < len(lines):
        chunk = "".join(lines[start: start + max_lines])
        if chunk.strip():
            chunks.append(chunk)
        start += step
    return chunks


def parse_project(root_path: str):
    """
    Full pipeline: walk the repo, extract symbols per file.
    Returns a list ready to insert as ProjectFile rows.
    Each dict also carries 'full_path' so the caller can chunk the file.
    """
    results = []
    for file_info in walk_repo(root_path):
        symbols, imports = extract_symbols(file_info["full_path"], file_info["language"])
        results.append({
            "path": file_info["path"],
            "language": file_info["language"],
            "full_path": file_info["full_path"],
            "symbols": symbols,
            "imports": imports,
        })
    return results
