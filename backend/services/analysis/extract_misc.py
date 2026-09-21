"""
Static fact extraction for non-code-centric files: JSON / package.json /
tsconfig, YAML / docker-compose / CI, TOML, Markdown, HTML, CSS / SCSS,
Dockerfile, requirements.txt, SQL, and a lower-confidence generic extractor
for other programming languages.

Nothing here executes or evaluates file content. Values whose *key names*
look secret are never stored.
"""

import json
import os
import re
from typing import Dict, List, Optional

from services.analysis.knowledge import NPM_TECH, PY_TECH, package_root_name
from services.analysis.redact import looks_secret_key, redact_secrets

# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def _strip_jsonc(text: str) -> str:
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i = text.find("*/", i + 2)
            i = n if i == -1 else i + 1
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _safe_scalar(key: str, value):
    if looks_secret_key(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_secrets(value)[:120]
    return value


def extract_json_facts(text: str, path: str) -> Dict:
    base = os.path.basename(path).lower()
    facts: Dict = {"kind_hint": "json", "confidence": "high", "details": {}}
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = json.loads(_strip_jsonc(text))
        except ValueError:
            facts["confidence"] = "low"
            facts["warnings"] = ["invalid JSON"]
            return facts

    if base == "package.json" and isinstance(data, dict):
        scripts = {k: redact_secrets(str(v))[:160] for k, v in (data.get("scripts") or {}).items()}
        deps = data.get("dependencies") or {}
        dev = data.get("devDependencies") or {}
        peer = data.get("peerDependencies") or {}
        facts["kind_hint"] = "package_manifest"
        facts["details"] = {
            "name": data.get("name"), "version": data.get("version"),
            "description": redact_secrets(str(data.get("description") or ""))[:200] or None,
            "type": data.get("type"), "main": data.get("main"), "module": data.get("module"),
            "private": data.get("private"), "scripts": scripts,
            "dependencies": {k: str(v) for k, v in deps.items()},
            "devDependencies": {k: str(v) for k, v in dev.items()},
            "peerDependencies": {k: str(v) for k, v in peer.items()},
            "workspaces": data.get("workspaces"), "engines": data.get("engines"),
        }
        return facts

    if re.match(r"^(ts|js)config(\..+)?\.json$", base) and isinstance(data, dict):
        co = data.get("compilerOptions") or {}
        facts["kind_hint"] = "compiler_config"
        facts["details"] = {
            "compilerOptions": {k: _safe_scalar(k, co[k]) for k in
                                ("target", "module", "moduleResolution", "jsx", "strict", "baseUrl", "outDir", "lib", "allowJs", "noEmit")
                                if k in co},
            "paths": sorted((co.get("paths") or {}).keys()),
            "include": data.get("include"), "exclude": data.get("exclude"),
            "references": [r.get("path") for r in data.get("references", []) if isinstance(r, dict)],
            "extends": data.get("extends"),
        }
        return facts

    if isinstance(data, dict):
        facts["details"] = {
            "top_level_keys": sorted(data.keys())[:40],
            "shape": {k: (type(v).__name__ if not isinstance(v, (dict, list)) else f"{type(v).__name__}({len(v)})")
                      for k, v in list(data.items())[:40]},
        }
    elif isinstance(data, list):
        facts["details"] = {"top_level": f"array({len(data)})"}
    return facts


# ---------------------------------------------------------------------------
# YAML / TOML
# ---------------------------------------------------------------------------

_YAML_KEY = re.compile(r"^(?P<k>[A-Za-z_][\w.\-]*)\s*:(?:\s|$)")


def extract_yaml_facts(text: str, path: str) -> Dict:
    base = os.path.basename(path).lower()
    norm = path.replace("\\", "/").lower()
    lines = text.splitlines()
    top_keys = [m.group("k") for ln in lines if (m := _YAML_KEY.match(ln))]
    facts: Dict = {"kind_hint": "yaml", "confidence": "medium",
                   "details": {"top_level_keys": top_keys[:30]}}

    def children(parent: str) -> List[str]:
        out, inside = [], False
        for ln in lines:
            if re.match(rf"^{parent}\s*:", ln):
                inside = True
                continue
            if inside:
                if ln.strip() and not ln.startswith((" ", "\t")):
                    break
                m = re.match(r"^ {2}([A-Za-z_][\w.\-]*)\s*:", ln)
                if m:
                    out.append(m.group(1))
        return out

    if base.startswith("docker-compose") or (("services" in top_keys) and ("compose" in base)):
        services = children("services")
        images = re.findall(r"^\s+image:\s*([^\s#]+)", text, re.M)
        ports = re.findall(r"^\s+-\s*['\"]?(\d+:\d+)", text, re.M)
        facts["kind_hint"] = "compose"
        facts["details"].update({"services": services, "images": images[:12], "ports": ports[:12]})
    elif ".github/workflows/" in norm:
        facts["kind_hint"] = "ci_workflow"
        name = re.search(r"^name:\s*(.+)$", text, re.M)
        facts["details"].update({"name": name.group(1).strip() if name else None, "jobs": children("jobs")})
    elif base in {"pnpm-lock.yaml"}:
        facts["kind_hint"] = "lockfile"
    return facts


def extract_toml_facts(text: str, path: str) -> Dict:
    facts: Dict = {"kind_hint": "toml", "confidence": "high", "details": {}}
    try:
        import tomllib  # Python 3.11+
        data = tomllib.loads(text)
    except Exception:
        facts["confidence"] = "low"
        facts["details"] = {"top_level_keys": re.findall(r"^\[([^\]]+)\]", text, re.M)[:30]}
        return facts
    base = os.path.basename(path).lower()
    if base == "pyproject.toml":
        proj = data.get("project") or {}
        poetry = (data.get("tool") or {}).get("poetry") or {}
        deps = proj.get("dependencies") or list((poetry.get("dependencies") or {}).keys())
        facts["kind_hint"] = "python_project"
        facts["details"] = {
            "name": proj.get("name") or poetry.get("name"),
            "version": proj.get("version") or poetry.get("version"),
            "description": redact_secrets(str(proj.get("description") or poetry.get("description") or ""))[:200] or None,
            "dependencies": [re.split(r"[<>=!~\[; ]", str(d), 1)[0] for d in deps if d != "python"][:60],
            "requires_python": proj.get("requires-python"),
            "build_backend": (data.get("build-system") or {}).get("build-backend"),
            "tools": sorted((data.get("tool") or {}).keys()),
            "scripts": sorted((proj.get("scripts") or {}).keys()),
        }
    else:
        facts["details"] = {"top_level_keys": sorted(data.keys())[:40]}
    return facts


# ---------------------------------------------------------------------------
# Dockerfile / requirements
# ---------------------------------------------------------------------------


def extract_dockerfile_facts(text: str) -> Dict:
    stages, expose, env_names, run_cmds = [], [], [], []
    workdir = cmd = entry = None
    copies = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kw, _, rest = line.partition(" ")
        kw = kw.upper()
        if kw == "FROM":
            stages.append(rest.split()[0] if rest.split() else "")
        elif kw == "WORKDIR":
            workdir = rest.strip()
        elif kw in {"COPY", "ADD"}:
            copies += 1
        elif kw == "RUN":
            run_cmds.append(redact_secrets(rest.strip())[:100])
        elif kw == "EXPOSE":
            expose += rest.split()
        elif kw == "CMD":
            cmd = redact_secrets(rest.strip())[:160]
        elif kw == "ENTRYPOINT":
            entry = redact_secrets(rest.strip())[:160]
        elif kw in {"ENV", "ARG"}:
            env_names.append(re.split(r"[= ]", rest.strip(), 1)[0])
    return {
        "kind_hint": "dockerfile", "confidence": "high",
        "details": {"base_images": stages, "workdir": workdir, "expose": expose, "cmd": cmd,
                    "entrypoint": entry, "copy_steps": copies, "run_steps": run_cmds[:6],
                    "env_names": sorted(set(env_names))[:20], "multi_stage": len(stages) > 1},
    }


def extract_requirements_facts(text: str) -> Dict:
    pkgs = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)$", line)
        if m:
            pkgs.append({"name": m.group(1), "spec": m.group(3).strip() or None})
    return {"kind_hint": "python_requirements", "confidence": "high", "details": {"packages": pkgs}}


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

_COMMAND_START = re.compile(
    r"^\s*(?:\$\s*)?(npm|npx|yarn|pnpm|pip3?|python3?|uvicorn|gunicorn|flask|docker(?:-compose)?|make|pytest|node|cargo|go|mvn|gradle|bundle|rails|poetry|conda|bun|deno)\b(.*)$"
)
_SECTION_KEYS = {
    "install": ("install", "setup", "getting started", "quick start", "quickstart", "requirements", "prerequisites"),
    "usage": ("usage", "run", "running", "start", "how to use", "commands"),
    "architecture": ("architecture", "design", "structure", "overview", "how it works", "project structure"),
    "api": ("api", "endpoints", "routes", "reference"),
    "testing": ("test", "testing"),
    "license": ("license", "licence"),
    "contributing": ("contributing", "contribute"),
    "configuration": ("config", "configuration", "environment", "env"),
}


def extract_markdown_facts(text: str) -> Dict:
    headings, commands, sections = [], [], set()
    in_fence, first_para = False, None
    buf: List[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            m = _COMMAND_START.match(line)
            if m:
                commands.append(redact_secrets(line.strip().lstrip("$ ").strip())[:120])
            continue
        hm = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", line)
        if hm:
            title = hm.group(2).strip()
            headings.append({"level": len(hm.group(1)), "text": title[:100]})
            low = title.lower()
            for key, words in _SECTION_KEYS.items():
                if any(w in low for w in words):
                    sections.add(key)
            continue
        if first_para is None:
            if line.strip() and not line.startswith(("<", "![", "[!", "|", ">", "-", "*")):
                buf.append(line.strip())
            elif buf:
                first_para = " ".join(buf)
    if first_para is None and buf:
        first_para = " ".join(buf)
    return {
        "kind_hint": "markdown", "confidence": "high",
        "summary_hint": redact_secrets(first_para)[:300] if first_para else None,
        "details": {
            "headings": headings[:40], "commands": commands[:15], "sections": sorted(sections),
            "title": next((h["text"] for h in headings if h["level"] == 1), None),
            "word_count": len(text.split()),
        },
    }


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def extract_html_facts(text: str) -> Dict:
    scripts, styles = [], []
    for m in re.finditer(r"<script\b([^>]*)>", text, re.I):
        attrs = m.group(1)
        src = re.search(r"""src\s*=\s*["']([^"']+)["']""", attrs, re.I)
        if src:
            scripts.append({"src": src.group(1), "module": bool(re.search(r"""type\s*=\s*["']module["']""", attrs, re.I))})
    inline = len(re.findall(r"<script\b(?![^>]*\bsrc\b)[^>]*>", text, re.I))
    for m in re.finditer(r"<link\b([^>]*)>", text, re.I):
        attrs = m.group(1)
        if re.search(r"""rel\s*=\s*["']stylesheet["']""", attrs, re.I):
            href = re.search(r"""href\s*=\s*["']([^"']+)["']""", attrs, re.I)
            if href:
                styles.append(href.group(1))
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    mount = re.findall(r"""<div[^>]*\bid\s*=\s*["'](root|app|__next|main)["']""", text, re.I)
    landmarks = {}
    for tag in ("header", "nav", "main", "section", "article", "aside", "footer", "form", "canvas", "table"):
        c = len(re.findall(rf"<{tag}\b", text, re.I))
        if c:
            landmarks[tag] = c
    return {
        "kind_hint": "html", "confidence": "high",
        "details": {
            "title": re.sub(r"\s+", " ", title.group(1)).strip()[:120] if title else None,
            "scripts": scripts, "inline_scripts": inline, "stylesheets": styles,
            "mount_points": mount, "landmarks": landmarks,
            "viewport_meta": bool(re.search(r"""name\s*=\s*["']viewport["']""", text, re.I)),
            "lang": (re.search(r"<html[^>]*\blang\s*=\s*[\"']([\w-]+)", text, re.I) or [None, None])[1],
        },
    }


# ---------------------------------------------------------------------------
# CSS / SCSS
# ---------------------------------------------------------------------------


def extract_css_facts(text: str, scss: bool = False) -> Dict:
    clean = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    if scss:
        clean = re.sub(r"(?m)//.*$", "", clean)
    classes = set(re.findall(r"(?<![\w#\d])\.(-?[A-Za-z_][\w-]*)", re.sub(r"\{[^}]*\}", "{}", clean)))
    ids = set(re.findall(r"#([A-Za-z_][\w-]*)\s*[{,:.\s>+~\[]", re.sub(r"\{[^}]*\}", "{}", clean)))
    media = sorted({re.sub(r"\s+", " ", m.strip()) for m in re.findall(r"@media\s*([^{]+)\{", clean)})
    keyframes = sorted(set(re.findall(r"@keyframes\s+([\w-]+)", clean)))
    custom_props = sorted(set(re.findall(r"(--[\w-]+)\s*:", clean)))
    fonts = sorted(set(re.findall(r"font-family\s*:\s*['\"]?([^;'\"{},]+)", clean)))[:6]
    prop = lambda pat: len(re.findall(pat, clean, re.I))  # noqa: E731
    rule_count = len(re.findall(r"\{", clean))
    selectors = re.findall(r"(?m)^\s*([^@{}\n][^{}]*?)\s*\{", clean)
    return {
        "kind_hint": "stylesheet", "confidence": "high",
        "details": {
            "rule_count": rule_count, "selector_sample": [s.strip()[:60] for s in selectors[:8]],
            "class_count": len(classes), "classes_sample": sorted(classes)[:12], "id_count": len(ids),
            "media_queries": media[:10], "keyframes": keyframes, "custom_properties": custom_props[:15],
            "custom_property_count": len(custom_props), "root_vars": ":root" in clean,
            "global_selectors": [s for s in ("html", "body", "*", ":root") if re.search(rf"(?m)(^|,)\s*{re.escape(s)}\s*[,{{]", clean)],
            "layout": {
                "flex": prop(r"display\s*:\s*(?:inline-)?flex"), "grid": prop(r"display\s*:\s*(?:inline-)?grid"),
                "positioned": prop(r"position\s*:\s*(?:absolute|fixed|sticky)"),
            },
            "uses_animation": bool(keyframes) or prop(r"\banimation\s*:") > 0 or prop(r"\btransition\s*:") > 0,
            "transitions": prop(r"\btransition\s*:"),
            "uses_variables": prop(r"var\(\s*--") > 0,
            "gradients": prop(r"gradient\("), "filters": prop(r"backdrop-filter|filter\s*:"),
            "imports": re.findall(r"""@import\s+(?:url\()?['"]([^'"]+)['"]""", clean),
            "font_families": [f.strip() for f in fonts],
            "grid_or_flex_layout": bool(prop(r"display\s*:\s*(?:inline-)?(?:flex|grid)")),
        },
    }


# ---------------------------------------------------------------------------
# SQL & generic languages
# ---------------------------------------------------------------------------


def extract_sql_facts(text: str) -> Dict:
    tables = re.findall(r"create\s+table\s+(?:if\s+not\s+exists\s+)?[`\"\[]?([\w.]+)", text, re.I)
    return {
        "kind_hint": "sql", "confidence": "medium",
        "details": {
            "tables": tables[:30],
            "indexes": len(re.findall(r"create\s+(?:unique\s+)?index", text, re.I)),
            "alters": len(re.findall(r"alter\s+table", text, re.I)),
            "inserts": len(re.findall(r"insert\s+into", text, re.I)),
        },
    }


_GENERIC_IMPORT = [
    re.compile(r"(?m)^\s*import\s+(?:static\s+)?([\w.*]+)\s*;"),        # Java/Kotlin-ish
    re.compile(r"(?m)^\s*using\s+([\w.]+)\s*;"),                        # C#
    re.compile(r"(?m)^\s*use\s+([\w:]+)"),                              # Rust / PHP
    re.compile(r"(?m)^\s*#include\s*[<\"]([^>\"]+)[>\"]"),              # C/C++
    re.compile(r"(?m)^\s*(?:require|require_relative)\s+['\"]([^'\"]+)['\"]"),  # Ruby
    re.compile(r"(?m)^\s*import\s+\"([^\"]+)\""),                       # Go single
    re.compile(r"(?m)^\s+\"([\w./\-]+)\"\s*$"),                         # Go block lines
]
_GENERIC_DEFS = re.compile(
    r"(?m)^\s*(?:(?:public|private|protected|static|final|abstract|async|pub|export|override|virtual|inline|extern)\s+)*"
    r"(?P<kw>class|interface|struct|enum|trait|impl|func|fn|def|function)\s+(?P<name>[A-Za-z_][\w]*)"
)


def extract_generic_facts(text: str, language: str) -> Dict:
    imports = []
    for pat in _GENERIC_IMPORT:
        for m in pat.finditer(text):
            imports.append({"source": m.group(1), "level": 0, "names": [], "imported": [], "line": text[:m.start()].count("\n") + 1, "kind": "import"})
    functions, classes = [], []
    for m in _GENERIC_DEFS.finditer(text):
        line = text[:m.start()].count("\n") + 1
        entry = {"name": m.group("name"), "line": line}
        if m.group("kw") in {"func", "fn", "def", "function"}:
            functions.append({**entry, "params": [], "async": False, "exported": True, "doc": None})
        else:
            classes.append({**entry, "bases": [], "methods": [], "doc": None, "kind": m.group("kw")})
    return {
        "kind_hint": "generic_code", "confidence": "low",
        "imports": imports[:80], "functions": functions[:80], "classes": classes[:50],
        "warnings": [f"{language} is analysed with lightweight pattern matching; relationships may be incomplete"],
    }


# ---------------------------------------------------------------------------
# Technology detection helpers (used by the project context builder)
# ---------------------------------------------------------------------------


def technologies_from_package(details: Dict) -> List[Dict]:
    techs = []
    for group, label in (("dependencies", "runtime"), ("devDependencies", "dev"), ("peerDependencies", "peer")):
        for name in (details.get(group) or {}):
            info = NPM_TECH.get(name)
            techs.append({"name": info[0] if info else name, "package": name, "category": info[1] if info else "other",
                          "scope": label, "known": bool(info), "ecosystem": "npm"})
    return techs


def technologies_from_requirements(packages: List[Dict]) -> List[Dict]:
    techs = []
    for p in packages:
        key = p["name"].lower().replace("_", "-")
        info = PY_TECH.get(key) or PY_TECH.get(p["name"].lower())
        techs.append({"name": info[0] if info else p["name"], "package": p["name"], "category": info[1] if info else "other",
                      "scope": "runtime", "known": bool(info), "ecosystem": "pip"})
    return techs


__all__ = [n for n in dir() if n.startswith("extract_") or n.startswith("technologies_")] + ["package_root_name"]
