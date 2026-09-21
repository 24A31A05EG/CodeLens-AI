import fnmatch
import os
from typing import List, Optional

from services.analysis.redact import is_secret_file, redact_secrets

# Directories to skip while walking an uploaded/cloned repo.
# Dependency, build-output, cache and VCS folders never contain project logic
# and can be enormous, so they are excluded from analysis entirely.
IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", ".next", ".idea", ".vscode",
    ".nuxt", ".svelte-kit", ".turbo", ".cache", ".parcel-cache",
    "coverage", ".nyc_output", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".eggs", "site-packages", "__MACOSX", ".gradle", ".dart_tool",
}

EXT_TO_LANG = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
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
    ".toml": "TOML",
    ".md": "Markdown",
}

# Well-known extension-less / .txt project files that carry real meaning.
# Matched on the lower-cased basename only, so arbitrary ``.txt`` files remain
# unsupported (single-file uploads of e.g. ``notes.txt`` are still rejected).
KNOWN_FILENAMES = {
    "dockerfile": "Dockerfile",
    "requirements.txt": "pip requirements",
}
KNOWN_FILENAME_GLOBS = {
    "requirements*.txt": "pip requirements",
    "dockerfile.*": "Dockerfile",
}

# Generated / dependency-lock files: large, machine-written, no explanatory value.
LOCKFILES = {
    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
    "composer.lock", "poetry.lock", "pipfile.lock", "cargo.lock",
}

# Files above this size are almost always bundles/generated output.
MAX_FILE_BYTES = int(os.getenv("CODELENS_MAX_FILE_KB", "1024")) * 1024


def language_for(filename: str) -> Optional[str]:
    """Language label for a file name, or None if the file is not supported."""
    base = os.path.basename(filename.replace("\\", "/")).lower()
    if base in KNOWN_FILENAMES:
        return KNOWN_FILENAMES[base]
    for pattern, language in KNOWN_FILENAME_GLOBS.items():
        if fnmatch.fnmatch(base, pattern):
            return language
    return EXT_TO_LANG.get(os.path.splitext(base)[1])


def is_supported_file(filename: str) -> bool:
    """True when the file type may be uploaded/analysed and is not secret-bearing."""
    return language_for(filename) is not None and not is_secret_file(filename)


def supported_description() -> str:
    names = sorted(EXT_TO_LANG) + sorted(KNOWN_FILENAMES) + sorted(KNOWN_FILENAME_GLOBS)
    return ", ".join(names)


def _should_skip_file(filename: str, full_path: str) -> bool:
    base = filename.lower()
    if is_secret_file(filename):
        return True  # .env, private keys, credential stores: never ingested
    if base in LOCKFILES:
        return True
    if base.endswith((".min.js", ".min.css", ".bundle.js", ".chunk.js")):
        return True
    try:
        if os.path.islink(full_path) or os.path.getsize(full_path) > MAX_FILE_BYTES:
            return True
    except OSError:
        return True
    return False


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
            language = language_for(filename)
            if language is None:
                continue  # skip binary/unrecognized files for now
            if _should_skip_file(filename, full_path):
                continue
            files.append({"path": rel_path, "language": language, "full_path": full_path})
    files.sort(key=lambda item: item["path"])  # deterministic ordering
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


MAX_CHUNK_LINES = 120


def _window_chunks(lines: List[str], max_lines: int, overlap: int = 10) -> List[str]:
    step = max(max_lines - overlap, 1)
    chunks = []
    start = 0
    while start < len(lines):
        chunk = "".join(lines[start: start + max_lines])
        if chunk.strip():
            chunks.append(chunk)
        if start + max_lines >= len(lines):
            break
        start += step
    return chunks


def chunk_file(
    full_path: str,
    symbols: List[str],
    max_lines: int = 60,
    symbol_lines: Optional[List[int]] = None,
) -> List[str]:
    """
    Split a source file into text chunks suitable for retrieval.

    Strategy:
    1. If ``symbol_lines`` (0-indexed start lines of functions/classes/
       components, produced by the static analyzer) is given, split at those
       boundaries. Code before the first symbol (imports, header comments) is
       kept as its own preamble chunk so "how does X start / what does it
       import" questions can still be answered. Over-long units are further
       split into overlapping windows.
    2. Otherwise, legacy behaviour: split on lines whose text matches an
       extracted symbol string.
    3. Fallback: fixed-size sliding window of ``max_lines`` lines with a
       10-line overlap.

    Every chunk is passed through ``redact_secrets`` before being returned, so
    secret-looking values never reach the chunk store or any prompt built from it.
    """
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return []

    if not lines:
        return []

    starts: List[int] = []
    if symbol_lines:
        starts = sorted({n for n in symbol_lines if 0 <= n < len(lines)})
    elif symbols:
        symbol_set = set(symbols)
        for i, line in enumerate(lines):
            name = line.strip().split("(")[0].split("{")[0].strip()
            if name in symbol_set:
                starts.append(i)

    chunks: List[str] = []
    if starts:
        boundaries = ([0] if starts[0] > 0 else []) + starts + [len(lines)]
        for i in range(len(boundaries) - 1):
            block = lines[boundaries[i]: boundaries[i + 1]]
            if not "".join(block).strip():
                continue
            if len(block) > MAX_CHUNK_LINES:
                chunks.extend(_window_chunks(block, MAX_CHUNK_LINES))
            else:
                chunks.append("".join(block))
    else:
        chunks = _window_chunks(lines, max_lines)

    return [redact_secrets(chunk) for chunk in chunks]


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
