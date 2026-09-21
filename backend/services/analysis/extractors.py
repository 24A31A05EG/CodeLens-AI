"""
Per-file analysis entry point: read a file, run the right extractor for its
type, classify its role, and tag its capabilities.

The result (``FileFacts``) is a plain JSON-serialisable dict. Every code-like
fact key always exists (possibly empty) so downstream consumers never need to
guard against missing keys.
"""

import os
import re
from typing import Dict, List, Optional, Tuple

from services.analysis import extract_misc as misc
from services.analysis.extract_js import extract_js_facts
from services.analysis.extract_py import extract_python_facts
from services.analysis.knowledge import DIR_CONVENTIONS, config_purpose, is_three_intrinsic, package_root_name
from services.analysis.redact import redact_secrets

MAX_ANALYZE_BYTES = 512 * 1024

JS_LANGS = {"JavaScript", "TypeScript"}
GENERIC_LANGS = {"Java", "Go", "Ruby", "Rust", "C++", "C", "C#", "PHP"}

# Which kind ids belong to which coarse category.
KIND_CATEGORY = {
    "component": "code", "hook": "code", "api_router": "code", "app_setup": "code",
    "data_model": "code", "schema": "code", "database": "code", "service": "code",
    "utility": "code", "state_store": "code", "api_client": "code", "module": "code",
    "package_init": "code", "script": "code", "test": "test", "code_config": "config",
    "package_manifest": "config", "build_config": "config", "lint_config": "config",
    "compiler_config": "config", "test_config": "config", "config": "config",
    "dependency_list": "config", "container": "infra", "compose": "infra", "ci_workflow": "infra",
    "documentation": "docs", "stylesheet": "style", "markup": "markup", "data": "data",
    "sql": "data", "lockfile": "data",
}


def _default_facts(path: str, language: str) -> Dict:
    return {
        "path": path, "language": language, "kind": "module", "category": "code", "tags": [],
        "imports": [], "bindings": {}, "exports": {"default": None, "named": []},
        "functions": [], "classes": [], "types": [], "components": [], "custom_hooks": [],
        "hooks_used": {}, "jsx": {"components": {}, "intrinsic": {}}, "props": {}, "state": [],
        "events": [], "routes": [], "router_prefixes": {}, "include_routers": [], "api_calls": [],
        "models": [], "env_vars": [], "db_usage": [], "calls": [], "renders": [],
        "entry_signals": [], "app_objects": [], "side_effects": [], "three_classes": [],
        "gsap_calls": [], "component_detail": {}, "test_functions": [],
        "summary_hint": None, "details": {}, "warnings": [], "confidence": "medium",
        "line_count": 0, "size_bytes": 0,
    }


def _read_text(full_path: str) -> Tuple[str, int, bool]:
    size = os.path.getsize(full_path)
    truncated = size > MAX_ANALYZE_BYTES
    with open(full_path, "r", encoding="utf-8-sig", errors="ignore") as fh:  # -sig: tolerate a BOM
        text = fh.read(MAX_ANALYZE_BYTES)
    return text, size, truncated


def _dir_parts(path: str) -> List[str]:
    return [p.lower() for p in path.replace("\\", "/").split("/")[:-1]]


def _is_test_path(path: str) -> bool:
    low = path.lower().replace("\\", "/")
    base = os.path.basename(low)
    return bool(
        re.search(r"(^|/)(tests?|__tests__|spec)/", low)
        or re.match(r"^test_.*\.py$|.*_test\.py$|.*\.(test|spec)\.[cm]?[jt]sx?$", base)
    )


def classify(facts: Dict) -> None:
    """Assign ``kind`` / ``category`` from path + extracted facts (mutates ``facts``)."""
    path, lang = facts["path"], facts["language"]
    base = os.path.basename(path).lower()
    dirs = _dir_parts(path)
    hint = facts.get("kind_hint")
    kind = "module"

    if hint == "package_manifest":
        kind = "package_manifest"
    elif hint == "compiler_config":
        kind = "compiler_config"
    elif hint == "python_requirements":
        kind = "dependency_list"
    elif hint == "dockerfile":
        kind = "container"
    elif hint == "compose":
        kind = "compose"
    elif hint == "ci_workflow":
        kind = "ci_workflow"
    elif hint == "lockfile":
        kind = "lockfile"
    elif hint == "python_project":
        kind = "config"
    elif hint == "markdown":
        kind = "documentation"
    elif hint == "stylesheet":
        kind = "stylesheet"
    elif hint == "html":
        kind = "markup"
    elif hint == "sql":
        kind = "sql"
    elif lang in {"JSON", "YAML", "TOML"}:
        purpose = config_purpose(base)
        kind = "config" if purpose else "data"
    elif _is_test_path(path):
        kind = "test"
    elif lang in JS_LANGS or lang == "Python" or lang in GENERIC_LANGS:
        purpose = config_purpose(base)
        if purpose:
            if re.match(r"^(vite|webpack|rollup|next|postcss|tailwind|babel)", base):
                kind = "build_config"
            elif re.match(r"^(eslint|\.eslintrc|prettier|\.prettierrc)", base):
                kind = "lint_config"
            elif re.match(r"^(jest|vitest)", base):
                kind = "test_config"
            else:
                kind = "config"
        elif facts["components"]:
            kind = "component"
        elif facts["custom_hooks"] and not facts["components"]:
            kind = "hook"
        elif facts["app_objects"] or "http_listen" in facts["entry_signals"]:
            kind = "app_setup"
        elif facts["routes"]:
            kind = "api_router"
        elif any(m["kind"] == "orm" for m in facts["models"]):
            kind = "data_model"
        elif facts["models"] and len(facts["models"]) >= max(1, len(facts["classes"]) // 2):
            kind = "schema"
        elif any(u in facts["db_usage"] for u in ("create_engine()", "sessionmaker()", "scoped_session()", "create_async_engine()")):
            kind = "database"
        elif base == "__init__.py":
            kind = "package_init"
        elif base.split(".")[0] in {"config", "settings", "constants", "conf"} and lang == "Python":
            kind = "code_config"
        elif set(dirs) & {"store", "stores", "state", "context", "contexts", "redux"}:
            kind = "state_store"
        elif set(dirs) & {"services", "service"}:
            kind = "service"
        elif set(dirs) & {"utils", "util", "helpers", "lib", "shared", "common"}:
            kind = "utility"
        elif facts["api_calls"] and not facts["components"]:
            kind = "api_client"
        elif set(dirs) & {"scripts", "bin"} or "dunder_main" in facts["entry_signals"]:
            kind = "script"
        elif lang == "Python" and facts["functions"] and not facts["classes"] and not facts["routes"]:
            kind = "module"
        else:
            kind = "module"

    facts["kind"] = kind
    facts["category"] = KIND_CATEGORY.get(kind, "code")


def derive_tags(facts: Dict) -> List[str]:
    tags = set()
    ext_names = {package_root_name(i["source"]).lower() for i in facts["imports"] if not i["source"].startswith((".", "/"))}
    intrinsic = facts.get("jsx", {}).get("intrinsic", {}) or {}
    if "react" in ext_names or facts["components"]:
        tags.add("react")
    if ext_names & {"three", "@react-three/fiber", "@react-three/drei", "@react-three/postprocessing"} or any(is_three_intrinsic(t) for t in intrinsic):
        tags.add("3d")
    if "@react-three/fiber" in ext_names or "useFrame" in facts["hooks_used"]:
        tags.add("r3f")
    if ext_names & {"gsap", "framer-motion", "motion", "lottie-web", "@react-spring/web"} or "useFrame" in facts["hooks_used"] or facts["gsap_calls"]:
        tags.add("animation")
    if facts["routes"]:
        tags.add("api")
    if facts["api_calls"]:
        tags.add("api-client")
    if any(m["kind"] == "orm" for m in facts["models"]) or facts["db_usage"] or ext_names & {"sqlalchemy", "mongoose", "prisma", "sequelize", "psycopg2", "pymongo"}:
        tags.add("database")
    if ext_names & {"openai", "anthropic", "langchain", "ibm_watsonx_ai", "transformers", "torch", "tensorflow", "sklearn"}:
        tags.add("ai")
    if ext_names & {"fastapi", "flask", "django", "starlette", "express", "koa", "fastify"}:
        tags.add("web-framework")
    if facts["state"] or {"useState", "useReducer"} & set(facts["hooks_used"]):
        tags.add("state")
    if facts["kind"] == "stylesheet":
        tags.add("styling")
    return sorted(tags)


def build_symbols(facts: Dict) -> Tuple[List[str], List[int]]:
    """Legacy ``ProjectFile.symbols`` strings + 0-indexed chunk boundary lines."""
    symbols: List[str] = []
    lines: List[int] = []
    lang = facts["language"]
    for f in facts["functions"]:
        if lang == "Python":
            symbols.append(("async def " if f.get("async") else "def ") + f["name"])
        elif f.get("is_component"):
            symbols.append(f"component {f['name']}")
        elif f.get("is_hook"):
            symbols.append(f"hook {f['name']}")
        else:
            symbols.append(f"function {f['name']}")
        lines.append(max(f["line"] - 1, 0))
    for c in facts["classes"]:
        symbols.append(f"class {c['name']}")
        lines.append(max(c["line"] - 1, 0))
    for t in facts.get("types", []):
        symbols.append(f"type {t}")
    seen, uniq = set(), []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq, lines


def build_import_lines(facts: Dict) -> List[str]:
    """Normalised one-line import statements (replaces truncated multi-line captures)."""
    out = []
    for i in facts["imports"]:
        if facts["language"] == "Python":
            dots = "." * i.get("level", 0)
            if i.get("kind") == "from":
                out.append(f"from {dots}{i['source']} import {', '.join(i.get('imported') or ['*'])}")
            else:
                out.append(f"import {i['source']}")
        elif facts["language"] in JS_LANGS:
            names = []
            if i.get("default"):
                names.append(i["default"])
            if i.get("namespace"):
                names.append(f"* as {i['namespace']}")
            if i.get("names"):
                names.append("{ " + ", ".join(i["names"]) + " }")
            clause = ", ".join(names)
            out.append(f"import {clause} from '{i['source']}'" if clause else f"import '{i['source']}'")
        else:
            out.append(f"import {i['source']}")
    return out[:200]


def extract_file(rel_path: str, language: str, full_path: str) -> Optional[Dict]:
    """Analyse one file. Returns ``None`` if it cannot be read."""
    try:
        text, size, truncated = _read_text(full_path)
    except OSError:
        return None

    facts = _default_facts(rel_path, language)
    facts["size_bytes"] = size
    facts["line_count"] = text.count("\n") + 1 if text else 0
    if truncated:
        facts["warnings"].append("file is large; only the first 512 KB were analysed")
    # very long average lines => minified / generated
    if text and size > 20_000 and len(text) / max(facts["line_count"], 1) > 300 and language in JS_LANGS | {"CSS"}:
        facts["warnings"].append("looks minified or generated; detailed analysis skipped")
        facts["kind"], facts["category"] = "module", "code"
        facts["confidence"] = "low"
        return facts

    base = os.path.basename(rel_path).lower()
    extra: Optional[Dict] = None

    if language in JS_LANGS:
        extra = extract_js_facts(text, rel_path, language)
    elif language == "Python":
        extra = extract_python_facts(text, rel_path)
        if extra is None:
            extra = misc.extract_generic_facts(text, language)
            extra["warnings"] = ["Python syntax error; analysed with pattern matching only"]
    elif language == "JSON":
        extra = misc.extract_json_facts(text, rel_path)
    elif language == "YAML":
        extra = misc.extract_yaml_facts(text, rel_path)
    elif language == "TOML":
        extra = misc.extract_toml_facts(text, rel_path)
    elif language == "Markdown":
        extra = misc.extract_markdown_facts(text)
    elif language == "HTML":
        extra = misc.extract_html_facts(text)
    elif language in {"CSS", "SCSS"}:
        extra = misc.extract_css_facts(text, scss=(language == "SCSS"))
    elif language == "Dockerfile":
        extra = misc.extract_dockerfile_facts(text)
    elif language == "pip requirements":
        extra = misc.extract_requirements_facts(text)
    elif language == "SQL":
        extra = misc.extract_sql_facts(text)
    else:
        extra = misc.extract_generic_facts(text, language)

    if extra:
        warnings = extra.pop("warnings", [])
        facts.update(extra)
        facts["warnings"] = list(facts.get("warnings", [])) + list(warnings)

    classify(facts)
    if facts["kind"] in {"build_config", "lint_config", "test_config", "config"} and language in JS_LANGS:
        facts["details"] = _js_config_details(text)
    facts["tags"] = derive_tags(facts)
    return facts


def _js_config_details(text: str) -> Dict:
    """Top-level option names and plugin calls of a JS tool config (vite/eslint/jest...)."""
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    keys, seen = [], set()
    for m in re.finditer(r"(?m)^ {2,4}['\"]?([A-Za-z_][\w.\-]*)['\"]?\s*:", code):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            keys.append(m.group(1))
    plugins = []
    pm = re.search(r"plugins\s*:\s*\[(?P<body>[^\]]*)\]", code, re.S)
    if pm:
        plugins = [re.sub(r"\(.*", "", p.strip()) for p in pm.group("body").split(",") if p.strip()][:10]
    return {"config_keys": keys[:20], "plugins": plugins}
