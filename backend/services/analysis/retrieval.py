"""
Ask-Codebase retrieval and answer composition.

Ranking combines, for the ONE project passed in:
  * path / file-name token matches,
  * symbol names (functions, classes, components, hooks, routes, models),
  * capability tags and subsystem labels via a small concept-synonym table,
  * lexical relevance of the stored code chunks (BM25-style),
  * graph neighbourhood: files closely connected to strong hits are boosted.

Answers are composed from the project graph and facts according to the detected
question intent (startup flow, locate files, dependencies, stack, API, overview,
or a concept explanation). No language model is involved, and no text outside
this project is ever consulted.
"""

import math
import os
import posixpath
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

from services.analysis.explainer import _bt, _lst, _plural, _behaviour, file_relations
from services.analysis.knowledge import KIND_LABELS, humanize_identifier, tokenize

_STOP = set("""a an the is are was were be been do does did how what which where when why who whom this that these those
of in on at to for from by with and or not it its as into about can could should would will i you we they my our your
me us them there here file files code project application app work works working use used using make made explain tell
show give""".split())

# concept word -> tokens that indicate the concept in paths / tags / imports / symbols
_SYNONYMS = {
    "3d": {"3d", "three", "r3f", "scene", "mesh", "canvas", "webgl", "shader", "shaders", "fiber", "drei", "geometry", "material"},
    "visualization": {"3d", "three", "scene", "canvas", "chart", "chart", "render"},
    "animation": {"animation", "animate", "gsap", "motion", "frame", "useframe", "keyframes", "transition"},
    "style": {"css", "style", "styles", "styling", "scss", "theme"},
    "styling": {"css", "style", "styles", "scss", "theme"},
    "database": {"database", "db", "sql", "sqlalchemy", "model", "models", "orm", "session", "engine", "table"},
    "storage": {"database", "db", "model", "models", "storage"},
    "api": {"api", "route", "routes", "router", "endpoint", "endpoints", "fastapi", "express", "fetch"},
    "endpoint": {"api", "route", "router", "endpoint"},
    "auth": {"auth", "login", "logout", "token", "session", "user", "password", "access", "security", "jwt", "oauth", "permission", "credential"},
    "test": {"test", "tests", "pytest", "spec", "jest", "vitest"},
    "config": {"config", "configuration", "settings", "env", "vite", "eslint", "tsconfig"},
    "build": {"build", "vite", "webpack", "bundle", "bundler", "package"},
    "state": {"state", "store", "context", "redux", "usestate", "reducer"},
    "ui": {"component", "components", "ui", "interface", "page", "pages", "view"},
    "ai": {"ai", "model", "llm", "openai", "watsonx", "embedding", "embeddings", "prompt"},
    "upload": {"upload", "file", "zip", "import"},
}

_INTENTS = [
    ("startup", re.compile(r"\b(start|starts|startup|boot|bootstrap|launch|launches|begin|begins|initiali[sz]e[sd]?|entry|entrypoint|run)\b.*\b(app|application|project|program|server|site|frontend|backend)\b|\bhow does (the )?(app|application|project|program|server) (start|run|begin|boot)|\bentry ?points?\b", re.I)),
    ("dependencies", re.compile(r"\b(what|which) (files? )?(uses?|imports?|depends? on|calls?|renders?)\b|\bused by\b|\bdepends? on\b|\bwho (uses|calls|imports)\b|\bwhat does .* (import|use|depend)", re.I)),
    ("stack", re.compile(r"\b(tech(nolog\w*)?|stack|framework\w*|librar\w+|built with|built using|dependenc\w+|packages?)\b", re.I)),
    ("api", re.compile(r"\b(api|endpoints?|routes?|http)\b.*\b(list|which|what|available|expose\w*|defined?)\b|\b(list|which|what) .*\b(api|endpoints?|routes?)\b", re.I)),
    ("overview", re.compile(r"\b(what is this|overview|summari[sz]e|what does (this|the) (project|app|application|repo\w*) do|purpose of (this|the) (project|app)|about this)\b", re.I)),
    ("locate", re.compile(r"\b(which|what) (files?|modules?|components?|parts?)\b|\bwhere (is|are|does|do)\b|\bresponsible\b|\bimplemented?\b|\bhandled?\b|\blocate\b|\bfind\b", re.I)),
]


def detect_intent(question: str) -> str:
    for name, rx in _INTENTS:
        if rx.search(question):
            return name
    return "concept"


def _terms(question: str) -> List[str]:
    return [t for t in tokenize(question) if t not in _STOP and len(t) > 1]


def _expand(terms: List[str]) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for t in terms:
        weights[t] = max(weights.get(t, 0), 1.0)
        for key, syn in _SYNONYMS.items():
            # exact word, member of the group, or a longer form of the key ("authentication" ~ "auth")
            if t == key or t in syn or (len(key) >= 3 and t.startswith(key)):
                for s in syn | {key}:
                    weights[s] = max(weights.get(s, 0), 0.6 if s != t else 1.0)
    return weights


def _file_tokens(path: str, f: Dict, node: Dict) -> Tuple[set, set, set]:
    """(path tokens, symbol tokens, concept tokens) for one file."""
    path_tokens = set(tokenize(path))
    sym = set()
    for fn in f.get("functions", []):
        sym |= set(tokenize(fn["name"]))
    for c in f.get("classes", []):
        sym |= set(tokenize(c["name"]))
    for c in f.get("components", []):
        sym |= set(tokenize(c))
    for r in f.get("routes", []):
        sym |= set(tokenize(r["path"])) | set(tokenize(r.get("handler") or ""))
    for m in f.get("models", []):
        sym |= set(tokenize(m["name"])) | set(tokenize(m.get("table") or ""))
    concept = set(f.get("tags", [])) | set(tokenize(node.get("subsystem") or "")) | set(tokenize(f.get("kind", "")))
    for imp in f.get("imports", []):
        if imp.get("external"):
            concept |= set(tokenize(imp["external"]))
    for k in f.get("jsx", {}).get("intrinsic", {}):
        concept |= set(tokenize(k))
    hint = f.get("summary_hint")
    if hint:
        concept |= set(tokenize(hint))
    return path_tokens, sym, concept


def rank_files(analysis: Dict, chunks: List[Tuple[str, str]], question: str, top_k: int = 8) -> List[Tuple[str, float, List[str]]]:
    files, graph = analysis["files"], analysis["graph"]
    terms = _terms(question)
    if not terms:
        return []
    weights = _expand(terms)

    # BM25-lite over chunks, aggregated per file
    df: Counter = Counter()
    chunk_tokens: List[Tuple[str, Counter, int]] = []
    for path, text in chunks:
        toks = tokenize(text)
        c = Counter(toks)
        chunk_tokens.append((path, c, len(toks)))
        for t in set(c):
            df[t] += 1
    n_chunks = max(len(chunk_tokens), 1)
    avg_len = (sum(l for _, _, l in chunk_tokens) / n_chunks) or 1
    lex: Dict[str, float] = defaultdict(float)
    for path, c, length in chunk_tokens:
        score = 0.0
        for t, w in weights.items():
            tf = c.get(t, 0)
            if tf:
                idf = math.log(1 + (n_chunks - df[t] + 0.5) / (df[t] + 0.5))
                score += w * idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / avg_len))
        lex[path] = max(lex[path], score)

    scores: Dict[str, float] = {}
    reasons: Dict[str, List[str]] = defaultdict(list)
    for path, f in files.items():
        node = graph["nodes"].get(path, {})
        ptoks, stoks, ctoks = _file_tokens(path, f, node)
        s = 0.0
        base_tokens = set(tokenize(posixpath.basename(path)))
        for t, w in weights.items():
            if t in base_tokens:
                s += 4.0 * w
                reasons[path].append(f"file name matches “{t}”")
            elif t in ptoks:
                s += 2.0 * w
                reasons[path].append(f"path matches “{t}”")
            if t in stoks:
                s += 3.0 * w
                reasons[path].append(f"defines “{t}”")
            if t in ctoks:
                s += 2.0 * w
                reasons[path].append(f"related to “{t}” ({', '.join(sorted(f.get('tags', [])[:3])) or f['kind']})")
        s += min(lex.get(path, 0.0), 6.0)
        if lex.get(path, 0) > 0.5:
            reasons[path].append("matching code content")
        if f["category"] in {"docs"} and not any(w in question.lower() for w in ("readme", "doc", "install", "setup", "run")):
            s *= 0.5
        if f["kind"] in {"lockfile", "test"} and "test" not in question.lower():
            s *= 0.6
        if s > 0:
            scores[path] = s

    # graph neighbourhood boost
    if scores:
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:3]
        boost: Dict[str, float] = defaultdict(float)
        for path, s in top:
            for e in graph["edges"]:
                if e["target"].startswith("endpoint:") or e["type"] in {"calls_api"}:
                    continue
                other = e["target"] if e["source"] == path else e["source"] if e["target"] == path else None
                if other and other in files:
                    boost[other] += 0.25 * s
                    reasons[other].append(f"directly connected to {posixpath.basename(path)}")
        for p, b in boost.items():
            scores[p] = scores.get(p, 0.0) + b

    if not scores:
        return []
    mx = max(scores.values())
    ranked = sorted(((p, s / mx, list(dict.fromkeys(reasons[p]))[:3]) for p, s in scores.items()), key=lambda x: (-x[1], x[0]))
    return ranked[:top_k]


def _short(analysis: Dict, path: str) -> str:
    f = analysis["files"][path]
    beh = _behaviour(f, path, analysis)
    label = KIND_LABELS.get(f["kind"], ("file",))[0]
    detail = beh[0] if beh else ""
    detail = detail.replace("\n", " ")
    return f"{label}. {detail}".strip()


def _find_named_file(analysis: Dict, question: str) -> Optional[str]:
    q = question.lower()
    best, best_len = None, 0
    for p in analysis["files"]:
        base = posixpath.basename(p).lower()
        stem = base.rsplit(".", 1)[0]
        for cand in (base, stem):
            if len(cand) >= 3 and re.search(rf"(?<![\w]){re.escape(cand)}(?![\w])", q) and len(cand) > best_len:
                best, best_len = p, len(cand)
    if best:
        return best
    # component / symbol names
    for p, f in analysis["files"].items():
        for name in f.get("components", []) + [c["name"] for c in f.get("classes", [])]:
            if len(name) >= 4 and re.search(rf"(?<![\w]){re.escape(name.lower())}(?![\w])", q) and len(name) > best_len:
                best, best_len = p, len(name)
    return best


def answer_question(analysis: Dict, chunks: List[Tuple[str, str]], question: str, top_k: int = 5,
                    threshold: float = 0.0) -> Dict:
    ctx, graph, files = analysis["context"], analysis["graph"], analysis["files"]
    intent = detect_intent(question)
    ranked = [r for r in rank_files(analysis, chunks, question, top_k=max(top_k, 8)) if r[1] >= threshold]
    sources: List[Dict] = []
    lines: List[str] = []
    named = _find_named_file(analysis, question)

    if intent == "startup":
        chains = ctx["architecture"]["startup_chains"]
        eps = graph["entry_points"]
        if eps:
            lines.append("Based on the detected entry points and import/render relationships:")
            for ep in eps[:3]:
                lines.append(f"- {_bt(ep['path'])} {ep['reason']}.")
            for chain in chains[:2]:
                lines.append("Startup path: " + " → ".join(_bt(p) for p in chain) + ".")
            first = chains[0] if chains else [eps[0]["path"]]
            last = first[-1] if first else None
            if len(first) > 1:
                main_kids = [e for e in graph["edges"] if e["source"] == first[min(2, len(first) - 1)]
                             and e["type"] in {"renders", "mounts"}]
                if main_kids:
                    lines.append(f"From there {_bt(first[min(2, len(first) - 1)])} brings in " +
                                 _lst([_bt(e["target"]) for e in main_kids], 6) + ".")
            path_files = list(dict.fromkeys([p for c in chains[:2] for p in c] + [e["path"] for e in eps]))
            sources = [{"file_path": p, "score": 1.0 - 0.05 * i, "reason": "on the startup path"} for i, p in enumerate(path_files[:top_k])]
        else:
            lines.append("No clear entry point was detected in the analysed files.")
    elif intent == "dependencies" and named:
        rel = file_relations(analysis, named)
        lines.append(f"{_bt(named)} is a {rel['role']}.")
        if rel["used_by"]:
            lines.append("It is used by: " + _lst([f"{_bt(u['path'])} ({u['relation']})" for u in rel["used_by"]], 8) + ".")
        else:
            lines.append("No other file in the project uses it directly.")
        if rel["depends_on"]:
            lines.append("It depends on: " + _lst([_bt(d["path"]) for d in rel["depends_on"]], 8) + ".")
        srcs = [named] + rel["related_files"]
        sources = [{"file_path": p, "score": max(0.3, 1.0 - 0.1 * i), "reason": "directly connected" if i else "the file you asked about"} for i, p in enumerate(srcs[:top_k])]
    elif intent == "stack":
        techs = ctx["technologies"]
        if techs:
            lines.append("Technologies detected (from manifests and imports): " + _lst([f"{t['name']}" for t in techs], 14) + ".")
        if ctx["tooling"]:
            lines.append("Development tooling: " + _lst([t["name"] for t in ctx["tooling"]], 8) + ".")
        lines.append(f"Project type: {ctx['project_type']}.")
        manifests = [p for p, f in files.items() if f["kind"] in {"package_manifest", "dependency_list"}]
        sources = [{"file_path": p, "score": 1.0, "reason": "declares dependencies"} for p in manifests[:top_k]]
    elif intent == "api":
        eps = graph["endpoints"]
        if eps:
            lines.append(f"The backend exposes {_plural(len(eps), 'endpoint')}:")
            for e in eps[:15]:
                lines.append(f"- {_bt(e['method'] + ' ' + e['path'])} → `{e['handler']}()` in {_bt(e['file'])}")
            exprs = sorted({e["prefix_expr"] for e in eps if e.get("prefix_expr")})
            if exprs:
                lines.append("Note: some routers are mounted under a prefix set by " + _lst([_bt(x) for x in exprs]) +
                             ", whose value is not known statically, so real URLs may include an extra prefix.")
            if graph.get("consumers"):
                cf = sorted({c["file"] for c in graph["consumers"]})
                lines.append(f"Called from the frontend by {_lst([_bt(c) for c in cf])} (inferred by matching request URLs).")
            sources = [{"file_path": p, "score": 1.0 - 0.05 * i, "reason": "defines endpoints"} for i, p in enumerate(dict.fromkeys(e["file"] for e in eps))][:top_k]
        else:
            lines.append("No HTTP endpoints were detected in the analysed files.")
    elif intent == "overview":
        lines.append(ctx["summary"])
        if ctx.get("purpose"):
            lines.append(f"Stated purpose ({ctx['purpose_source']}): “{ctx['purpose'][:220]}”")
        sources = [{"file_path": p, "score": 1.0, "reason": "project documentation / manifest"} for p in ([ctx["purpose_source"]] if ctx.get("purpose_source") else [])]
    else:
        if not ranked:
            lines.append("I couldn't find files in this project that match that question. "
                         "Try naming a file, component, feature or technology. Here is an overview instead:")
            lines.append(ctx["summary"])
        else:
            top = ranked[:top_k]
            verb = "The files most responsible are:" if intent == "locate" else "The most relevant files are:"
            lines.append(verb)
            for p, s, why in top:
                lines.append(f"- {_bt(p)} — {_short(analysis, p)}")
            top_paths = [p for p, _, _ in top]
            rel_lines = []
            for e in graph["edges"]:
                if e["source"] in top_paths and e["target"] in top_paths and e["type"] in {"renders", "mounts", "calls", "imports"}:
                    rel_lines.append(f"{_bt(posixpath.basename(e['source']))} {_REL_VERB[e['type']]} {_bt(posixpath.basename(e['target']))}")
            if rel_lines:
                lines.append("How they connect: " + "; ".join(rel_lines[:8]) + ".")
            chain = analysis["graph"]["nodes"].get(top_paths[0], {})
            sources = [{"file_path": p, "score": round(s, 4), "reason": "; ".join(why) or "relevant content"} for p, s, why in top]

    if not sources and ranked:
        sources = [{"file_path": p, "score": round(s, 4), "reason": "; ".join(w) or "relevant content"} for p, s, w in ranked[:top_k]]
    lines.append("")
    lines.append(f"(Answer built from static analysis of {len(files)} files in this project; {intent} question. No language model was used.)")
    return {
        "answer": "\n".join(lines), "sources": sources[:top_k], "intent": intent,
        "related_files": [p for p, _, _ in ranked[:top_k]],
    }


_REL_VERB = {"renders": "renders", "mounts": "mounts", "calls": "calls into", "imports": "imports"}
