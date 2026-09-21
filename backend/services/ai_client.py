"""
AI service boundary for CodeLens.

The optional Gemini integration lives behind these functions. The deterministic
project-analysis pipeline remains the source of truth and fallback: uploads can be
parsed, files can be explained, docs can be created, diagrams are valid Mermaid,
and /ask can answer from retrieved chunks even without an external model.
"""

import ast
import math
import os
import re
from typing import Dict, Iterable, List, Optional

from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
except ImportError:  # Optional until Gemini is enabled/installed.
    genai = None

from services.analysis.redact import redact_secrets

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "700"))
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.2"))
ENABLE_GEMINI = os.getenv("CODELENS_ENABLE_GEMINI", "0") == "1"

_MOCK_EMBED_DIM = 384

LEVEL_INSTRUCTIONS = {
    "beginner": "Explain in one or two plain-English sentences, no jargon.",
    "developer": "Explain what the code does and how, at a working-developer level.",
    "technical": "Give a precise, technical explanation including edge cases and complexity.",
}


def _call_model(prompt: str) -> Optional[str]:
    """Call Gemini when enabled, otherwise return ``None``.

    Static analysis remains the fallback. Gemini failures are logged so the
    integration can be diagnosed instead of failing silently.
    """
    # Safe diagnostics: never print the API key itself.
    if not (ENABLE_GEMINI and GEMINI_API_KEY and genai is not None):
        print(
            "[Gemini] NOT CALLED:",
            f"enabled={ENABLE_GEMINI}",
            f"key_present={bool(GEMINI_API_KEY)}",
            f"sdk_loaded={genai is not None}",
            f"model={GEMINI_MODEL}",
        )
        return None

    try:
        # Use the stable Gemini API version explicitly.
        client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options={"api_version": "v1", "timeout": 15000},
        )
        interaction = client.interactions.create(
            model=GEMINI_MODEL,
            input=prompt,
            generation_config={
                "max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS,
                "thinking_level": "low",
            },
        )

        text = getattr(interaction, "output_text", None)
        if text is None:
            # Compatibility with SDK response objects that expose steps.
            steps = getattr(interaction, "steps", None) or []
            for step in reversed(steps):
                content = getattr(step, "content", None)
                if isinstance(content, list):
                    for item in reversed(content):
                        candidate = getattr(item, "text", None)
                        if candidate:
                            text = candidate
                            break
                if text:
                    break

        if text:
            print(f"[Gemini] SUCCESS: model={GEMINI_MODEL}")
            return str(text).strip()

        print("[Gemini] ERROR: API returned no output text")
        return None

    except Exception as exc:
        # Do not print the API key.
        print(f"[Gemini] ERROR: {type(exc).__name__}: {exc}")
        return None


def _mock_embedding(text: str) -> List[float]:
    raw = [0.0] * _MOCK_EMBED_DIM
    for index, char in enumerate(text):
        raw[index % _MOCK_EMBED_DIM] += ord(char)
    magnitude = math.sqrt(sum(value * value for value in raw)) or 1.0
    return [value / magnitude for value in raw]


def _trim_list(values: Iterable[str], limit: int = 8) -> List[str]:
    cleaned = [value for value in values if value]
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + [f"and {len(cleaned) - limit} more"]


def _split_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    symbol = symbol.replace("async def ", "")
    symbol = symbol.replace("def ", "")
    symbol = symbol.replace("class ", "")
    symbol = symbol.replace("function ", "")
    symbol = symbol.replace("export ", "")
    return symbol.strip()


def _generic_summary(code: str) -> Dict[str, List[str]]:
    functions = []
    classes = []
    imports = []

    function_pattern = re.compile(
        r"(?:^|\s)(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|"
        r"(?:^|\s)(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(|"
        r"^\s*def\s+([A-Za-z_][\w]*)|"
        r"^\s*class\s+([A-Za-z_][\w]*)"
    )

    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ", "#include", "require(")):
            imports.append(stripped[:120])

        match = function_pattern.search(line)
        if not match:
            continue
        matched = next((group for group in match.groups() if group), None)
        if not matched:
            continue
        if stripped.startswith("class "):
            classes.append(matched)
        else:
            functions.append(matched)

    return {"functions": functions, "classes": classes, "imports": imports}


def _python_summary(code: str) -> Optional[Dict[str, List[str]]]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    functions = []
    classes = []
    imports = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported = ", ".join(alias.name for alias in node.names)
            imports.append(f"{module}: {imported}" if module else imported)

    return {"functions": functions, "classes": classes, "imports": imports}


def _summarize_code(code: str) -> Dict[str, List[str]]:
    return _python_summary(code) or _generic_summary(code)


def _describe_symbols(summary: Dict[str, List[str]]) -> str:
    parts = []
    functions = _trim_list(summary.get("functions", []))
    classes = _trim_list(summary.get("classes", []))
    imports = _trim_list(summary.get("imports", []), limit=5)

    if classes:
        parts.append("classes: " + ", ".join(classes))
    if functions:
        parts.append("functions: " + ", ".join(functions))
    if imports:
        parts.append("imports: " + ", ".join(imports))

    return "; ".join(parts) if parts else "top-level code or configuration"


def _fallback_explain_code(code_snippet: str, level: str, file_path: Optional[str]) -> str:
    summary = _summarize_code(code_snippet)
    target = f"`{file_path}`" if file_path else "This file"
    symbol_text = _describe_symbols(summary)
    line_count = len(code_snippet.splitlines())

    if level == "beginner":
        return f"{target} contains {symbol_text}. In simple terms, it organizes code that the project can run or reuse."

    if level == "technical":
        return (
            f"{target} has {line_count} lines and contains {symbol_text}. "
            "The extracted symbols define the main callable or reusable units; imports indicate dependencies that should be available when this file runs. "
            "No runtime execution was performed, so this explanation is based on static parsing."
        )

    return (
        f"{target} contains {symbol_text}. "
        "It contributes reusable project logic through its detected functions/classes and depends on the listed imports where present. "
        "This explanation was generated from static code analysis."
    )


def _symbol_names(file_info: dict) -> List[str]:
    return [_split_symbol(symbol) for symbol in file_info.get("symbols") or []]


def _fallback_readme(project_summary: dict) -> str:
    name = project_summary.get("name") or "Uploaded Project"
    files = project_summary.get("files") or []
    languages = sorted({file_info.get("language") for file_info in files if file_info.get("language")})

    lines = [
        f"# {name}",
        "",
        "## Overview",
        "",
        "This project was analyzed by CodeLens AI. The backend parsed the uploaded source files, extracted symbols, and prepared the project for explanations, documentation, diagrams, and codebase Q&A.",
        "",
        "## Languages",
        "",
        ", ".join(languages) if languages else "No supported source files were detected.",
        "",
        "## Project Structure",
        "",
    ]

    if files:
        for file_info in files:
            symbols = _symbol_names(file_info)
            detail = f" - {', '.join(symbols)}" if symbols else ""
            lines.append(f"- `{file_info.get('path')}` ({file_info.get('language', 'Unknown')}){detail}")
    else:
        lines.append("- No parsed files available.")

    lines.extend(
        [
            "",
            "## Generated Artifacts",
            "",
            "Use `/explain` for file explanations, `/generate-docs` for documentation, `/generate-diagram` for architecture, and `/history` to view prior analysis results.",
        ]
    )
    return "\n".join(lines)


def _fallback_api_docs(project_summary: dict) -> str:
    name = project_summary.get("name") or "Uploaded Project"
    files = project_summary.get("files") or []
    lines = [
        f"# {name} API Documentation",
        "",
        "## Detected Code Surface",
        "",
    ]

    if not files:
        lines.append("No functions, classes, or route-like symbols were detected.")
        return "\n".join(lines)

    for file_info in files:
        symbols = _symbol_names(file_info)
        lines.append(f"### `{file_info.get('path')}`")
        lines.append("")
        if symbols:
            lines.extend(f"- `{symbol}`" for symbol in symbols)
        else:
            lines.append("- No public symbols detected by the static parser.")
        lines.append("")

    lines.append("These docs are generated from static symbols. Add richer route parsing when extending the model-assisted pipeline.")
    return "\n".join(lines)


def _module_candidates(import_line: str) -> List[str]:
    stripped = import_line.strip()
    candidates = []

    # ES6: import ... from './module' or import ... from "module"
    if "from " in stripped and (stripped.startswith("import ") or stripped.startswith("from ")):
        match = re.search(r"""from\s+['"]([^'"]+)['"]""", stripped)
        if match:
            raw = match.group(1).replace("./", "").replace("../", "")
            candidates.extend([raw, raw.split("/")[-1]])
        elif stripped.startswith("from "):
            # Python: from x.y import z
            parts = stripped.split()
            if len(parts) >= 2:
                module = parts[1]
                candidates.extend([module, module.split(".")[-1]])
    elif stripped.startswith("import "):
        # JS: import './module' or Python: import a, b
        match = re.search(r"""['"]([^'"]+)['"]""", stripped)
        if match:
            raw = match.group(1).replace("./", "").replace("../", "")
            candidates.extend([raw, raw.split("/")[-1]])
        else:
            module_text = stripped[len("import ") :]
            for part in module_text.split(","):
                part_cleaned = part.strip().split()[0] if part.strip() else ""
                if part_cleaned:
                    candidates.extend([part_cleaned, part_cleaned.split(".")[-1]])
    elif (
        stripped.startswith(("const ", "let ", "var "))
        and "require(" in stripped
    ):
        match = re.search(r"""require\(['"]([^'"]+)['"]\)""", stripped)
        if match:
            module = match.group(1).replace("./", "").replace("../", "")
            candidates.extend([module, module.split("/")[-1]])

    return [candidate.replace("-", "_").strip(" .;") for candidate in candidates if candidate]


def _node_id(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", path).strip("_") or "root"


def generate_mermaid_diagram(dependency_graph: dict) -> str:
    prompt = (
        "Convert this module dependency graph into valid Mermaid flowchart syntax.\n"
        f"Dependency graph:\n{dependency_graph}"
    )
    model_response = _call_model(prompt)
    if model_response:
        return model_response

    paths = list(dependency_graph.keys())
    module_to_path = {}
    for path in paths:
        normalized = path.replace("\\", "/")
        stem = os.path.splitext(os.path.basename(normalized))[0]
        dotted = os.path.splitext(normalized)[0].replace("/", ".")
        module_to_path[stem] = path
        module_to_path[dotted] = path
        module_to_path[dotted.split(".")[-1]] = path

    lines = ["graph TD"]
    for path in paths:
        lines.append(f'  {_node_id(path)}["{path}"]')

    edges = set()
    for source, imports in dependency_graph.items():
        for import_line in imports or []:
            for candidate in _module_candidates(import_line):
                target = module_to_path.get(candidate)
                if target and target != source:
                    edges.add((source, target))

    for source, target in sorted(edges):
        lines.append(f"  {_node_id(source)} --> {_node_id(target)}")

    if not paths:
        lines.append('  empty["No parsed files"]')
    elif not edges:
        lines.append('  note["No internal imports detected"]')

    return "\n".join(lines)


def embed_text(text: str) -> List[float]:
    return _mock_embedding(text)


def explain_code(code_snippet: str, level: str = "developer", file_path: Optional[str] = None) -> str:
    code_snippet = redact_secrets(code_snippet)
    instruction = LEVEL_INSTRUCTIONS.get(level, LEVEL_INSTRUCTIONS["developer"])
    prompt = f"{instruction}\n\nCode:\n```\n{code_snippet}\n```"
    model_response = _call_model(prompt)
    if model_response:
        return model_response
    return _fallback_explain_code(code_snippet, level, file_path)


def generate_readme(project_summary: dict) -> str:
    prompt = (
        "Write a concise README.md for this project based on its structure.\n\n"
        f"Project structure summary:\n{project_summary}"
    )
    model_response = _call_model(prompt)
    if model_response:
        return model_response
    return _fallback_readme(project_summary)


def generate_api_docs(routes_summary: dict) -> str:
    prompt = (
        "Generate API documentation from this route/function summary:\n"
        f"{routes_summary}"
    )
    model_response = _call_model(prompt)
    if model_response:
        return model_response
    return _fallback_api_docs(routes_summary)


def answer_question(question: str, retrieved_chunks: List[str]) -> str:
    context = "\n\n---\n\n".join(retrieved_chunks)
    prompt = (
        "Answer the question using only the provided code context. Cite file paths where relevant.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    model_response = _call_model(prompt)
    if model_response:
        return model_response

    if not retrieved_chunks:
        return "I could not find relevant code context for that question."

    first_chunk = retrieved_chunks[0]
    source = "the most relevant file"
    if first_chunk.startswith("# "):
        source = first_chunk.splitlines()[0].replace("# ", "").strip()
    explanation = _fallback_explain_code(first_chunk, "developer", source)
    return f"Based on `{source}`, {explanation}"


# ---------------------------------------------------------------------------
# Project-aware entry points (static analysis first, model optional)
# ---------------------------------------------------------------------------

MAX_PROMPT_CHARS = 12000


def build_file_prompt(analysis: dict, path: str, level: str, static_text: str) -> str:
    """
    Context pack for a model call about ONE file of ONE project.

    Contains: the level instruction, the project summary, the file's facts and
    graph relationships (already computed locally), and the static explanation.
    Bounded in size and passed through secret redaction. It never includes any
    other project's data because ``analysis`` belongs to a single project.
    """
    instruction = LEVEL_INSTRUCTIONS.get(level, LEVEL_INSTRUCTIONS["developer"])
    ctx = analysis["context"]
    prompt = (
        f"{instruction}\n\n"
        f"Project: {ctx['name']} - {ctx['project_type']}\n{ctx['summary']}\n\n"
        f"File: {path}\n"
        f"Verified facts and relationships (from static analysis):\n{static_text}\n\n"
        "Rewrite the explanation for the requested audience. Use only the facts above; "
        "do not invent files, functions or behaviour."
    )
    return redact_secrets(prompt)[:MAX_PROMPT_CHARS]


def explain_file(analysis: dict, path: str, level: str = "developer") -> Optional[dict]:
    """Project-aware explanation. Returns {text, relations, source} or None if the file is unknown."""
    from services.analysis.explainer import explain_file as static_explain

    result = static_explain(analysis, path, level)
    if result is None:
        return None
    source = "static-analysis"
    model_text = _call_model(build_file_prompt(analysis, path, level, result["text"]))
    if model_text:
        result["text"] = redact_secrets(model_text)
        source = "ai-assisted (Google Gemini)"
    result["source"] = source
    return result


def answer_project_question(analysis: dict, chunks: list, question: str, top_k: int = 5,
                            threshold: float = 0.0) -> dict:
    """Project-aware answer for Ask Codebase. Static composition; model synthesis if enabled."""
    from services.analysis.retrieval import answer_question as static_answer

    result = static_answer(analysis, chunks, question, top_k=top_k, threshold=threshold)
    result["answer_source"] = "static-analysis"
    prompt = redact_secrets(
        "Answer the question using only the verified facts below. Cite file paths.\n\n"
        f"Facts:\n{result['answer']}\n\nQuestion: {question}"
    )[:MAX_PROMPT_CHARS]
    model_text = _call_model(prompt)
    if model_text:
        result["answer"] = redact_secrets(model_text)
        result["answer_source"] = "ai-assisted (Google Gemini)"
    return result
