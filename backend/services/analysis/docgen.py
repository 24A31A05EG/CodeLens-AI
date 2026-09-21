"""
Diagram and documentation generation from the project analysis.

Everything here is a pure function of the analysis dict of ONE project:
architecture diagram (Mermaid source + a structured tree the UI can render
without a Mermaid renderer), README and API documentation.
"""

import posixpath
import re
from collections import defaultdict
from typing import Dict, List

from services.analysis.explainer import _lst, _plural
from services.analysis.graph import render_tree
from services.analysis.knowledge import KIND_LABELS
from services.analysis.redact import redact_secrets

MAX_DIAGRAM_NODES = 40
_STRUCT = {"mounts", "renders", "calls", "loads", "imports"}


def _label(text: str) -> str:
    """Make text safe inside a Mermaid quoted label (uploaded names are untrusted)."""
    return re.sub(r'["\[\]{}()<>|`#;\\]', "", text)[:60]


# ---------------------------------------------------------------------------
# Diagram
# ---------------------------------------------------------------------------

def build_mermaid(analysis: Dict) -> str:
    graph, files = analysis["graph"], analysis["files"]
    nodes = graph["nodes"]
    edges = [e for e in graph["edges"]
             if e["target"] in nodes and (e["kinds"] and set(e["kinds"]) & _STRUCT or e["type"] == "calls_api")
             and nodes[e["source"]]["category"] in {"code", "markup", "test"}
             and nodes[e["target"]]["category"] in {"code", "markup"}
             and nodes[e["source"]]["kind"] != "test"]
    if not edges:
        return 'graph TD\n    empty["No relationships between files were detected"]'

    degree: Dict[str, int] = defaultdict(int)
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    entries = {e["path"] for e in graph["entry_points"]}
    ordered = sorted(degree, key=lambda p: (p not in entries, nodes[p]["depth"] if nodes[p]["depth"] is not None else 99, -degree[p], p))
    chosen = set(ordered[:MAX_DIAGRAM_NODES])
    omitted = len(degree) - len(chosen)

    base_count: Dict[str, int] = defaultdict(int)
    for p in chosen:
        base_count[posixpath.basename(p)] += 1
    ids = {p: f"n{i}" for i, p in enumerate(sorted(chosen))}

    def name(p: str) -> str:
        # Keep repository-relative paths visible. Common names such as App.jsx
        # and index.jsx become ambiguous when only the basename is displayed.
        return _label(p)

    lines = ["graph TD"]
    groups: Dict[str, List[str]] = defaultdict(list)
    for p in sorted(chosen):
        sub = nodes[p]["subsystem"]
        groups[f"{sub}|{nodes[p]['dir']}" if sub else ""].append(p)
    gi = 0
    for key, members in sorted(groups.items()):
        if key and len(members) > 1:
            label, d = key.split("|", 1)
            lines.append(f'    subgraph g{gi}["{_label(label)} ({_label(d)})"]')
            gi += 1
            for p in members:
                lines.append(f'        {ids[p]}["{name(p)}"]')
            lines.append("    end")
        else:
            for p in members:
                lines.append(f'    {ids[p]}["{name(p)}"]')
    arrow = {"mounts": ("==>", "mounts"), "renders": ("-->", "renders"), "calls": ("-.->", "calls"),
             "loads": ("-->", "loads"), "imports": ("-->", ""), "calls_api": ("-.->", "HTTP (inferred)")}
    seen = set()
    for e in edges:
        if e["source"] in chosen and e["target"] in chosen and (e["source"], e["target"]) not in seen:
            seen.add((e["source"], e["target"]))
            style, lab = arrow.get(e["type"], ("-->", ""))
            lines.append(f'    {ids[e["source"]]} {style}{"|" + lab + "|" if lab else ""} {ids[e["target"]]}')
    lines.append("    classDef entry fill:#fff3d6,stroke:#e0a100,color:#3a2b00;")
    ent = [ids[p] for p in entries if p in ids]
    if ent:
        lines.append(f"    class {','.join(sorted(ent))} entry;")
    if omitted > 0:
        lines.append(f'    more["+{omitted} more files not shown"]')
    return "\n".join(lines)


def diagram_payload(analysis: Dict) -> Dict:
    graph = analysis["graph"]
    trees = render_tree(graph)

    def slim(t):
        return {"path": t["path"], "kind": t.get("kind"), "via": t.get("via"), "repeat": bool(t.get("repeat")),
                "children": [slim(c) for c in t["children"]]}

    return {
        "mermaid": build_mermaid(analysis),
        "tree": [slim(t) for t in trees],
        "entry_points": graph["entry_points"],
        "stats": graph["stats"],
        "legend": {"==>": "mounts router", "-->": "imports / renders / loads", "-.->": "calls (or inferred HTTP link)"},
    }


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

def _tree_lines(subsystems: List[Dict]) -> List[str]:
    return [f"- `{s['path']}/` — {s['label']} ({_plural(s['files'], 'file')})" for s in subsystems]


def generate_readme(analysis: Dict) -> str:
    ctx, graph, files = analysis["context"], analysis["graph"], analysis["files"]
    L: List[str] = [f"# {ctx['name']}", ""]
    L += ["## Overview", "", ctx["summary"], ""]
    if ctx.get("purpose"):
        L += [f"> {redact_secrets(ctx['purpose'])} — from `{ctx['purpose_source']}`", ""]

    if ctx["technologies"] or ctx["tooling"]:
        L += ["## Technology stack", "", "| Technology | Role | Detected in |", "|---|---|---|"]
        for t in ctx["technologies"]:
            L.append(f"| {t['name']} | {t['category']} | {', '.join(t['sources'])} |")
        for t in ctx["tooling"]:
            L.append(f"| {t['name']} | {t['category']} (dev) | {', '.join(t['sources'])} |")
        L.append("")

    if len(ctx["parts"]) > 1:
        L += ["## Project parts", ""]
        for p in ctx["parts"]:
            L.append(f"- **{p['name']}** (`{p['path'] or '.'}/`): {p['headline']}, {_plural(p['file_count'], 'file')}")
        L.append("")

    if ctx["subsystems"]:
        L += ["## Directory structure", ""] + _tree_lines(ctx["subsystems"]) + [""]

    arch = ctx["architecture"]
    L += ["## Architecture", "", f"{arch['style']}.", ""]
    for chain in arch["startup_chains"]:
        L.append("Startup path: " + " → ".join(f"`{p}`" for p in chain))
    if arch["startup_chains"]:
        L.append("")
    for x in arch["layer_links"] + arch["flows"]:
        L.append(f"- {x}")
    if arch["layer_links"] or arch["flows"]:
        L.append("")

    if ctx["subsystems"]:
        L += ["## Major modules", ""]
        for s in ctx["subsystems"]:
            keys = ", ".join(f"`{posixpath.basename(k)}`" for k in s["key_files"])
            L.append(f"- **{s['label']}** (`{s['path']}/`): {keys}")
        L.append("")

    if ctx["components"]:
        L += ["## Major components", ""]
        for c in ctx["components"][:15]:
            extra = f" — hooks: {', '.join(c['hooks'])}" if c["hooks"] else ""
            L.append(f"- `{c['name']}` (`{c['path']}`){extra}")
        L.append("")

    L += ["## Getting started", ""]
    cmds = ctx["commands"]
    if cmds["install"] or cmds["run"]:
        L.append("Commands below come from files in this repository (source noted in brackets).")
        L.append("")
        L.append("```bash")
        for bucket in ("install", "run", "build", "test", "lint"):
            for c in cmds[bucket]:
                where = f"  # cd {c['part']}" if c.get("part") else ""
                L.append(f"{c['command']}{where}")
        L.append("```")
        L.append("")
        for bucket in ("install", "run", "build", "test", "lint"):
            for c in cmds[bucket]:
                L.append(f"- `{c['command']}` — {c['source']}")
    else:
        L.append("No install or run commands could be detected in this repository.")
    L.append("")

    if ctx["api"]["endpoints"]:
        exprs = sorted({e["prefix_expr"] for e in graph["endpoints"] if e.get("prefix_expr")})
        L += ["## API", ""]
        if exprs:
            L += [f"> Some routers are mounted under a prefix set by {', '.join('`' + x + '`' for x in exprs)}; "
                  "its value is not known statically, so real URLs may include an extra prefix.", ""]
        L += ["| Method | Path | Handler | File |", "|---|---|---|---|"]
        for e in ctx["api"]["endpoints"]:
            L.append(f"| {e['method']} | `{e['path']}` | `{e['handler']}` | `{e['file']}` |")
        L.append("")
    if ctx["data_layer"]["models"]:
        L += ["## Data models", ""]
        for m in ctx["data_layer"]["models"]:
            tbl = f" (table `{m['table']}`)" if m.get("table") else ""
            L.append(f"- `{m['name']}`{tbl} in `{m['file']}`: {', '.join(m['fields']) or 'no fields detected'}")
        L.append("")

    deps = ctx["dependencies"]
    if deps["npm"]["runtime"] or deps["npm"]["dev"] or deps["pip"]:
        L += ["## Dependencies", ""]
        if deps["npm"]["runtime"]:
            L.append("**npm (runtime):** " + ", ".join(f"{d['name']} {d['version']}" for d in deps["npm"]["runtime"]))
        if deps["npm"]["dev"]:
            L.append("**npm (dev):** " + ", ".join(f"{d['name']} {d['version']}" for d in deps["npm"]["dev"]))
        if deps["pip"]:
            L.append("**pip:** " + ", ".join(f"{d['name']}{(' ' + d['version']) if d['version'] else ''}" for d in deps["pip"]))
        L.append("")

    if ctx["config_files"]:
        L += ["## Configuration files", ""] + [f"- `{c['path']}` — {c['purpose']}" for c in ctx["config_files"]] + [""]

    L += ["## Development workflow", ""]
    wf = [f"- {b}: `{c['command']}`" for b in ("build", "test", "lint") for c in cmds[b]]
    L += wf if wf else ["No build, test or lint commands were detected."]
    L.append("")
    if ctx["limitations"]:
        L += ["## About this documentation", "", "Generated by static analysis of the repository. " + " ".join(ctx["limitations"]), ""]
    return redact_secrets("\n".join(L))


# ---------------------------------------------------------------------------
# API documentation
# ---------------------------------------------------------------------------

def generate_api_docs(analysis: Dict) -> str:
    ctx, graph, files = analysis["context"], analysis["graph"], analysis["files"]
    L = [f"# {ctx['name']} — API Documentation", ""]
    eps = graph["endpoints"]
    if eps:
        L += ["## HTTP endpoints", ""]
        exprs = sorted({e["prefix_expr"] for e in eps if e.get("prefix_expr")})
        if exprs:
            L += [f"> Paths exclude prefixes set by {', '.join('`' + x + '`' for x in exprs)} (value not known statically).", ""]
        by_file: Dict[str, List[Dict]] = defaultdict(list)
        for e in eps:
            by_file[e["file"]].append(e)
        consumers: Dict[str, List[str]] = defaultdict(list)
        for c in graph.get("consumers", []):
            consumers[c["endpoint"]].append(c["file"])
        for fpath, items in sorted(by_file.items()):
            L += [f"### `{fpath}`", ""]
            for e in items:
                L.append(f"#### `{e['method']} {e['path']}`")
                fn = next((x for x in files[fpath]["functions"] if x["name"] == e["handler"]), None)
                if e.get("summary"):
                    L.append(e["summary"])
                if fn and fn["params"]:
                    L.append("Parameters: " + ", ".join(f"`{p}`" for p in fn["params"]))
                if e["id"] in consumers:
                    L.append("Called from (inferred): " + ", ".join(f"`{c}`" for c in sorted(set(consumers[e['id']]))))
                L.append("")
    else:
        L += ["No HTTP endpoints were detected.", ""]

    if ctx["data_layer"]["models"]:
        L += ["## Data models", ""]
        for m in ctx["data_layer"]["models"]:
            L.append(f"### `{m['name']}` ({m['kind']})")
            if m.get("table"):
                L.append(f"Table: `{m['table']}`")
            if m["fields"]:
                L.append("Fields: " + ", ".join(f"`{x}`" for x in m["fields"]))
            L.append("")

    mods = []
    for p, f in sorted(files.items()):
        if f["category"] != "code" or f["kind"] in {"api_router", "test", "package_init"}:
            continue
        api_items = []
        for fn in f["functions"]:
            if fn.get("method") or not fn.get("exported", True):
                continue
            sig = ", ".join(fn["params"])
            doc = f" — {fn['doc']}" if fn.get("doc") else ""
            tag = " (component)" if fn.get("is_component") else " (hook)" if fn.get("is_hook") else ""
            api_items.append(f"- `{fn['name']}({sig})`{tag}{doc}")
        for c in f["classes"]:
            doc = f" — {c['doc']}" if c.get("doc") else ""
            api_items.append(f"- class `{c['name']}`{doc}")
        if api_items:
            mods.append((p, KIND_LABELS.get(f["kind"], ("module",))[0], api_items))
    if mods:
        L += ["## Modules", ""]
        for p, label, items in mods[:60]:
            L += [f"### `{p}` — {label}", ""] + items + [""]

    env = sorted({v for f in files.values() for v in f.get("env_vars", [])})
    if env:
        L += ["## Environment variables", "", ", ".join(f"`{v}`" for v in env), ""]
    return redact_secrets("\n".join(L))
