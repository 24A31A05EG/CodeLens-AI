"""
Project-aware explanations.

``explain_file(analysis, path, level)`` builds an explanation from three
sources of evidence, all belonging to the SAME project:

1. the file's own extracted facts (functions, hooks, JSX, routes, models ...);
2. its relationships in the project graph (what it imports/renders/calls, and
   what uses it);
3. the project context (subsystem, technologies, startup chain).

The three levels differ in content, not just wording:

* beginner  - what it is and why it exists, in plain language, few terms;
* developer - structured: what/does/key elements/dependencies/used-by/role;
* technical - developer view plus implementation details, evidence lines,
              metrics and the limits of the analysis.

Nothing is copied from a template that ignores the file: every sentence comes
from a fact about this file or its neighbours. Values of secret-looking
settings are never quoted.
"""

import posixpath
from typing import Dict, List, Optional

from services.analysis.knowledge import (
    KIND_LABELS, NPM_TECH, PY_TECH, REACT_HOOK_MEANING, humanize_identifier, is_three_intrinsic,
)
from services.analysis.graph import chain_from_entry
from services.analysis.redact import redact_secrets

# relation text when THIS file is the target (who uses it)
_REL_PHRASE = {
    "renders": "renders this file's component", "mounts": "mounts this router",
    "calls": "calls functions from this file", "loads": "loads this file",
    "styles": "applies these styles", "imports": "imports this file",
}
# relation text when THIS file is the source (what it uses)
_REL_OUT = {
    "renders": "rendered by this file", "mounts": "mounted by this file",
    "calls": "code it calls into", "loads": "loaded by this file",
    "styles": "styles it applies", "imports": "imported by this file",
}


def _bt(text: str) -> str:
    return f"`{text}`"


def _lst(items: List[str], limit: int = 8) -> str:
    items = [i for i in items if i]
    if len(items) > limit:
        return ", ".join(items[:limit]) + f", and {len(items) - limit} more"
    if len(items) > 1:
        return ", ".join(items[:-1]) + " and " + items[-1]
    return items[0] if items else ""


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _tech_label(pkg: str, language: str) -> str:
    info = (NPM_TECH.get(pkg) if language in ("JavaScript", "TypeScript") else PY_TECH.get(pkg.lower())) \
        or NPM_TECH.get(pkg) or PY_TECH.get(pkg.lower())
    return info[0] if info else pkg


def _kind_label(analysis: Dict, path: str) -> str:
    n = analysis["graph"]["nodes"].get(path)
    if not n:
        return "file"
    return KIND_LABELS.get(n["kind"], ("file",))[0]


def _neighbors(analysis: Dict, path: str):
    edges = analysis["graph"]["edges"]
    out = [e for e in edges if e["source"] == path and not e["target"].startswith("endpoint:")]
    inc = [e for e in edges if e["target"] == path]
    return out, inc


def _external_labels(f: Dict) -> List[str]:
    seen, out = set(), []
    for imp in f.get("imports", []):
        ext = imp.get("external")
        if ext and ext not in seen:
            seen.add(ext)
            out.append(_tech_label(ext, f["language"]))
    return out


def _stack_phrase(f: Dict) -> str:
    tags = set(f.get("tags", []))
    if f["kind"] == "component":
        if "r3f" in tags:
            return "React Three Fiber component"
        if "3d" in tags:
            return "React component that uses Three.js"
        return "React component"
    return ""


# ---------------------------------------------------------------------------
# Fact sentences per kind
# ---------------------------------------------------------------------------

def _hook_lines(f: Dict) -> List[str]:
    lines = []
    for hook, cnt in sorted(f.get("hooks_used", {}).items()):
        meaning = REACT_HOOK_MEANING.get(hook)
        if meaning:
            lines.append(f"`{hook}` {meaning}")
    return lines


def _component_does(f: Dict, path: str, analysis: Dict) -> List[str]:
    out: List[str] = []
    comps = f["components"]
    main = f["exports"].get("default") if f["exports"].get("default") in comps else (comps[0] if comps else None)
    tags = set(f["tags"])
    intrinsic = f["jsx"]["intrinsic"]
    three_prims = sorted(t for t in intrinsic if is_three_intrinsic(t))
    plain_html = sorted(t for t in intrinsic if not is_three_intrinsic(t))
    draws_3d = bool(three_prims or f["three_classes"] or "useFrame" in f["hooks_used"])
    hosts_canvas = "Canvas" in f["jsx"]["components"]
    if main:
        subj = humanize_identifier(main)
        if draws_3d:
            out.append(f"Defines the `{main}` component, which builds part of the 3D scene (the name reads as \"{subj}\").")
        elif hosts_canvas:
            out.append(f"Defines the `{main}` component, which hosts the `Canvas` that displays the 3D scene and lays out the page around it.")
        else:
            out.append(f"Defines the `{main}` component (the name reads as \"{subj}\").")
    if len(comps) > 1:
        out.append(f"Also defines {_lst([_bt(c) for c in comps if c != main])}.")
    if three_prims:
        out.append(f"Composes its output from Three.js elements: {_lst([_bt(t) for t in three_prims], 6)}.")
    elif plain_html:
        out.append(f"Renders standard HTML elements: {_lst([_bt(t) for t in plain_html], 6)}.")
    if "useFrame" in f["hooks_used"]:
        out.append("Animates on every frame through `useFrame` (React Three Fiber's render loop).")
    if f["gsap_calls"]:
        out.append(f"Uses GSAP ({', '.join('gsap.' + c for c in f['gsap_calls'])}) for animation.")
    if f["three_classes"]:
        out.append(f"Creates Three.js objects directly: {_lst([_bt(c) for c in f['three_classes']])}.")
    if f["events"]:
        out.append(f"Handles events: {_lst([_bt(e) for e in f['events']], 5)}.")
    return out


def _python_does(f: Dict, path: str, analysis: Dict) -> List[str]:
    out: List[str] = []
    kind = f["kind"]
    endpoints = [e for e in analysis["graph"]["endpoints"] if e["file"] == path]
    if kind == "api_router" or (endpoints and kind != "app_setup"):
        out.append(f"Exposes {_plural(len(endpoints), 'HTTP endpoint')}: " +
                   _lst([f"{_bt(e['method'] + ' ' + e['path'])} → `{e['handler']}()`" for e in endpoints], 6) + ".")
    if kind == "app_setup":
        for app in f["app_objects"]:
            title = f' titled "{app["title"]}"' if app.get("title") else ""
            out.append(f"Creates the {app['framework']} application object `{app['name']}`{title}.")
        mounts = [e for e in analysis["graph"]["edges"] if e["source"] == path and "mounts" in e["kinds"]]
        if mounts:
            out.append("Mounts routers from " + _lst([_bt(m["target"]) for m in mounts]) + ".")
        if endpoints:
            out.append("Defines directly: " + _lst([_bt(f"{e['method']} {e['path']}") for e in endpoints]) + ".")
    for m in f["models"]:
        if m["kind"] == "orm":
            tbl = f" (table `{m['table']}`)" if m.get("table") else ""
            flds = f" with columns {_lst([_bt(x) for x in m['fields']], 6)}" if m["fields"] else ""
            out.append(f"Defines the database model `{m['name']}`{tbl}{flds}.")
        else:
            flds = f" with fields {_lst([_bt(x) for x in m['fields']], 6)}" if m["fields"] else ""
            out.append(f"Defines the validation schema `{m['name']}`{flds}.")
    if kind == "database":
        out.append("Sets up the database connection: " + _lst([_bt(u) for u in f["db_usage"] if u.endswith("()")]) + ".")
    if kind in {"service", "utility", "module", "script", "code_config"}:
        docs = [(fn["name"], fn["doc"]) for fn in f["functions"] if not fn.get("method") and fn.get("doc")]
        funcs = [fn["name"] for fn in f["functions"] if not fn.get("method")]
        if funcs:
            out.append(f"Provides {_plural(len(funcs), 'function')}: {_lst([_bt(n + '()') for n in funcs], 6)}.")
        for n, d in docs[:3]:
            out.append(f"`{n}()`: {d}")
    if kind == "test":
        out.append(f"Contains {_plural(len(f['test_functions']), 'test')}: {_lst([_bt(t) for t in f['test_functions']], 6)}.")
    modelled = {m["name"] for m in f["models"]}
    if f["classes"] and kind not in {"data_model", "schema"}:
        for c in [c for c in f["classes"] if c["name"] not in modelled][:4]:
            m = f" with methods {_lst([_bt(x) for x in c['methods']], 5)}" if c["methods"] else ""
            out.append(f"Defines class `{c['name']}`{m}.")
    if f["env_vars"]:
        out.append(f"Reads configuration from environment variables: {_lst([_bt(v) for v in f['env_vars']])}.")
    return out


def _config_does(f: Dict, path: str, analysis: Dict) -> List[str]:
    d, out, kind = f["details"], [], f["kind"]
    base = posixpath.basename(path)
    if kind == "package_manifest":
        out.append(f"Project `{d.get('name') or '(unnamed)'}`" + (f" v{d['version']}" if d.get("version") else "") + " declares its dependencies and commands here.")
        if d.get("scripts"):
            out.append("npm scripts: " + _lst([f"`{k}` → `{v}`" for k, v in d["scripts"].items()], 8) + ".")
        rt = [_tech_label(k, "JavaScript") for k in d.get("dependencies", {})]
        dev = [_tech_label(k, "JavaScript") for k in d.get("devDependencies", {})]
        if rt:
            out.append(f"Runtime dependencies ({len(rt)}): {_lst(rt, 10)}.")
        if dev:
            out.append(f"Development dependencies ({len(dev)}): {_lst(dev, 10)}.")
    elif kind in {"build_config", "lint_config", "test_config", "config"} and f["language"] in ("JavaScript", "TypeScript"):
        from services.analysis.knowledge import config_purpose
        out.append(f"{config_purpose(base) or 'Tool configuration'}.")
        if d.get("plugins"):
            out.append(f"Enables plugins: {_lst([_bt(p) for p in d['plugins']])}.")
        if d.get("config_keys"):
            out.append(f"Sets options: {_lst([_bt(k) for k in d['config_keys']], 8)}.")
    elif kind == "compiler_config":
        co = d.get("compilerOptions", {})
        out.append("TypeScript/JavaScript compiler settings: " + _lst([f"`{k}` = `{v}`" for k, v in co.items()], 8) + ".")
        if d.get("paths"):
            out.append(f"Path aliases: {_lst([_bt(p) for p in d['paths']])}.")
    elif kind == "dependency_list":
        pk = d.get("packages", [])
        out.append(f"Lists {_plural(len(pk), 'Python package')}: {_lst([_bt(p['name']) for p in pk], 10)}.")
    elif kind == "container":
        out.append(f"Builds a container from `{_lst(d.get('base_images', []))}`" + (f", working in `{d['workdir']}`" if d.get("workdir") else "") + ".")
        if d.get("expose"):
            out.append(f"Exposes port(s) {_lst(d['expose'])}.")
        if d.get("cmd"):
            out.append(f"Starts with: `{d['cmd']}`.")
    elif kind == "compose":
        out.append(f"Defines services: {_lst([_bt(s) for s in d.get('services', [])])}.")
    elif kind == "ci_workflow":
        out.append(f"CI workflow{' ' + repr(d['name']) if d.get('name') else ''} with jobs: {_lst(d.get('jobs', []))}.")
    elif kind == "config" and f.get("kind_hint") == "python_project":
        out.append(f"Python project `{d.get('name')}`" + (f" v{d['version']}" if d.get("version") else "") + ".")
        if d.get("dependencies"):
            out.append(f"Dependencies: {_lst(d['dependencies'], 10)}.")
    else:
        if d.get("top_level_keys"):
            out.append(f"Top-level keys: {_lst([_bt(k) for k in d['top_level_keys']], 10)}.")
    return out


def _doc_style_markup_does(f: Dict, path: str) -> List[str]:
    d, out, kind = f["details"], [], f["kind"]
    if kind == "documentation":
        if d.get("title"):
            out.append(f"Titled \"{d['title']}\".")
        secs = [h["text"] for h in d.get("headings", []) if h["level"] <= 2]
        if secs:
            out.append(f"Sections: {_lst(secs, 8)}.")
        if d.get("commands"):
            out.append(f"Documents commands: {_lst([_bt(c) for c in d['commands']], 5)}.")
    elif kind == "stylesheet":
        out.append(f"Contains {_plural(d.get('rule_count', 0), 'rule')} using {_plural(d.get('class_count', 0), 'class selector')}.")
        if d.get("custom_properties"):
            out.append(f"Defines CSS variables: {_lst([_bt(v) for v in d['custom_properties']], 6)}.")
        if d.get("keyframes"):
            out.append(f"Defines animations: {_lst([_bt(k) for k in d['keyframes']])}.")
        if d.get("media_queries"):
            out.append(f"Responsive rules for: {_lst([_bt(m) for m in d['media_queries']], 4)}.")
        lay = d.get("layout", {})
        if lay.get("flex") or lay.get("grid"):
            out.append(f"Layout uses flexbox ({lay.get('flex', 0)}) and grid ({lay.get('grid', 0)}).")
        if d.get("global_selectors"):
            out.append(f"Sets global base styles on {_lst([_bt(s) for s in d['global_selectors']])}.")
    elif kind == "markup":
        out.append(f"Page titled \"{d.get('title')}\"." if d.get("title") else "HTML page.")
        if d.get("mount_points"):
            out.append(f"Provides the mount point `#{d['mount_points'][0]}` for the JavaScript app.")
        mods = [s["src"] for s in d.get("scripts", []) if s.get("module")]
        if mods:
            out.append(f"Loads the module script {_lst([_bt(m) for m in mods])}.")
    elif kind == "sql":
        out.append(f"Creates tables: {_lst([_bt(t) for t in d.get('tables', [])])}.")
    return out


def _behaviour(f: Dict, path: str, analysis: Dict) -> List[str]:
    kind = f["kind"]
    if f["language"] in ("JavaScript", "TypeScript") and kind in {"component"}:
        return _component_does(f, path, analysis)
    if kind == "hook":
        out = [f"Defines the custom hook {_lst([_bt(h) for h in f['custom_hooks']])}, reusable logic shared by components."]
        out += [f"Internally {l}." for l in _hook_lines(f)[:4]]
        if f["events"]:
            out.append(f"Listens for: {_lst([_bt(e) for e in f['events']])}.")
        return out
    if f["language"] == "Python" or (f["language"] in ("JavaScript", "TypeScript") and kind in {"api_router", "app_setup", "service", "utility", "module", "api_client", "state_store", "script"}):
        if f["language"] == "Python":
            return _python_does(f, path, analysis)
        out = []
        funcs = [fn["name"] for fn in f["functions"]]
        if f["routes"]:
            out.append("Defines routes: " + _lst([_bt(f"{r['method']} {r['path']}") for r in f["routes"]]) + ".")
        if funcs:
            out.append(f"Defines {_plural(len(funcs), 'function')}: {_lst([_bt(n + '()') for n in funcs], 6)}.")
        for call in f["api_calls"][:4]:
            out.append(f"Sends a `{call['method']}` request via {call['via']} to `{call['target'][:60]}`.")
        return out
    if kind in {"package_manifest", "build_config", "lint_config", "test_config", "config", "compiler_config",
                "dependency_list", "container", "compose", "ci_workflow", "data"}:
        return _config_does(f, path, analysis)
    if kind in {"documentation", "stylesheet", "markup", "sql"}:
        return _doc_style_markup_does(f, path)
    # generic code
    out = []
    if f["functions"]:
        out.append(f"Defines {_plural(len(f['functions']), 'function')}: {_lst([_bt(x['name'] + '()') for x in f['functions']], 6)}.")
    if f["classes"]:
        out.append(f"Defines {_plural(len(f['classes']), 'class')}: {_lst([_bt(c['name']) for c in f['classes']], 6)}.")
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def file_relations(analysis: Dict, path: str) -> Dict:
    f = analysis["files"][path]
    graph = analysis["graph"]
    out, inc = _neighbors(analysis, path)
    nodes = graph["nodes"]

    def item(e, other, phrase):
        return {"path": other, "kind": _kind_label(analysis, other), "relation": phrase,
                "type": e["type"], "confidence": e["confidence"], "evidence": e["evidence"][:2]}

    depends = [item(e, e["target"], _REL_OUT.get(e["type"], "imports")) for e in out if e["type"] != "calls_api"]
    api_out = [item(e, e["target"], "calls the API served by") for e in out if e["type"] == "calls_api"]
    used_by = [item(e, e["source"], _REL_PHRASE.get(e["type"], "used by")) for e in inc if e["type"] != "calls_api"]
    used_by += [item(e, e["source"], "calls this file's API from") for e in inc if e["type"] == "calls_api"]

    related, seen = [], {path}
    for r in depends + used_by + api_out:
        if r["path"] not in seen:
            seen.add(r["path"])
            related.append(r["path"])
    # siblings rendered/imported by the same parent
    for e in inc:
        for sib in graph["edges"]:
            if sib["source"] == e["source"] and sib["target"] not in seen and not sib["target"].startswith("endpoint:") \
                    and sib["type"] in {"renders", "mounts"}:
                seen.add(sib["target"])
                related.append(sib["target"])
    node = nodes.get(path, {})
    return {
        "kind": f["kind"], "role": KIND_LABELS.get(f["kind"], ("file",))[0],
        "tags": f["tags"], "subsystem": node.get("subsystem"), "entry": node.get("entry", False),
        "depends_on": depends[:25], "used_by": used_by[:25], "calls_api": api_out[:10],
        "related_files": related[:10], "startup_chain": chain_from_entry(graph, path),
        "confidence": f.get("confidence", "medium"), "warnings": f.get("warnings", []),
        "technologies": _external_labels(f)[:12],
    }


def _identity(f: Dict, path: str, analysis: Dict) -> str:
    kind = f["kind"]
    label = KIND_LABELS.get(kind, ("file",))[0]
    stack = _stack_phrase(f)
    a = "an" if (stack or label)[:1].lower() in "aeiou" else "a"
    lang = f["language"]
    bits = stack or label
    node = analysis["graph"]["nodes"].get(path, {})
    where = f" in the {node['subsystem']} subsystem" if node.get("subsystem") else ""
    if kind == "component" and "3d" in f["tags"] and not stack:
        bits = "UI component"
    return f"{_bt(path)} is {a} {bits} ({lang}){where} of the {analysis['context']['name']} project."


def _fit_lines(f: Dict, path: str, analysis: Dict, rel: Dict) -> List[str]:
    lines = []
    node = analysis["graph"]["nodes"].get(path, {})
    if node.get("entry"):
        reason = next((e["reason"] for e in analysis["graph"]["entry_points"] if e["path"] == path), "")
        lines.append(f"This is an entry point: it {reason}.")
    chain = rel["startup_chain"]
    if len(chain) > 1:
        lines.append("Startup path: " + " → ".join(_bt(p) for p in chain) + ".")
    elif not node.get("entry") and node.get("depth") is None and f["category"] == "code" and f["kind"] not in {"test"}:
        lines.append("It is not reachable from any detected entry point, so it may be unused or loaded dynamically.")
    ctx = analysis["context"]
    if node.get("subsystem") and node.get("dir"):
        peers = [p for p, n in analysis["graph"]["nodes"].items() if n["dir"] == node["dir"] and p != path and n["category"] == "code"]
        if peers:
            lines.append(f"It sits in `{node['dir']}/` ({node['subsystem']}) alongside {_lst([_bt(posixpath.basename(p)) for p in sorted(peers)], 5)}.")
    return lines


def _rel_lines(items: List[Dict], limit: int = 8) -> List[str]:
    out = []
    for r in items[:limit]:
        tag = "" if r["confidence"] == "extracted" else " (inferred)"
        out.append(f"{_bt(r['path'])} ({r['kind']}) — {r['relation']}{tag}")
    if len(items) > limit:
        out.append(f"…and {len(items) - limit} more")
    return out


def explain_file(analysis: Dict, path: str, level: str) -> Optional[Dict]:
    f = analysis["files"].get(path)
    if f is None:
        return None
    level = (level or "developer").lower()
    rel = file_relations(analysis, path)
    behaviour = _behaviour(f, path, analysis)
    identity = _identity(f, path, analysis)
    fit = _fit_lines(f, path, analysis, rel)
    hint = f.get("summary_hint")
    kind_plain = KIND_LABELS.get(f["kind"], ("file", "a file"))[1]

    if level == "beginner":
        text = _beginner(f, path, analysis, rel, behaviour, kind_plain, hint)
    elif level == "technical":
        text = _developer(identity, behaviour, rel, fit, hint, _key_elements(f)) + "\n\n" + _technical_extra(f, path, analysis, rel)
    else:
        text = _developer(identity, behaviour, rel, fit, hint, _key_elements(f))

    return {"text": redact_secrets(text), "relations": rel}


def _beginner(f, path, analysis, rel, behaviour, kind_plain, hint) -> str:
    name = posixpath.basename(path)
    s = [f"{_bt(path)} is {kind_plain}."]
    if hint:
        s.append(f"Its own comment describes it as: \"{redact_secrets(hint.splitlines()[0])[:160]}\".")
    # 1-2 plain observations
    kind = f["kind"]
    if kind == "component":
        subj = humanize_identifier(f["components"][0]) if f["components"] else humanize_identifier(name.split(".")[0])
        if f["three_classes"] or "useFrame" in f["hooks_used"] or any(is_three_intrinsic(t) for t in f["jsx"]["intrinsic"]):
            s.append(f"It draws part of the 3D picture — judging by its name, the \"{subj}\" — and keeps it moving as the page runs.")
        elif "3d" in f["tags"]:
            s.append(f"It sets up the area of the page where the 3D picture is shown (name reads as \"{subj}\").")
        else:
            s.append(f"It draws one part of what you see on screen — judging by its name, the \"{subj}\".")
        kids = [r for r in rel["depends_on"] if r["type"] == "renders"]
        if kids:
            s.append(f"To do that it puts together smaller pieces: {_lst([_bt(posixpath.basename(k['path'])) for k in kids], 4)}.")
    elif kind == "api_router":
        eps = [e for e in analysis["graph"]["endpoints"] if e["file"] == path]
        s.append(f"It answers requests that other programs send to the server — {_plural(len(eps), 'kind')} of request in total, such as {_lst([_bt(e['method'] + ' ' + e['path']) for e in eps], 2)}.")
    elif kind == "app_setup":
        s.append("It creates the server application and connects the other parts to it.")
    elif kind == "data_model":
        s.append(f"It describes what gets stored in the database: {_lst([_bt(m['name']) for m in f['models']])}.")
    elif kind in {"service", "utility", "module"} and f["functions"]:
        s.append(f"It offers ready-made helpers such as {_lst([_bt(x['name']) for x in f['functions'] if not x.get('method')], 3)} for other files to use.")
    elif kind == "package_manifest":
        s.append("It lists the outside libraries the project needs and the short commands used to run or build it.")
    elif kind in {"build_config", "lint_config", "compiler_config", "test_config", "config"}:
        s.append("Tools read it to know how to behave; it contains settings rather than program logic.")
    elif kind == "stylesheet":
        s.append("It sets colours, sizes and layout so the page looks the way it does.")
    elif kind == "markup":
        s.append("It is the first page the browser opens, and it loads the rest of the app.")
    elif kind == "documentation":
        s.append("It explains the project to people, so it is not part of the running program.")
    elif behaviour:
        s.append(behaviour[0].replace("`", ""))
    if rel["used_by"]:
        s.append(f"It is used by {_lst([_bt(posixpath.basename(u['path'])) for u in rel['used_by']], 3)}.")
    elif f["category"] == "code" and f["kind"] not in {"test"} and not rel["entry"]:
        s.append("Nothing else in the project appears to use it directly.")
    if rel["startup_chain"] and len(rel["startup_chain"]) > 1:
        s.append("When the app starts, it is reached through " + " → ".join(_bt(posixpath.basename(p)) for p in rel["startup_chain"]) + ".")
    return " ".join(s)


def _developer(identity, behaviour, rel, fit, hint, key_elements=None) -> str:
    parts = ["What it is:", identity]
    if hint:
        parts.append(f"The file's own description: \"{redact_secrets(hint.splitlines()[0])[:200]}\"")
    if behaviour:
        parts += ["", "What it does:"] + [f"- {b}" for b in behaviour]
    parts_extra = list(key_elements or [])
    if rel["technologies"]:
        parts_extra.append(f"Built with: {_lst(rel['technologies'], 8)}")
    if parts_extra:
        parts += ["", "Key elements:"] + [f"- {p}" for p in parts_extra]
    if rel["depends_on"]:
        parts += ["", "Depends on (inside this project):"] + [f"- {l}" for l in _rel_lines(rel["depends_on"])]
    if rel["used_by"]:
        parts += ["", "Used by:"] + [f"- {l}" for l in _rel_lines(rel["used_by"])]
    if rel["calls_api"]:
        parts += ["", "Talks to the backend:"] + [f"- {l}" for l in _rel_lines(rel["calls_api"])]
    if fit:
        parts += ["", "Role in the project:"] + [f"- {l}" for l in fit]
    return "\n".join(parts)


def _technical_extra(f, path, analysis, rel) -> str:
    lines = ["Implementation details:"]
    lines.append(f"- Size: {f.get('line_count', 0)} lines, {f.get('size_bytes', 0)} bytes; language {f['language']}.")
    if f["language"] == "Python":
        cx = sorted(((fn["complexity"], fn["name"]) for fn in f["functions"]), reverse=True)[:3]
        if cx:
            lines.append("- Most complex functions (branch count): " + _lst([f"`{n}` ({c})" for c, n in cx]) + ".")
        if f["side_effects"]:
            lines.append(f"- Side effects: {_lst(f['side_effects'])}.")
        if f["db_usage"]:
            lines.append(f"- Database operations: {_lst(f['db_usage'])}.")
    else:
        if f["hooks_used"]:
            lines.append("- Hooks: " + _lst([f"`{h}` ×{n} ({REACT_HOOK_MEANING[h]})" if h in REACT_HOOK_MEANING else f"`{h}` ×{n}" for h, n in sorted(f["hooks_used"].items())], 8) + ".")
        if f["state"]:
            lines.append(f"- Local state variables: {_lst([_bt(s) for s in f['state']])}.")
        for comp, props in list(f["props"].items())[:3]:
            lines.append(f"- `{comp}` props: {_lst([_bt(p) for p in props], 8)}.")
        detail = f.get("component_detail", {})
        for comp, d in list(detail.items())[:3]:
            if d.get("renders"):
                lines.append(f"- `{comp}` renders: {_lst([_bt(r) for r in d['renders']], 8)}.")
        ex = f["exports"]
        if ex.get("default") or ex.get("named"):
            bits = []
            if ex.get("default"):
                bits.append(f"default `{ex['default']}`")
            if ex.get("named"):
                bits.append(f"named {_lst([_bt(n) for n in ex['named']])}")
            lines.append("- Exports: " + "; ".join(bits) + ".")
        if f["env_vars"]:
            lines.append(f"- Reads env vars: {_lst([_bt(v) for v in f['env_vars']])}.")
    ext = [i for i in f.get("imports", []) if i.get("external")]
    if ext:
        lines.append(f"- External packages imported: {_lst(sorted({_bt(i['external']) for i in ext}), 10)}.")
    lines += ["", "Relationship evidence:"]
    ev = [(e['type'], e) for e in analysis['graph']['edges'] if e['source'] == path or e['target'] == path]
    shown = 0
    for t, e in ev:
        if e["target"].startswith("endpoint:") and e["source"] != path:
            continue
        other = e["target"] if e["source"] == path else e["source"]
        direction = "→" if e["source"] == path else "←"
        lines.append(f"- {direction} {_bt(other)} [{'/'.join(e['kinds'])}, {e['confidence']}] {e['evidence'][0] if e['evidence'] else ''}")
        shown += 1
        if shown >= 10:
            break
    if shown == 0:
        lines.append("- No relationships to other files were found.")
    lines += ["", "Analysis notes:"]
    lines.append(f"- Extraction confidence: {rel['confidence']} " + ("(parsed with a real syntax tree)." if f["language"] == "Python" and rel["confidence"] == "high" else "(pattern-based analysis; runtime behaviour is not evaluated)."))
    for w in rel["warnings"]:
        lines.append(f"- Warning: {w}")
    return "\n".join(lines)


def _key_elements(f: Dict) -> List[str]:
    """Compact list of the file's main structural elements (names only)."""
    out = []
    for comp, props in list(f.get("props", {}).items())[:2]:
        out.append(f"`{comp}` accepts props: {_lst([_bt(p) for p in props], 6)}")
    if f.get("hooks_used"):
        out.append("Hooks used: " + _lst([_bt(h) for h in sorted(f["hooks_used"])], 8))
    if f.get("state"):
        out.append("State: " + _lst([_bt(x) for x in f["state"]]))
    ex = f.get("exports", {})
    if ex.get("default") and f["language"] != "Python":
        out.append(f"Default export: `{ex['default']}`")
    if f["language"] == "Python" and f.get("classes"):
        out.append("Classes: " + _lst([_bt(c["name"]) for c in f["classes"]], 6))
    return out
