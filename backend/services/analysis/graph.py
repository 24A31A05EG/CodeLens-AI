"""
Cross-file relationship analysis.

Input:  ``files`` - {path: FileFacts} for every analysed file in ONE project.
Output: a JSON-serialisable graph:

    {
      "nodes":     {path: {kind, category, label, dir, layer, entry, depth, ...}},
      "edges":     [{source, target, type, kinds, evidence, confidence, symbols}],
      "endpoints": [{id, method, path, file, handler, ...}],
      "entry_points": [{path, reason, confidence}],
      "external":  {path: [package names]},
      "stats":     {...},
    }

Rules that keep the graph honest:

* An edge exists only if the source code shows it (an import statement, a JSX
  element bound to an import, a call of an imported name, a script tag, an
  ``include_router`` call ...). Those edges have ``confidence: "extracted"``.
* API-consumption edges (``consumes`` / ``calls_api``) are matched by URL path
  and are always marked ``confidence: "inferred"``.
* Only files inside this one project are ever considered - resolution works on
  the given ``files`` mapping and nothing else.
"""

import posixpath
import re
import sys
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set, Tuple

from services.analysis.knowledge import DIR_CONVENTIONS, package_root_name

JS_EXTS = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json", ".css", ".scss"]
STDLIB = set(getattr(sys, "stdlib_module_names", set())) | {"__future__"}

# primary edge type priority (lower index wins)
_TYPE_ORDER = ["mounts", "renders", "calls", "loads", "styles", "imports"]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _dirname(path: str) -> str:
    return posixpath.dirname(path)


def _join(*parts: str) -> str:
    return posixpath.normpath(posixpath.join(*[p for p in parts if p != ""])) if any(parts) else ""


def package_roots(paths: Set[str]) -> List[str]:
    """Directories that look like the root of a JS/Python package (sorted deepest first)."""
    roots = {""}
    markers = {"package.json", "pyproject.toml", "setup.py", "requirements.txt", "index.html", "manage.py"}
    for p in paths:
        if posixpath.basename(p).lower() in markers:
            roots.add(_dirname(p))
    return sorted(roots, key=lambda r: (-r.count("/") if r else 1, r))


def nearest_root(path: str, roots: List[str]) -> str:
    d = _dirname(path)
    best = ""
    for r in roots:
        if r == "" or d == r or d.startswith(r + "/"):
            if len(r) >= len(best):
                best = r
    return best


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------

def _probe_js(candidate: str, paths: Set[str]) -> Optional[str]:
    candidate = posixpath.normpath(candidate)
    if candidate in paths:
        return candidate
    for ext in JS_EXTS:
        if candidate + ext in paths:
            return candidate + ext
    for ext in JS_EXTS:
        idx = f"{candidate}/index{ext}"
        if idx in paths:
            return idx
    # TypeScript ESM style: './x.js' actually points at './x.ts'
    m = re.match(r"^(.*)\.(js|jsx|mjs|cjs)$", candidate)
    if m:
        for ext in (".ts", ".tsx"):
            if m.group(1) + ext in paths:
                return m.group(1) + ext
    return None


def resolve_js_spec(importer: str, spec: str, paths: Set[str], roots: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """-> (resolved internal path | None, external package | None)."""
    spec = spec.split("?", 1)[0].split("#", 1)[0]
    if spec.startswith("."):
        return _probe_js(_join(_dirname(importer), spec), paths), None
    root = nearest_root(importer, roots)
    if spec.startswith("/"):
        for base in (root, ""):
            hit = _probe_js(_join(base, spec.lstrip("/")), paths)
            if hit:
                return hit, None
        return None, None
    if spec.startswith(("@/", "~/", "#/")):
        rest = spec[2:]
        for base in (_join(root, "src"), root, "src", ""):
            hit = _probe_js(_join(base, rest), paths)
            if hit:
                return hit, None
        return None, None
    if spec.startswith(("node:", "data:", "http:", "https:")):
        return None, spec.split(":", 1)[0]
    return None, package_root_name(spec)


def resolve_py_import(importer: str, imp: Dict, paths: Set[str]) -> Tuple[List[str], Optional[str], bool]:
    """-> (resolved internal paths, external top-level package, is_stdlib)."""
    module = imp.get("source") or ""
    level = imp.get("level", 0)
    names = imp.get("imported") or []
    parts = [p for p in module.split(".") if p]

    def module_files(base_dir: str, mparts: List[str]) -> Optional[str]:
        mp = _join(base_dir, *mparts) if mparts else base_dir
        if mp == "" and not mparts:
            cand = "__init__.py"
            return cand if cand in paths else None
        for cand in (f"{mp}.py", f"{mp}/__init__.py"):
            if cand in paths:
                return cand
        return None

    def submodules(base_dir: str, mparts: List[str]) -> List[str]:
        out = []
        for n in names:
            if n == "*":
                continue
            mp = _join(base_dir, *mparts, n)
            for cand in (f"{mp}.py", f"{mp}/__init__.py"):
                if cand in paths:
                    out.append(cand)
                    break
        return out

    if level > 0:
        base = _dirname(importer)
        for _ in range(level - 1):
            base = _dirname(base)
        subs = submodules(base, parts)
        main = module_files(base, parts)
        targets = subs or ([main] if main else [])
        if subs and main and len(subs) < len(names):
            targets.append(main)
        return [t for t in targets if t != importer], None, False

    # absolute import: try nearest ancestor directories first
    ancestors = []
    d = _dirname(importer)
    while True:
        ancestors.append(d)
        if d == "":
            break
        d = _dirname(d)
    for base in ancestors:
        main = module_files(base, parts) if parts else None
        subs = submodules(base, parts) if (parts or names) and (main or not parts) else []
        if main or subs:
            targets = subs[:] if subs else ([main] if main else [])
            if subs and main and len(subs) < len([n for n in names if n != "*"]):
                targets.append(main)
            return [t for t in targets if t != importer], None, False
    top = parts[0] if parts else ""
    if top in STDLIB:
        return [], None, True
    return [], top or None, False


# ---------------------------------------------------------------------------
# API path matching
# ---------------------------------------------------------------------------

def normalize_route_path(path: str) -> str:
    path = re.sub(r"\{[^}/]*\}|:[A-Za-z_]\w*", "{}", path or "")
    path = re.sub(r"/+", "/", "/" + path.strip("/"))
    return path.rstrip("/") or "/"


def api_call_path(target: str) -> Optional[str]:
    """Extract a normalised URL path from the first argument of fetch/axios."""
    t = (target or "").strip()
    literals = re.findall(r"""(`[^`]*`|'[^']*'|"[^"]*")""", t)
    if not literals:
        return None
    for lit in literals:
        body = lit[1:-1]
        body = re.sub(r"\$\{[^}]*\}", "{}", body)
        if body.startswith("{}"):
            body = body[2:]
        m = re.match(r"^https?://[^/]+(/.*)?$", body)
        if m:
            body = m.group(1) or "/"
        if body.startswith("/"):
            body = body.split("?", 1)[0]
            return normalize_route_path(body)
    return None


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _layer_for(path: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Nearest conventional directory -> (dir path, subsystem label, layer key)."""
    parts = path.split("/")[:-1]
    for i in range(len(parts), 0, -1):
        name = parts[i - 1].lower()
        if name in DIR_CONVENTIONS and name not in {"src", "app"}:
            label, layer = DIR_CONVENTIONS[name]
            return "/".join(parts[:i]), label, layer
    return None, None, None


def build_graph(files: Dict[str, Dict]) -> Dict:
    paths = set(files)
    roots = package_roots(paths)
    edge_map: Dict[Tuple[str, str], Dict] = {}
    external: Dict[str, Set[str]] = defaultdict(set)
    spec_cache: Dict[Tuple[str, str], Tuple[Optional[str], Optional[str]]] = {}
    binding_targets: Dict[str, Dict[str, str]] = {}

    def add_edge(src: str, dst: str, kind: str, evidence: str, symbol: Optional[str] = None,
                 confidence: str = "extracted") -> None:
        if not dst or src == dst:
            return
        e = edge_map.setdefault((src, dst), {
            "source": src, "target": dst, "kinds": [], "evidence": [], "symbols": [], "_conf": set(),
        })
        e["_conf"].add(confidence)
        if kind not in e["kinds"]:
            e["kinds"].append(kind)
        if evidence and evidence not in e["evidence"] and len(e["evidence"]) < 4:
            e["evidence"].append(evidence)
        if symbol and symbol not in e["symbols"] and len(e["symbols"]) < 12:
            e["symbols"].append(symbol)

    def js_resolve(importer: str, spec: str):
        key = (importer, spec)
        if key not in spec_cache:
            spec_cache[key] = resolve_js_spec(importer, spec, paths, roots)
        return spec_cache[key]

    # ---- imports / renders / calls / html loads ----
    for path, f in files.items():
        lang = f["language"]
        if lang == "Python":
            for idx, imp in enumerate(f["imports"]):
                targets, ext, is_std = resolve_py_import(path, imp, paths)
                imp["resolved"] = targets
                imp["external"] = ext
                imp["stdlib"] = is_std
                if ext:
                    external[path].add(ext)
                stmt = (f"from {'.' * imp.get('level', 0)}{imp['source']} import {', '.join(imp.get('imported') or [])}"
                        if imp.get("kind") == "from" else f"import {imp['source']}")
                for t in targets:
                    add_edge(path, t, "imports", f"line {imp['line']}: {stmt}"[:140])
            # binding -> resolved file (for calls / include_router)
            binding_target: Dict[str, str] = {}
            for name, b in f["bindings"].items():
                probe = {"source": b["source"], "level": b.get("level", 0),
                         "imported": [b["imported"]] if b["imported"] != "*" else []}
                t, _, _ = resolve_py_import(path, probe, paths)
                if t:
                    binding_target[name] = t[0]
            # React fallback: if an imported symbol resolves to a file that
            # static analysis identified as a React component, preserve the
            # source-based component relationship even when JSX syntax is
            # dynamic and the lightweight JSX scanner did not bind it.
            for local_name, target_path in binding_target.items():
                target_facts = files.get(target_path) or {}
                if (local_name[:1].isupper()
                        and target_facts.get("components")
                        and not target_path.lower().endswith((".css", ".scss", ".json"))):
                    already = any(
                        e["source"] == path and e["target"] == target_path and "renders" in e["kinds"]
                        for e in edge_map.values()
                    )
                    if not already:
                        add_edge(
                            path, target_path, "renders",
                            f"imported React component `{local_name}` from `{target_path}`",
                            local_name,
                        )
            for call in f["calls"]:
                root = call["name"].split(".")[0]
                t = binding_target.get(root)
                if t:
                    add_edge(path, t, "calls", f"line {call['line']}: calls {call['name']}()", call["name"])
            for inc in f.get("include_routers", []):
                root = inc["target"].split(".")[0]
                t = binding_target.get(root)
                if t:
                    add_edge(path, t, "mounts", f"line {inc['line']}: include_router({inc['target']})", inc["target"])
            binding_targets[path] = binding_target
        elif lang in ("JavaScript", "TypeScript"):
            for imp in f["imports"]:
                target, ext = js_resolve(path, imp["source"])
                imp["resolved"] = [target] if target else []
                imp["external"] = ext
                imp["stdlib"] = False
                if ext:
                    external[path].add(ext)
                if target:
                    is_style = target.lower().endswith((".css", ".scss"))
                    add_edge(path, target, "styles" if is_style else "imports",
                             f"line {imp['line']}: import '{imp['source']}'")
            binding_target = {}
            for name, b in f["bindings"].items():
                t, _ = js_resolve(path, b["source"])
                if t:
                    binding_target[name] = t
            for r in f["renders"]:
                t = binding_target.get(r["base"])
                if t and not t.lower().endswith((".css", ".scss")):
                    add_edge(path, t, "renders", f"line {r['line']}: <{r['name']}> rendered", r["name"])
            for call in f["calls"]:
                root = call["name"].split(".")[0]
                t = binding_target.get(root)
                if t and not t.lower().endswith((".css", ".scss", ".json")) and not root[:1].isupper():
                    add_edge(path, t, "calls", f"line {call['line']}: calls {call['name']}()", call["name"])
            binding_targets[path] = binding_target
        elif f.get("kind") == "markup":
            root = nearest_root(path, roots)
            for s in f["details"].get("scripts", []):
                t, _ = resolve_js_spec(path, s["src"] if s["src"].startswith(("/", ".")) else "./" + s["src"], paths, roots)
                if t:
                    add_edge(path, t, "loads", f"<script src=\"{s['src']}\">")
            for href in f["details"].get("stylesheets", []):
                t, _ = resolve_js_spec(path, href if href.startswith(("/", ".")) else "./" + href, paths, roots)
                if t:
                    add_edge(path, t, "styles", f"<link href=\"{href}\">")
        elif f.get("kind") == "stylesheet":
            for imp in f["details"].get("imports", []):
                t, _ = resolve_js_spec(path, imp if imp.startswith((".", "/")) else "./" + imp, paths, roots)
                if t:
                    add_edge(path, t, "styles", f"@import '{imp}'")
        else:
            for imp in f.get("imports", []):
                imp.setdefault("resolved", [])
                imp.setdefault("external", package_root_name(imp["source"]) if imp.get("source") else None)
                imp.setdefault("stdlib", False)

    # ---- endpoints (provided) ----
    endpoints: List[Dict] = []
    for path, f in files.items():
        for r in f.get("routes", []):
            prefix_router = f.get("router_prefixes", {}).get(r.get("object") or "", "")
            include_prefix, mounted_by, prefix_expr = "", [], None
            for g_path, g in files.items():
                for inc in g.get("include_routers", []):
                    root, _, attr = inc["target"].partition(".")
                    tgt = binding_targets.get(g_path, {}).get(root)
                    same_file_router = (g_path == path and inc["target"] == (r.get("object") or ""))
                    if (tgt == path and (not attr or attr == (r.get("object") or ""))) or same_file_router:
                        include_prefix = inc["prefix"] or ""
                        prefix_expr = inc.get("prefix_expr")
                        mounted_by.append(g_path)
                        break
            raw = f"{include_prefix}/{prefix_router}/{r['path']}" if r["framework"] != "express" else r["path"]
            full = re.sub(r"/+", "/", "/" + raw.strip("/")).rstrip("/") or "/"   # readable, keeps {param} names
            ep = {
                "id": f"{r['method']} {full}", "method": r["method"], "path": full, "match": normalize_route_path(full),
                "declared_path": r["path"],
                "file": path, "handler": r.get("handler"), "line": r.get("line"),
                "summary": r.get("summary"), "framework": r.get("framework"), "mounted_by": mounted_by,
                "prefix_expr": prefix_expr,
            }
            endpoints.append(ep)
            add_edge(path, f"endpoint:{ep['id']}", "exposes", f"line {r.get('line')}: {r['method']} {full}")

    # ---- API consumption (inferred by URL match) ----
    seg_index = [(ep, ep["match"].strip("/").split("/")) for ep in endpoints]
    consumers: List[Dict] = []
    for path, f in files.items():
        for call in f.get("api_calls", []):
            cpath = api_call_path(call["target"])
            if not cpath:
                continue
            csegs = cpath.strip("/").split("/")
            for ep, esegs in seg_index:
                if len(esegs) != len(csegs) or (ep["file"] == path):
                    continue
                if all(a == b or a == "{}" or b == "{}" for a, b in zip(esegs, csegs)):
                    if call["method"] and ep["method"] not in {call["method"], "WEBSOCKET"} and call["method"] != "GET":
                        continue
                    if call["method"] == "GET" and ep["method"] != "GET":
                        continue
                    ev = f"line {call['line']}: {call['via']}({cpath}) matches {ep['method']} {ep['path']}"
                    add_edge(path, f"endpoint:{ep['id']}", "consumes", ev, confidence="inferred")
                    add_edge(path, ep["file"], "calls_api", ev, ep["id"], confidence="inferred")
                    consumers.append({"file": path, "endpoint": ep["id"], "line": call["line"]})

    # ---- finalize edges ----
    edges = []
    for e in edge_map.values():
        e["confidence"] = "extracted" if "extracted" in e.pop("_conf") else "inferred"
        e["type"] = next((t for t in _TYPE_ORDER + ["exposes", "consumes", "calls_api"] if t in e["kinds"]), "imports")
        edges.append(e)
    edges.sort(key=lambda e: (e["source"], e["target"]))

    file_edges = [e for e in edges if e["target"] in paths]
    incoming: Dict[str, List[str]] = defaultdict(list)
    outgoing: Dict[str, List[str]] = defaultdict(list)
    for e in file_edges:
        incoming[e["target"]].append(e["source"])
        outgoing[e["source"]].append(e["target"])

    # ---- entry points ----
    entries: Dict[str, Dict] = {}

    def add_entry(p: str, reason: str, confidence: str = "extracted"):
        if p in paths and p not in entries:
            entries[p] = {"path": p, "reason": reason, "confidence": confidence}

    for e in file_edges:
        if "loads" in e["kinds"] and files[e["source"]].get("kind") == "markup":
            add_entry(e["target"], f"loaded by {posixpath.basename(e['source'])} as a module script")
    for path, f in files.items():
        if f.get("kind") == "test":
            continue  # test modules with a __main__ guard are not application entry points
        sig = f.get("entry_signals", [])
        if "root_render" in sig:
            add_entry(path, "mounts the React/Vue root")
        if "http_listen" in sig:
            add_entry(path, "starts an HTTP server")
        for s in sig:
            if s.endswith("_app") and s != "root_render":
                add_entry(path, "creates the web application object")
        if "dunder_main" in sig:
            add_entry(path, "has a `__main__` guard (runnable script)")
        if f.get("kind") == "package_manifest":
            d = f["details"]
            main = d.get("main")
            if main:
                t, _ = resolve_js_spec(path, "./" + main.lstrip("./"), paths, roots)
                if t:
                    add_entry(t, f"declared as `main` in {posixpath.basename(path)}")
            for sname, cmd in (d.get("scripts") or {}).items():
                m = re.search(r"\b(?:node|nodemon|ts-node|tsx|bun)\s+([\w./\-]+\.[cm]?[jt]sx?)", cmd)
                if m:
                    t, _ = resolve_js_spec(path, "./" + m.group(1).lstrip("./"), paths, roots)
                    if t:
                        add_entry(t, f"run by the `{sname}` npm script")
    if not entries:
        for path, f in files.items():
            base = posixpath.basename(path).lower()
            stem = base.rsplit(".", 1)[0]
            if f["category"] == "code" and stem in {"main", "index", "app", "server", "manage", "wsgi", "asgi", "cli"} \
                    and not incoming.get(path):
                add_entry(path, "conventional entry-point file name (inferred)", "inferred")

    # ---- depth / reached-from via BFS over structural edges ----
    depth: Dict[str, int] = {}
    parent: Dict[str, str] = {}
    dq = deque()
    for p in entries:
        depth[p] = 0
        dq.append(p)
    struct_types = {"mounts", "renders", "calls", "loads", "imports"}
    adj: Dict[str, List[str]] = defaultdict(list)
    for e in file_edges:
        if set(e["kinds"]) & struct_types:
            adj[e["source"]].append(e["target"])
    while dq:
        cur = dq.popleft()
        for nxt in adj.get(cur, []):
            if nxt not in depth:
                depth[nxt] = depth[cur] + 1
                parent[nxt] = cur
                dq.append(nxt)

    # ---- nodes ----
    nodes: Dict[str, Dict] = {}
    for path, f in files.items():
        d, label, layer = _layer_for(path)
        if layer == "api" and f.get("components"):
            label, layer = "Pages / screens", "ui"
        nodes[path] = {
            "path": path, "kind": f["kind"], "category": f["category"], "language": f["language"],
            "dir": _dirname(path), "subsystem": label, "layer": layer,
            "entry": path in entries, "depth": depth.get(path),
            "reached_from": parent.get(path),
            "imports_count": len(outgoing.get(path, [])), "used_by_count": len(incoming.get(path, [])),
        }

    graph = {
        "nodes": nodes,
        "edges": edges,
        "endpoints": endpoints,
        "consumers": consumers,
        "entry_points": sorted(entries.values(), key=lambda e: e["path"]),
        "external": {p: sorted(v) for p, v in external.items()},
        "package_roots": [r for r in roots],
        "stats": {
            "files": len(nodes), "edges": len(file_edges),
            "edge_types": _count_types(file_edges),
            "endpoints": len(endpoints), "consumed_endpoints": len({c["endpoint"] for c in consumers}),
            "entry_points": len(entries),
        },
    }
    return graph


def _count_types(edges: List[Dict]) -> Dict[str, int]:
    out: Dict[str, int] = defaultdict(int)
    for e in edges:
        out[e["type"]] += 1
    return dict(out)


# ---------------------------------------------------------------------------
# Graph queries used by explainer / retrieval / diagram
# ---------------------------------------------------------------------------

def outgoing_edges(graph: Dict, path: str, include_endpoints: bool = False) -> List[Dict]:
    return [e for e in graph["edges"]
            if e["source"] == path and (include_endpoints or not e["target"].startswith("endpoint:"))]


def incoming_edges(graph: Dict, path: str) -> List[Dict]:
    return [e for e in graph["edges"] if e["target"] == path]


def chain_from_entry(graph: Dict, path: str) -> List[str]:
    """Shortest structural chain entry -> ... -> path (empty if unreachable)."""
    nodes = graph["nodes"]
    chain, cur, guard = [path], path, 0
    while cur in nodes and nodes[cur].get("reached_from") and guard < 50:
        cur = nodes[cur]["reached_from"]
        chain.append(cur)
        guard += 1
    chain.reverse()
    if not nodes.get(chain[0], {}).get("entry"):
        return []
    return chain


def render_tree(graph: Dict, max_depth: int = 8, max_children: int = 30) -> List[Dict]:
    """Hierarchical view from each entry point along structural edges.

    Each node appears once in full; repeats are marked ``repeat: True``.
    """
    edges_by_src: Dict[str, List[Dict]] = defaultdict(list)
    for e in graph["edges"]:
        if e["target"].startswith("endpoint:"):
            continue
        edges_by_src[e["source"]].append(e)
    order = {t: i for i, t in enumerate(_TYPE_ORDER)}
    seen: Set[str] = set()

    def visit(path: str, via: Optional[str], depth: int, stack: Tuple[str, ...]) -> Dict:
        node = graph["nodes"].get(path, {})
        item = {"path": path, "kind": node.get("kind"), "via": via, "children": []}
        if path in seen:
            item["repeat"] = True
            return item
        seen.add(path)
        if depth >= max_depth:
            return item
        kids = [e for e in edges_by_src.get(path, []) if e["target"] not in stack and e["type"] != "calls_api"]
        kids.sort(key=lambda e: (order.get(e["type"], 9), e["target"]))
        for e in kids[:max_children]:
            item["children"].append(visit(e["target"], e["type"], depth + 1, stack + (path,)))
        return item

    trees = []
    for ep in graph["entry_points"]:
        trees.append(visit(ep["path"], None, 0, ()))
    return trees
