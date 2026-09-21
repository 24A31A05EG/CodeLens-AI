"""
Project-level understanding.

``build_project_context(name, files, graph)`` condenses the per-file facts and
the relationship graph into one structured description of the repository:
what kind of project it is, what it is built with, where it starts, how it is
divided into subsystems, what API it exposes, and how to run it.

Every statement is derived from the repository's own files (manifests, imports,
directory layout, the graph). Where something cannot be determined the field is
left empty or absent - it is never guessed.
"""

import os
import posixpath
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set

from services.analysis.extract_misc import technologies_from_package, technologies_from_requirements
from services.analysis.graph import chain_from_entry, nearest_root, package_roots, render_tree
from services.analysis.knowledge import (
    DIR_CONVENTIONS, KIND_LABELS, NPM_TECH, PY_TECH, config_purpose, package_root_name,
)
from services.analysis.redact import redact_secrets

# Languages counted as "programming languages" in the headline stats.
PROGRAMMING = {"Python", "JavaScript", "TypeScript", "Java", "Go", "Ruby", "Rust", "C++", "C", "C#", "PHP"}
_CATEGORY_ORDER = ["framework", "build", "3d", "animation", "backend", "orm", "database", "ai", "state",
                   "routing", "styling", "validation", "http", "data", "language", "util", "test", "lint"]
_UI_FRAMEWORKS = {"React": 0, "Vue": 1, "Svelte": 2, "Next.js": 3, "Nuxt": 4, "Angular": 5, "SolidJS": 6, "Preact": 7}
_BUNDLERS = {"Vite": 0, "Webpack": 1, "Parcel": 2, "Rollup": 3, "esbuild": 4}


def _title(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").strip().title()


def _module_name(path_in_part: str) -> str:
    return posixpath.splitext(path_in_part)[0].replace("/", ".")


def build_project_context(name: str, files: Dict[str, Dict], graph: Dict) -> Dict:
    paths = set(files)
    roots = package_roots(paths)
    nodes = graph["nodes"]

    # ----- wrapper directory (ZIP usually contains one top-level folder) -----
    tops = {p.split("/")[0] for p in paths if "/" in p}
    root_dir = next(iter(tops)) if len(tops) == 1 and all("/" in p for p in paths) else ""

    # ----- languages -----
    lang_files: Counter = Counter()
    lang_loc: Counter = Counter()
    other_types: Counter = Counter()
    for p, f in files.items():
        if f["language"] in PROGRAMMING:
            lang_files[f["language"]] += 1
            lang_loc[f["language"]] += f.get("line_count", 0)
        else:
            other_types[f["language"]] += 1
    total_loc = sum(lang_loc.values()) or 1
    languages = [
        {"name": n, "files": c, "lines": lang_loc[n], "share": round(lang_loc[n] / total_loc, 3)}
        for n, c in lang_files.most_common()
    ]

    # ----- technologies (manifests first, then import evidence) -----
    tech: Dict[str, Dict] = {}

    def add_tech(label: str, category: str, source: str, scope: str = "runtime", version: Optional[str] = None,
                 package: Optional[str] = None):
        cur = tech.get(label)
        if cur is None:
            tech[label] = {"name": label, "category": category, "scope": scope, "sources": [source],
                           "version": version, "package": package}
        else:
            if source not in cur["sources"]:
                cur["sources"].append(source)
            if scope == "runtime":
                cur["scope"] = "runtime"

    manifests = [(p, f) for p, f in files.items() if f["kind"] == "package_manifest"]
    reqs = [(p, f) for p, f in files.items() if f["kind"] == "dependency_list"]
    pyprojects = [(p, f) for p, f in files.items() if f.get("kind_hint") == "python_project"]
    for p, f in manifests:
        d = f["details"]
        for t in technologies_from_package(d):
            if t["known"]:
                ver = (d.get(("devDependencies" if t["scope"] == "dev" else "dependencies")) or {}).get(t["package"])
                add_tech(t["name"], t["category"], posixpath.basename(p), t["scope"], ver, t["package"])
    for p, f in reqs:
        for t in technologies_from_requirements(f["details"]["packages"]):
            if t["known"]:
                spec = next((x["spec"] for x in f["details"]["packages"] if x["name"] == t["package"]), None)
                add_tech(t["name"], t["category"], posixpath.basename(p), "runtime", spec, t["package"])
    for p, f in pyprojects:
        for dep in f["details"].get("dependencies", []):
            info = PY_TECH.get(dep.lower().replace("_", "-"))
            if info:
                add_tech(info[0], info[1], "pyproject.toml")
    for p, f in files.items():
        for imp in f.get("imports", []):
            ext = imp.get("external")
            if not ext:
                continue
            info = NPM_TECH.get(ext) if f["language"] in ("JavaScript", "TypeScript") else PY_TECH.get(ext.lower())
            if info:
                add_tech(info[0], info[1], "imports in source", "runtime", package=ext)

    def tech_sort(t):
        return (_CATEGORY_ORDER.index(t["category"]) if t["category"] in _CATEGORY_ORDER else 99, t["name"])

    technologies = sorted((t for t in tech.values() if t["scope"] == "runtime"), key=tech_sort)
    tooling = sorted((t for t in tech.values() if t["scope"] != "runtime"), key=tech_sort)

    # ----- parts (frontend / backend / ...) -----
    part_roots: Set[str] = set()
    for p, f in files.items():
        if f["kind"] in {"package_manifest", "dependency_list"} or f.get("kind_hint") == "python_project":
            part_roots.add(posixpath.dirname(p))
    if not part_roots:
        part_roots = {""}
    # a root that only contains another part's root as a subdir is not a part of its own
    def in_part(path: str, root: str) -> bool:
        return root == "" or path.startswith(root + "/")

    # assign each file to the deepest part root
    sorted_roots = sorted(part_roots, key=lambda r: -len(r))
    file_part: Dict[str, str] = {}
    for p in paths:
        file_part[p] = next((r for r in sorted_roots if in_part(p, r)), "")

    parts: List[Dict] = []
    for r in sorted(part_roots):
        members = [p for p in paths if file_part[p] == r]
        if not members:
            continue
        mf = [files[p] for p in members]
        ext_all = {package_root_name(i["source"]).lower() for f in mf for i in f.get("imports", [])
                   if i.get("external")}
        ptech = {}
        for p in members:
            f = files[p]
            if f["kind"] == "package_manifest":
                for t in technologies_from_package(f["details"]):
                    if t["known"]:
                        ptech[t["name"]] = t
            if f["kind"] == "dependency_list":
                for t in technologies_from_requirements(f["details"]["packages"]):
                    if t["known"]:
                        ptech[t["name"]] = t
        for e in ext_all:
            info = NPM_TECH.get(e) or PY_TECH.get(e)
            if info and info[0] not in ptech:
                ptech[info[0]] = {"name": info[0], "category": info[1], "scope": "runtime"}
        names = set(ptech)
        ui = sorted([n for n in names if n in _UI_FRAMEWORKS], key=lambda n: _UI_FRAMEWORKS[n])
        bundler = sorted([n for n in names if n in _BUNDLERS], key=lambda n: _BUNDLERS[n])
        backend_fw = [n for n in names if ptech[n]["category"] == "backend" and n not in {"Uvicorn", "Gunicorn", "Celery"}]
        has_html = any(files[p]["kind"] == "markup" for p in members)
        has_js = any(files[p]["language"] in ("JavaScript", "TypeScript") for p in members)
        has_py = any(files[p]["language"] == "Python" for p in members)
        role = "library"
        if ui or (has_html and has_js):
            role = "frontend"
        elif backend_fw or any("api" in files[p]["tags"] and "web-framework" in files[p]["tags"] for p in members):
            role = "backend"
        elif has_py and not has_js:
            role = "application"
        elif not (has_js or has_py):
            role = "other"
        entry = [e for e in graph["entry_points"] if file_part.get(e["path"]) == r]
        pname = posixpath.basename(r) if r else (root_dir or name)
        if root_dir and r == root_dir:
            pname = name
        headline_parts = []
        if role == "frontend":
            headline_parts = (ui[:1] or []) + bundler[:1]
            headline = " + ".join(headline_parts) + " frontend" if headline_parts else "JavaScript frontend"
        elif role == "backend":
            headline = ", ".join(sorted(backend_fw, key=lambda n: (n != "FastAPI", n))[:2]) + " backend" if backend_fw else "Web backend"
            if has_py and not any(n in backend_fw for n in ("Express", "Koa", "Fastify", "NestJS")):
                headline += " (Python)"
            elif has_js:
                headline += " (Node.js)"
        elif role == "application":
            headline = "Python application"
        else:
            headline = "Code library / module set"
        parts.append({
            "name": pname, "path": r, "role": role, "headline": headline,
            "file_count": len(members), "technologies": sorted(names, key=lambda n: (tech_sort(ptech[n]))),
            "entry_points": [e["path"] for e in entry],
            "languages": sorted({files[p]["language"] for p in members if files[p]["language"] in PROGRAMMING}),
        })

    # ----- headline project type -----
    if len(parts) == 1:
        project_type = parts[0]["headline"]
        if parts[0]["role"] == "frontend" and any(
                "root_render" in files[p].get("entry_signals", []) for p in paths if file_part[p] == parts[0]["path"]):
            project_type += " (single-page application)"
    else:
        named = sorted((p for p in parts if p["role"] in {"frontend", "backend"}),
                       key=lambda p: (p["role"] != "frontend", p["path"]))
        if len(named) >= 2:
            project_type = "Full-stack application: " + ", ".join(
                f"{p['headline']} in `{p['path'] or '.'}/`" for p in named)
        else:
            project_type = "; ".join(p["headline"] for p in parts[:3])

    # ----- main application component (what the entry renders) -----
    main_app = None
    _APP_NAMES = {"app", "application", "root", "main", "layout"}
    for e in graph["entry_points"]:
        f = files.get(e["path"], {})
        if "root_render" not in f.get("entry_signals", []):
            continue
        cands = []
        for edge in graph["edges"]:
            if edge["source"] == e["path"] and "renders" in edge["kinds"]:
                comps = files.get(edge["target"], {}).get("components", [])
                if comps and not all(c.endswith("Provider") for c in comps):  # skip context/theme wrappers
                    cands.append(edge["target"])
        named = [c for c in cands if posixpath.splitext(posixpath.basename(c))[0].lower() in _APP_NAMES]
        # otherwise only trust a candidate that itself composes other components
        composing = [c for c in cands if any(x["source"] == c and "renders" in x["kinds"] for x in graph["edges"])]
        pick = (named or (composing if len(composing) == 1 else []))
        if pick:
            main_app = pick[0]
            break
    if main_app is None:
        # Fall back to an entry that creates the app / mounts the UI, but only if unambiguous.
        app_entries = [e["path"] for e in graph["entry_points"]
                       if files.get(e["path"], {}).get("app_objects")
                       or "root_render" in files.get(e["path"], {}).get("entry_signals", [])]
        if len(app_entries) == 1:
            main_app = app_entries[0]

    # ----- subsystems (directories with meaning) -----
    by_dir: Dict[str, List[str]] = defaultdict(list)
    for p, n in nodes.items():
        if n["category"] in {"code", "style", "test"}:
            by_dir[n["dir"]].append(p)
    subsystems = []
    for d, members in by_dir.items():
        name_l = posixpath.basename(d).lower()
        conv = DIR_CONVENTIONS.get(name_l)
        if not conv and len(members) < 3:
            continue
        if conv and name_l in {"src", "app"} and len(members) < 2:
            continue
        label = conv[0] if conv else f"{_title(posixpath.basename(d) or 'root')} module"
        layer = conv[1] if conv else "module"
        if layer == "api" and sum(1 for m in members if files[m].get("components")) * 2 >= len(members):
            label, layer = "Pages / screens", "ui"  # a `routes/` folder of components is UI routing, not an HTTP API
        key_files = sorted(members, key=lambda m: (-nodes[m]["used_by_count"], m))[:4]
        tags = Counter(t for m in members for t in files[m]["tags"])
        subsystems.append({
            "label": label, "path": d, "layer": layer, "files": len(members),
            "key_files": key_files, "tags": [t for t, _ in tags.most_common(4)],
            "kinds": dict(Counter(nodes[m]["kind"] for m in members)),
        })
    subsystems.sort(key=lambda s: (-s["files"], s["path"]))
    subsystems = subsystems[:14]

    # ----- config files -----
    config_files = []
    for p, f in sorted(files.items()):
        if f["category"] in {"config", "infra"}:
            purpose = config_purpose(posixpath.basename(p)) or KIND_LABELS.get(f["kind"], ("configuration",))[0]
            config_files.append({"path": p, "kind": f["kind"], "purpose": purpose})

    # ----- components -----
    components = []
    for p, f in files.items():
        for comp in f.get("components", []):
            detail = f.get("component_detail", {}).get(comp, {})
            internal_children = []
            for edge in graph["edges"]:
                if edge["source"] == p and "renders" in edge["kinds"]:
                    internal_children.append(edge["target"])
            components.append({
                "name": comp, "path": p, "hooks": detail.get("hooks", []),
                "renders_files": internal_children if len(f["components"]) == 1 else [],
                "used_by_count": nodes[p]["used_by_count"],
            })
    components.sort(key=lambda c: (-c["used_by_count"], c["path"]))

    # ----- API -----
    api = {
        "endpoints": [{k: e[k] for k in ("id", "method", "path", "file", "handler", "summary", "line")} for e in graph["endpoints"]],
        "consumers": graph.get("consumers", []),
    }

    # ----- data / AI layers -----
    models = []
    for p, f in files.items():
        for m in f.get("models", []):
            models.append({"name": m["name"], "kind": m["kind"], "table": m.get("table"), "file": p, "fields": m.get("fields", [])})
    data_layer = {
        "models": models,
        "database_files": [p for p, f in files.items() if f["kind"] in {"database", "data_model"} or "database" in f["tags"] and f["category"] == "code"],
        "sql_files": [p for p, f in files.items() if f["kind"] == "sql"],
    }
    ai_files = [p for p, f in files.items() if "ai" in f["tags"]]
    ai_layer = {"files": ai_files, "libraries": sorted({t["name"] for t in tech.values() if t["category"] == "ai"})}

    # ----- dependencies -----
    deps = {"npm": {"runtime": [], "dev": []}, "pip": []}
    for p, f in manifests:
        d = f["details"]
        deps["npm"]["runtime"] += [{"name": k, "version": v, "manifest": p} for k, v in (d.get("dependencies") or {}).items()]
        deps["npm"]["dev"] += [{"name": k, "version": v, "manifest": p} for k, v in (d.get("devDependencies") or {}).items()]
    for p, f in reqs:
        deps["pip"] += [{"name": x["name"], "version": x["spec"], "manifest": p} for x in f["details"]["packages"]]
    for p, f in pyprojects:
        deps["pip"] += [{"name": x, "version": None, "manifest": p} for x in f["details"].get("dependencies", [])]

    # ----- commands (from real files) -----
    commands: Dict[str, List[Dict]] = {"install": [], "run": [], "build": [], "test": [], "lint": []}
    for p, f in manifests:
        d = f["details"]
        pdir = posixpath.dirname(p)
        where = f" (in `{pdir}/`)" if pdir else ""
        commands["install"].append({"command": "npm install", "source": f"{posixpath.basename(p)} present{where}", "part": pdir})
        for sname, cmd in (d.get("scripts") or {}).items():
            bucket = ("run" if sname in {"dev", "start", "serve", "preview"} else
                      "build" if sname.startswith("build") else
                      "test" if sname.startswith("test") else
                      "lint" if sname.startswith(("lint", "format")) else None)
            if bucket:
                commands[bucket].append({"command": f"npm run {sname}", "detail": cmd, "source": f"scripts.{sname} in {p}", "part": pdir})
    for p, f in reqs:
        pdir = posixpath.dirname(p)
        commands["install"].append({"command": f"pip install -r {posixpath.basename(p)}", "source": f"{p} present", "part": pdir})
    for p, f in files.items():
        for app in f.get("app_objects", []):
            part_root = file_part[p]
            rel = p[len(part_root) + 1:] if part_root and p.startswith(part_root + "/") else p
            if f["language"] == "Python" and app["framework"] in {"FastAPI", "Starlette", "Quart"}:
                commands["run"].append({"command": f"uvicorn {_module_name(rel)}:{app['name']} --reload",
                                        "source": f"{app['framework']} app object `{app['name']}` in {p}", "part": part_root})
        if f.get("kind") == "container":
            cmd = f["details"].get("cmd")
            if cmd:
                commands["run"].append({"command": f"(container) {cmd}", "source": f"CMD in {p}", "part": posixpath.dirname(p)})
        if f["kind"] == "test" and f["language"] == "Python" and not any(c["command"] == "pytest" for c in commands["test"]):
            commands["test"].append({"command": "pytest", "source": "Python test files present", "part": ""})
    for p, f in files.items():
        if f["kind"] == "documentation":
            for c in f["details"].get("commands", [])[:8]:
                if not any(x["command"] == c for bucket in commands.values() for x in bucket):
                    bucket = ("install" if any(w in c for w in ("install", "pip", "npm i", "yarn add")) else
                              "test" if "test" in c else "build" if "build" in c else "run")
                    commands[bucket].append({"command": c, "source": f"documented in {p}", "part": posixpath.dirname(p)})

    # ----- documentation / purpose -----
    readmes = sorted((p for p, f in files.items() if f["kind"] == "documentation" and posixpath.basename(p).lower().startswith("readme")),
                     key=lambda p: (p.count("/"), p))
    purpose, purpose_source = None, None
    if readmes:
        hint = files[readmes[0]].get("summary_hint")
        if hint:
            purpose, purpose_source = hint, readmes[0]
    if not purpose:
        for p, f in manifests:
            desc = f["details"].get("description")
            if desc:
                purpose, purpose_source = desc, p
                break
    documentation = {
        "readmes": readmes,
        "doc_files": [p for p, f in files.items() if f["kind"] == "documentation"],
        "sections": sorted({s for r in readmes for s in files[r]["details"].get("sections", [])}),
    }

    # ----- architecture -----
    layers_present = defaultdict(list)
    for s in subsystems:
        layers_present[s["layer"]].append(s)
    _structural_layers = {"source", "assets", "frontend", "backend"}
    layer_edges: Counter = Counter()
    for e in graph["edges"]:
        if e["target"].startswith("endpoint:"):
            continue
        a, b = nodes[e["source"]]["layer"], nodes[e["target"]]["layer"]
        if a and b and a != b and not ({a, b} & _structural_layers):
            layer_edges[(a, b)] += 1
    layer_names = {"ui": "UI components", "3d": "3D visualization", "api": "API routes", "service": "service layer",
                   "data": "data layer", "logic": "hooks/state", "util": "utilities", "ai": "AI layer",
                   "style": "styling", "config": "configuration", "test": "tests", "script": "scripts",
                   "docs": "documentation", "module": "other modules"}

    style_bits: List[str] = []
    for part in parts:
        loc = f" in `{part['path']}/`" if part["path"] and len(parts) > 1 else ""
        if part["role"] == "frontend":
            fw = next((t for t in part["technologies"] if t in _UI_FRAMEWORKS), None)
            comp_count = sum(len(files[p].get("components", [])) for p in paths if file_part[p] == part["path"])
            base = f"Component-based {fw} frontend" if fw and comp_count else f"{fw or 'JavaScript'} frontend"
            style_bits.append(base + loc + (f" ({comp_count} component{'s' if comp_count != 1 else ''})" if comp_count else ""))
        elif part["role"] == "backend":
            style_bits.append(part["headline"] + loc)
    extras = []
    for s in subsystems:
        if s["layer"] == "3d":
            extras.append(f"a dedicated {s['label']} layer (`{s['path']}/`)")
    architecture_style = "; ".join(style_bits) if style_bits else project_type
    if extras:
        architecture_style += ", with " + " and ".join(extras)
    flows = []
    layer_flow = [f"{layer_names.get(a, a)} → {layer_names.get(b, b)} ({n} link{'s' if n != 1 else ''})"
                  for (a, b), n in layer_edges.most_common(6)]
    consumed = graph["stats"].get("consumed_endpoints", 0)
    if consumed:
        consumer_files = sorted({c["file"] for c in graph.get("consumers", [])})
        flows.append(f"{len(consumer_files)} file(s) call {consumed} backend endpoint(s) (matched by URL, inferred)")

    # startup spine(s): follow the widest structural path from each entry
    trees = render_tree(graph)
    spines = []
    for t in trees:
        spine, cur = [t["path"]], t
        while cur["children"]:
            code_kids = [c for c in cur["children"] if nodes.get(c["path"], {}).get("category") == "code" and not c.get("repeat")]
            if not code_kids:
                break
            cur = max(code_kids, key=_subtree_size)
            spine.append(cur["path"])
        html_parents = [e["source"] for e in graph["edges"] if e["target"] == t["path"] and "loads" in e["kinds"]]
        if html_parents:
            spine.insert(0, html_parents[0])
        if len(spine) > 1:
            spines.append(spine)

    # ----- limitations -----
    limitations = []
    low_files = sorted(p for p, f in files.items() if f.get("confidence") == "low" and f["language"] in PROGRAMMING)
    if low_files:
        eg = ", ".join(f"`{posixpath.basename(p)}`" for p in low_files[:3])
        limitations.append(
            f"{len(low_files)} source file(s) (e.g. {eg}) could not be fully parsed and use lightweight pattern matching; "
            "their relationships may be incomplete.")
    if any(f["language"] in ("JavaScript", "TypeScript") for f in files.values()):
        limitations.append("JavaScript/TypeScript analysis is pattern-based (no full parser); dynamic imports and runtime-generated components may be missed.")
    if graph.get("consumers"):
        limitations.append("Frontend-to-backend links are inferred by matching request URLs to route paths.")

    summary = _compose_summary(name, project_type, languages, technologies, graph, files, main_app, subsystems, purpose)

    return {
        "name": name, "root_dir": root_dir, "project_type": project_type, "summary": summary,
        "purpose": purpose, "purpose_source": purpose_source,
        "languages": languages, "other_file_types": dict(other_types),
        "parts": parts, "technologies": technologies, "tooling": tooling,
        "entry_points": graph["entry_points"], "main_application": main_app,
        "subsystems": subsystems, "config_files": config_files,
        "components": components[:40], "api": api, "data_layer": data_layer, "ai_layer": ai_layer,
        "dependencies": deps, "commands": commands, "documentation": documentation,
        "architecture": {"style": architecture_style, "layer_links": layer_flow, "flows": flows, "startup_chains": spines[:4]},
        "graph_stats": graph["stats"], "limitations": limitations,
        "file_count": len(files),
        "kind_counts": dict(Counter(f["kind"] for f in files.values())),
    }


def _subtree_size(node: Dict) -> int:
    return 1 + sum(_subtree_size(c) for c in node["children"] if not c.get("repeat"))


_GENERIC_LEAD = ("Full-stack", "Code library", "Web backend")


def _compose_summary(name, project_type, languages, technologies, graph, files, main_app, subsystems, purpose) -> str:
    lang_txt = ", ".join(l["name"] for l in languages[:3]) or "no programming languages detected"
    kind = project_type[0].lower() + project_type[1:] if project_type.startswith(_GENERIC_LEAD) else project_type
    article = "an" if kind[:1].lower() in "aeiou" else "a"
    parts = [f"{name} is {article} {kind}."]
    parts.append(f"It contains {len(files)} analysed files ({lang_txt}).")
    key_tech = [t["name"] for t in technologies if t["category"] in {"framework", "3d", "animation", "backend", "orm", "ai", "state", "routing"}][:6]
    if key_tech:
        parts.append(f"Key technologies: {', '.join(key_tech)}.")
    eps = graph["entry_points"]
    if eps:
        parts.append("Entry point" + ("s" if len(eps) > 1 else "") + ": " + ", ".join(f"`{e['path']}`" for e in eps[:3]) + ".")
    if main_app and (not eps or main_app != eps[0]["path"]):
        parts.append(f"Main application module: `{main_app}`.")
    named = [s for s in subsystems if s["layer"] not in {"source", "assets", "config"}][:4]
    if named:
        parts.append("Main subsystems: " + "; ".join(f"{s['label']} (`{s['path']}/`)" for s in named) + ".")
    return " ".join(parts)
