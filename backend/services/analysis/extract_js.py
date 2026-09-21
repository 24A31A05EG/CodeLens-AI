"""
Static fact extraction for JavaScript / TypeScript / JSX / TSX.

Approach: a small scanner produces two views of the source with identical
offsets and line numbers -

* ``code``   - comments blanked, string contents intact (for reading import
               specifiers, API paths, route paths);
* ``masked`` - comments blanked AND string/template contents blanked (for
               structural regexes and brace matching, so text inside strings or
               comments can never look like code).

This is regex-level analysis, not a full parser. Facts are reported with
``confidence: "medium"``; known blind spots (regex literals containing quotes,
JSX text containing apostrophes) can hide a construct but never invent one.
"""

import bisect
import re
from typing import Dict, List, Optional, Tuple

from services.analysis.knowledge import is_three_intrinsic
from services.analysis.redact import redact_secrets


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_js(src: str) -> Tuple[str, str, List[dict]]:
    n = len(src)
    code = list(src)
    masked = list(src)
    comments: List[dict] = []

    def blank(buf, a, b):
        for k in range(a, min(b, n)):
            if buf[k] != "\n":
                buf[k] = " "

    i, line = 0, 1
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            comments.append({"start": line, "end": line, "text": src[i + 2:j].strip(), "block": False})
            blank(code, i, j)
            blank(masked, i, j)
            i = j
            continue
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            raw = src[i + 2:max(j - 2, i + 2)]
            text = "\n".join(re.sub(r"^\s*\*\s?", "", ln).rstrip() for ln in raw.splitlines()).strip()
            start_line = line
            line += src.count("\n", i, j)
            comments.append({"start": start_line, "end": line, "text": text, "block": True})
            blank(code, i, j)
            blank(masked, i, j)
            i = j
            continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == "\\":
                    j += 1
                j += 1
            blank(masked, i + 1, j)
            i = j + 1 if (j < n and src[j] == c) else j
            continue
        if c == "`":
            j, depth = i + 1, 0
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if depth == 0 and ch == "`":
                    break
                if ch == "$" and j + 1 < n and src[j + 1] == "{":
                    depth += 1
                    j += 2
                    continue
                if depth > 0 and ch == "{":
                    depth += 1
                elif depth > 0 and ch == "}":
                    depth -= 1
                j += 1
            end = min(j, n)
            line += src.count("\n", i, end)
            blank(masked, i + 1, end)
            i = end + 1
            continue
        i += 1
    return "".join(code), "".join(masked), comments


def _balanced(masked: str, open_idx: int, open_ch: str, close_ch: str) -> int:
    """Index of the matching close char for the open char at ``open_idx`` (or len)."""
    depth = 0
    for k in range(open_idx, len(masked)):
        ch = masked[k]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return k
    return len(masked)


# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

_IMPORT_FROM = re.compile(
    r"""\bimport\s+(?P<type>type\s+)?(?P<clause>[^;'"`]*?)\s*\bfrom\s*['"](?P<src>[^'"\n]*)['"]""", re.DOTALL
)
_IMPORT_SIDE = re.compile(r"""(?m)^\s*import\s*['"](?P<src>[^'"\n]*)['"]""")
_REEXPORT = re.compile(r"""\bexport\s+(?:type\s+)?(?P<what>\*(?:\s+as\s+\w+)?|\{[^}]*\})\s*from\s*['"](?P<src>[^'"\n]*)['"]""")
_REQUIRE = re.compile(
    r"""(?:(?:const|let|var)\s+(?P<lhs>\{[^}]*\}|[\w$]+)\s*=\s*)?\brequire\(\s*['"](?P<src>[^'"\n]*)['"]\s*\)"""
)
_DYNAMIC_IMPORT = re.compile(r"""\bimport\(\s*['"](?P<src>[^'"\n]*)['"]\s*\)""")
_LAZY = re.compile(
    r"""(?:const|let|var)\s+(?P<name>[\w$]+)\s*=\s*(?:React\.)?lazy\(\s*\(\s*\)\s*=>\s*import\(\s*['"](?P<src>[^'"\n]*)['"]\s*\)"""
)

_FUNC_DECL = re.compile(
    r"(?m)^[ \t]*(?P<exp>export\s+)?(?P<default>default\s+)?(?P<async>async\s+)?function\s*\*?\s*(?P<name>[A-Za-z_$][\w$]*)?\s*\("
)
_VAR_DECL = re.compile(
    r"(?m)^[ \t]*(?P<exp>export\s+)?(?:default\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*"
)
_CLASS_DECL = re.compile(
    r"(?m)^[ \t]*(?P<exp>export\s+)?(?P<default>default\s+)?(?:abstract\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)(?:\s+extends\s+(?P<base>[\w$.]+))?"
)
_TYPE_DECL = re.compile(r"(?m)^[ \t]*(?:export\s+)?(?:interface|type|enum)\s+(?P<name>[A-Za-z_$][\w$]*)")
_WRAPPER = re.compile(r"^(?:(?:React\.)?(?:memo|forwardRef|observer)\s*\(\s*)")
_EXPORT_DEFAULT_NAME = re.compile(r"(?m)^\s*export\s+default\s+(?P<name>[A-Za-z_$][\w$]*)\s*;?\s*$")
_EXPORT_LIST = re.compile(r"(?m)^\s*export\s*\{(?P<body>[^}]*)\}\s*(?!from)")
_EXPORT_NAMED = re.compile(r"(?m)^\s*export\s+(?:async\s+)?(?:const|let|var|function\*?|class)\s+(?P<name>[A-Za-z_$][\w$]*)")

_JSX_TAG = re.compile(r"(?:(?<=[\s(\{>,?:&|=])|^)<(?P<tag>[A-Za-z][\w.]*)(?=[\s/>])", re.MULTILINE)
_HOOK_CALL = re.compile(r"\b(?P<hook>use[A-Z][\w$]*)\s*\(")
_STATE_DECL = re.compile(r"\bconst\s*\[\s*(?P<a>[\w$]+)\s*,\s*(?P<b>[\w$]+)\s*\]\s*=\s*(?:React\.)?useState\b")
_EVENT_PROP = re.compile(r"\b(?P<ev>on[A-Z][A-Za-z]+)\s*=\s*\{")
_ADD_LISTENER = re.compile(r"""\baddEventListener\(\s*['"](?P<ev>[\w:-]+)['"]""")
_NEW_CLASS = re.compile(r"\bnew\s+(?P<ns>[A-Za-z_$][\w$]*\.)?(?P<cls>[A-Z][\w$]*)\s*\(")
_GSAP_CALL = re.compile(r"\bgsap\.(?P<fn>to|from|fromTo|set|timeline|registerPlugin|context|matchMedia)\b")
_ENV_PROCESS = re.compile(r"\bprocess\.env\.(?P<n>[A-Z_][A-Z0-9_]*)")
_ENV_VITE = re.compile(r"\bimport\.meta\.env\.(?P<n>[A-Za-z_][\w]*)")
_EXPRESS_ROUTE = re.compile(
    r"""\b(?P<obj>app|router|server|api)\.(?P<m>get|post|put|delete|patch|all)\(\s*['"`](?P<path>/[^'"`\n]*)['"`]"""
)
_ROOT_RENDER = re.compile(r"\b(?:createRoot|hydrateRoot)\s*\(|\bReactDOM\.render\s*\(|\bcreateApp\s*\([^)]*\)\s*\.mount\s*\(")
_LISTEN = re.compile(r"\b(?:app|server)\.listen\s*\(")
_FETCH = re.compile(r"\bfetch\s*\(")
_AXIOS = re.compile(r"\baxios(?:\.(?P<m>get|post|put|delete|patch))?\s*\(")
_PROPS_ACCESS = re.compile(r"\bprops\.(?P<p>[A-Za-z_$][\w$]*)")

_LICENSE_HINT = re.compile(r"license|copyright|eslint|prettier|@ts-|istanbul|@flow|@jsx|use strict|<reference", re.I)


def _line_index(text: str) -> List[int]:
    starts = [0]
    for m in re.finditer(r"\n", text):
        starts.append(m.end())
    return starts


def _line_of(starts: List[int], idx: int) -> int:
    return bisect.bisect_right(starts, idx)


def _split_params(params_masked: str, params_code: str) -> List[str]:
    """Names of parameters/destructured props from a parameter list."""
    text = params_code.strip()
    if not text:
        return []
    names: List[str] = []
    m = re.match(r"^\{(?P<body>.*)\}", text, re.DOTALL)
    if m:  # destructured props
        depth, cur, parts = 0, "", []
        for ch in m.group("body"):
            if ch in "{[(":
                depth += 1
            elif ch in "}])":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part.startswith("..."):
                names.append(part[3:].strip().split(":")[0] or "rest")
                continue
            pn = re.split(r"[:=]", part, 1)[0].strip()
            if re.match(r"^[A-Za-z_$][\w$]*$", pn):
                names.append(pn)
        return names
    for part in re.split(r",(?![^(\[{]*[)\]}])", text):
        pn = re.split(r"[:=]", part.strip(), 1)[0].strip().lstrip(".")
        if re.match(r"^[A-Za-z_$][\w$]*$", pn):
            names.append(pn)
    return names


def _parse_import_clause(clause: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """-> (default, namespace, named_local_names as 'imported as local' tuples flattened)."""
    default = namespace = None
    named: List[str] = []
    clause = clause.strip()
    if not clause:
        return None, None, []
    brace = re.search(r"\{(?P<body>.*)\}", clause, re.DOTALL)
    head = clause[: brace.start()] if brace else clause
    head = head.strip().rstrip(",").strip()
    if head:
        ns = re.match(r"^\*\s+as\s+([\w$]+)$", head)
        if ns:
            namespace = ns.group(1)
        else:
            parts = [p.strip() for p in head.split(",") if p.strip()]
            for p in parts:
                nsm = re.match(r"^\*\s+as\s+([\w$]+)$", p)
                if nsm:
                    namespace = nsm.group(1)
                elif re.match(r"^[\w$]+$", p):
                    default = p
    if brace:
        for item in brace.group("body").split(","):
            item = re.sub(r"^\s*type\s+", "", item.strip())
            if not item:
                continue
            m = re.match(r"^([\w$]+)\s+as\s+([\w$]+)$", item)
            named.append(f"{m.group(1)}:{m.group(2)}" if m else item)
    return default, namespace, named


def extract_js_facts(source: str, path: str, language: str) -> Dict:
    code, masked, comments = scan_js(source)
    starts = _line_index(source)
    is_jsx_file = path.lower().endswith((".jsx", ".tsx", ".js", ".mjs", ".cjs"))
    lines = source.count("\n") + 1

    facts: Dict = {
        "imports": [], "bindings": {}, "exports": {"default": None, "named": []},
        "functions": [], "classes": [], "types": [], "components": [], "custom_hooks": [],
        "hooks_used": {}, "jsx": {"components": {}, "intrinsic": {}}, "props": {}, "state": [],
        "events": [], "routes": [], "api_calls": [], "env_vars": [], "three_classes": [],
        "gsap_calls": [], "entry_signals": [], "renders": [], "calls": [],
        "summary_hint": None, "confidence": "medium", "line_count": lines,
    }

    # ---- header comment (file's own statement of purpose) ----
    first_code = re.search(r"\S", code)
    first_code_line = _line_of(starts, first_code.start()) if first_code else lines + 1
    for cm in comments:
        if cm["end"] < first_code_line and cm["text"] and not _LICENSE_HINT.search(cm["text"][:80]):
            facts["summary_hint"] = redact_secrets(cm["text"].strip())[:400]
            break

    # ---- imports ----
    bindings: Dict[str, Dict] = {}

    def add_import(spec, default=None, namespace=None, named=None, line=1, kind="static", type_only=False):
        named = named or []
        record = {
            "source": spec, "default": default, "namespace": namespace,
            "names": [n.split(":")[1] if ":" in n else n for n in named],
            "imported": [n.split(":")[0] for n in named],
            "line": line, "kind": kind, "type_only": type_only,
            "side_effect": not (default or namespace or named),
        }
        facts["imports"].append(record)
        if default:
            bindings[default] = {"source": spec, "imported": "default"}
        if namespace:
            bindings[namespace] = {"source": spec, "imported": "*"}
        for n in named:
            imp, _, loc = n.partition(":")
            bindings[loc or imp] = {"source": spec, "imported": imp}

    def spec(m):  # specifier text: located on ``masked`` (so strings/comments are ignored), read from ``code``
        return code[m.start("src"):m.end("src")]

    for m in _IMPORT_FROM.finditer(masked):
        d, ns, named = _parse_import_clause(m.group("clause"))
        add_import(spec(m), d, ns, named, _line_of(starts, m.start()), type_only=bool(m.group("type")))
    for m in _IMPORT_SIDE.finditer(masked):
        add_import(spec(m), line=_line_of(starts, m.start()), kind="side-effect")
    for m in _REEXPORT.finditer(masked):
        what = m.group("what")
        named = []
        if what.startswith("{"):
            named = [x.strip() for x in what.strip("{}").split(",") if x.strip()]
            named = [re.sub(r"\s+as\s+", ":", n) for n in named]
        add_import(spec(m), named=named, line=_line_of(starts, m.start()), kind="re-export")
        facts["exports"]["named"].extend(n.split(":")[-1] for n in named)
    for m in _REQUIRE.finditer(masked):
        lhs = (m.group("lhs") or "").strip()
        if lhs.startswith("{"):
            names = [re.sub(r":\s*", ":", x.strip()) for x in lhs.strip("{}").split(",") if x.strip()]
            add_import(spec(m), named=names, line=_line_of(starts, m.start()), kind="require")
        elif lhs:
            add_import(spec(m), default=lhs, line=_line_of(starts, m.start()), kind="require")
        else:
            add_import(spec(m), line=_line_of(starts, m.start()), kind="require")
    lazy_specs = set()
    for m in _LAZY.finditer(masked):
        add_import(spec(m), default=m.group("name"), line=_line_of(starts, m.start()), kind="dynamic")
        lazy_specs.add(spec(m))
    for m in _DYNAMIC_IMPORT.finditer(masked):
        if spec(m) not in lazy_specs:
            add_import(spec(m), line=_line_of(starts, m.start()), kind="dynamic")
    facts["bindings"] = bindings

    # ---- functions / components / hooks (with body ranges) ----
    ranges: List[Dict] = []

    def record_function(name, start_idx, open_paren_idx, exported, is_default, is_async, wrapped=False):
        close_paren = _balanced(masked, open_paren_idx, "(", ")")
        params_code = code[open_paren_idx + 1:close_paren]
        params = _split_params(masked[open_paren_idx + 1:close_paren], params_code)
        after = close_paren + 1
        body_start = masked.find("{", after, after + 200) if "=>" not in masked[after:after + 60].split("{")[0] else -1
        arrow = re.match(r"\s*(?::[^={]+)?=>\s*", masked[after:after + 200])
        if arrow:
            expr_start = after + arrow.end()
            if expr_start < len(masked) and masked[expr_start] == "{":
                body_end = _balanced(masked, expr_start, "{", "}")
                body_range = (expr_start, body_end)
            else:
                end_m = re.search(r"\n(?=(?:export|const|let|var|function|class|import)\b)|;", masked[expr_start:expr_start + 3000])
                body_range = (expr_start, expr_start + (end_m.start() if end_m else 400))
        elif body_start != -1:
            body_range = (body_start, _balanced(masked, body_start, "{", "}"))
        else:
            body_range = (after, min(after + 200, len(masked)))
        return name, params, body_range

    def add_function(name, idx, params, body_range, exported, is_default, is_async, wrapper=False):
        body = masked[body_range[0]:body_range[1]]
        line = _line_of(starts, idx)
        has_jsx = bool(_JSX_TAG.search(body)) or "createElement(" in body
        pascal = bool(re.match(r"^[A-Z]", name or ""))
        is_hook = bool(re.match(r"^use[A-Z0-9]", name or ""))
        is_component = pascal and (has_jsx or "return null" in body or wrapper)
        doc = None
        for cm in comments:
            if cm["block"] and cm["end"] == line - 1 or (cm["end"] == line - 1 and not cm["block"]):
                doc = redact_secrets(cm["text"].strip().splitlines()[0])[:200] if cm["text"].strip() else None
        info = {
            "name": name, "line": line, "async": is_async, "params": params[:12],
            "exported": exported, "default_export": is_default,
            "is_component": is_component, "is_hook": is_hook, "doc": doc,
            "length": _line_of(starts, body_range[1]) - line + 1,
        }
        facts["functions"].append(info)
        ranges.append({"name": name, "range": body_range, "component": is_component, "hook": is_hook, "params": params})
        if is_component:
            facts["components"].append(name)
            if params:
                facts["props"][name] = params[:20]
        if is_hook:
            facts["custom_hooks"].append(name)

    seen_lines = set()
    for m in _FUNC_DECL.finditer(masked):
        name = m.group("name") or ("default" if m.group("default") else None)
        if not name:
            continue
        open_idx = m.end() - 1
        _, params, rng = record_function(name, m.start(), open_idx, bool(m.group("exp")), bool(m.group("default")), bool(m.group("async")))
        add_function(name, m.start(), params, rng, bool(m.group("exp")), bool(m.group("default")), bool(m.group("async")))
        seen_lines.add(m.start())
        if m.group("default") and m.group("name"):
            facts["exports"]["default"] = m.group("name")
        elif m.group("exp") and not m.group("default"):
            facts["exports"]["named"].append(name)

    for m in _VAR_DECL.finditer(masked):
        rhs_start = m.end()
        rhs = masked[rhs_start:rhs_start + 240]
        wrapper = _WRAPPER.match(rhs)
        off = wrapper.end() if wrapper else 0
        rest = rhs[off:]
        is_async = bool(re.match(r"async\b", rest))
        rest2 = re.sub(r"^async\s+", "", rest)
        base = rhs_start + off + (len(rest) - len(rest2))
        params_idx = None
        if re.match(r"function\b", rest2):
            pm = re.search(r"\(", rest2)
            params_idx = base + pm.start() if pm else None
        elif rest2.startswith("("):
            close = _balanced(masked, base, "(", ")")
            if re.match(r"\s*(?::[^={]+)?=>", masked[close + 1:close + 120]):
                params_idx = base
        elif re.match(r"[A-Za-z_$][\w$]*\s*=>", rest2):
            ident = re.match(r"([A-Za-z_$][\w$]*)\s*=>", rest2)
            # single-identifier arrow parameter: synthesize a params range
            arrow_pos = base + ident.end()
            expr_start = arrow_pos
            while expr_start < len(masked) and masked[expr_start] in " \t\n":
                expr_start += 1
            if expr_start < len(masked) and masked[expr_start] == "{":
                rng = (expr_start, _balanced(masked, expr_start, "{", "}"))
            else:
                end_m = re.search(r"\n(?=(?:export|const|let|var|function|class|import)\b)|;", masked[expr_start:expr_start + 3000])
                rng = (expr_start, expr_start + (end_m.start() if end_m else 400))
            add_function(m.group("name"), m.start(), [ident.group(1)], rng, bool(m.group("exp")), False, is_async, bool(wrapper))
            if m.group("exp"):
                facts["exports"]["named"].append(m.group("name"))
            continue
        if params_idx is None:
            continue
        _, params, rng = record_function(m.group("name"), m.start(), params_idx, bool(m.group("exp")), False, is_async, bool(wrapper))
        add_function(m.group("name"), m.start(), params, rng, bool(m.group("exp")), False, is_async, bool(wrapper))
        if m.group("exp"):
            facts["exports"]["named"].append(m.group("name"))

    for m in _CLASS_DECL.finditer(masked):
        name, base = m.group("name"), m.group("base")
        open_idx = masked.find("{", m.end())
        end = _balanced(masked, open_idx, "{", "}") if open_idx != -1 else m.end()
        body = masked[open_idx:end] if open_idx != -1 else ""
        methods = [
            mm.group("n") for mm in re.finditer(r"(?m)^[ \t]+(?:static\s+|async\s+)*(?P<n>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", body)
            if mm.group("n") not in {"if", "for", "while", "switch", "catch", "function"}
        ]
        line = _line_of(starts, m.start())
        cls = {"name": name, "line": line, "bases": [base] if base else [], "methods": methods[:30], "doc": None}
        facts["classes"].append(cls)
        if base and re.search(r"(?:^|\.)(?:Pure)?Component$", base):
            facts["components"].append(name)
        if m.group("default"):
            facts["exports"]["default"] = name
        elif m.group("exp"):
            facts["exports"]["named"].append(name)

    for m in _TYPE_DECL.finditer(masked):
        facts["types"].append(m.group("name"))

    for m in _EXPORT_DEFAULT_NAME.finditer(masked):
        if m.group("name") not in {"function", "class", "async"}:
            facts["exports"]["default"] = m.group("name")
    for m in _EXPORT_LIST.finditer(masked):
        for item in m.group("body").split(","):
            item = item.strip()
            if not item:
                continue
            mm = re.match(r"^([\w$]+)(?:\s+as\s+([\w$]+))?$", item)
            if mm:
                if mm.group(2) == "default":
                    facts["exports"]["default"] = mm.group(1)
                else:
                    facts["exports"]["named"].append(mm.group(2) or mm.group(1))
    for m in _EXPORT_NAMED.finditer(masked):
        facts["exports"]["named"].append(m.group("name"))
    if re.search(r"\bexport\s+default\b", masked) and not facts["exports"]["default"]:
        facts["exports"]["default"] = "(anonymous)"
    facts["exports"]["named"] = sorted(set(facts["exports"]["named"]))
    if re.search(r"\bmodule\.exports\b|\bexports\.\w+\s*=", masked):
        facts["exports"]["commonjs"] = True

    # ---- JSX usage ----
    if is_jsx_file:
        first_render_line: Dict[str, int] = {}
        for m in _JSX_TAG.finditer(masked):
            tag = m.group("tag")
            base = tag.split(".")[0]
            if tag[0].isupper() or "." in tag:
                facts["jsx"]["components"][tag] = facts["jsx"]["components"].get(tag, 0) + 1
                first_render_line.setdefault(base, _line_of(starts, m.start()))
            else:
                facts["jsx"]["intrinsic"][tag] = facts["jsx"]["intrinsic"].get(tag, 0) + 1
        for tag, count in facts["jsx"]["components"].items():
            base = tag.split(".")[0]
            facts["renders"].append({"name": tag, "base": base, "count": count, "line": first_render_line.get(base, 1)})

    # ---- hooks, state, events ----
    for m in _HOOK_CALL.finditer(masked):
        if masked[max(0, m.start() - 9):m.start()].rstrip().endswith("function"):
            continue  # a hook *definition*, not a use
        facts["hooks_used"][m.group("hook")] = facts["hooks_used"].get(m.group("hook"), 0) + 1
    for m in _STATE_DECL.finditer(masked):
        facts["state"].append(m.group("a"))
    ev = {m.group("ev") for m in _EVENT_PROP.finditer(masked)}
    ev |= {f"addEventListener('{m.group('ev')}')" for m in _ADD_LISTENER.finditer(code)}
    facts["events"] = sorted(ev)[:25]

    # ---- library usage: three.js classes, gsap ----
    three_names = {loc for loc, b in bindings.items() if b["source"] == "three" or b["source"].startswith("three/")}
    three_ns = {loc for loc, b in bindings.items() if b["source"] == "three" and b["imported"] == "*"}
    three_used = set()
    for m in _NEW_CLASS.finditer(masked):
        ns, cls = (m.group("ns") or "").rstrip("."), m.group("cls")
        if (ns and ns in three_ns) or (not ns and cls in three_names):
            three_used.add(cls)
    facts["three_classes"] = sorted(three_used)
    facts["gsap_calls"] = sorted({m.group("fn") for m in _GSAP_CALL.finditer(masked)})

    # ---- per-component detail: hooks + renders inside each component body ----
    comp_detail = {}
    for r in ranges:
        if r["component"] or r["hook"]:
            body = masked[r["range"][0]:r["range"][1]]
            hooks = sorted({
                mm.group("hook") for mm in _HOOK_CALL.finditer(body)
                if not body[max(0, mm.start() - 9):mm.start()].rstrip().endswith("function")
            } - {r["name"]})
            kids = sorted({mm.group("tag") for mm in _JSX_TAG.finditer(body) if mm.group("tag")[0].isupper() or "." in mm.group("tag")})
            intrinsic = sorted({mm.group("tag") for mm in _JSX_TAG.finditer(body) if mm.group("tag")[0].islower() and "." not in mm.group("tag")})
            accessed = sorted({mm.group("p") for mm in _PROPS_ACCESS.finditer(body)})
            comp_detail[r["name"]] = {"hooks": hooks, "renders": kids, "intrinsic": intrinsic[:20], "props_accessed": accessed[:20]}
            if accessed and r["name"] not in facts["props"]:
                facts["props"][r["name"]] = accessed
    facts["component_detail"] = comp_detail

    # ---- network + routes + env + entry signals ----
    for m in _FETCH.finditer(masked):
        arg, opts = _call_first_arg(code, masked, m.end() - 1)
        if arg is not None:
            method = None
            mm = re.search(r"""method\s*:\s*['"](?P<m>[A-Za-z]+)['"]""", opts or "")
            if mm:
                method = mm.group("m").upper()
            facts["api_calls"].append({"target": arg, "method": method or "GET", "via": "fetch", "line": _line_of(starts, m.start())})
    for m in _AXIOS.finditer(masked):
        arg, _ = _call_first_arg(code, masked, m.end() - 1)
        if arg is not None:
            facts["api_calls"].append({"target": arg, "method": (m.group("m") or "GET").upper(), "via": "axios", "line": _line_of(starts, m.start())})
    for m in _EXPRESS_ROUTE.finditer(code):
        facts["routes"].append({
            "method": m.group("m").upper(), "path": m.group("path"), "handler": None,
            "line": _line_of(starts, m.start()), "framework": "express",
        })
    facts["env_vars"] = sorted({m.group("n") for m in _ENV_PROCESS.finditer(masked)} | {m.group("n") for m in _ENV_VITE.finditer(masked)})

    if _ROOT_RENDER.search(masked):
        facts["entry_signals"].append("root_render")
    if _LISTEN.search(masked) or facts["routes"]:
        if _LISTEN.search(masked):
            facts["entry_signals"].append("http_listen")

    # ---- calls to imported bindings (for 'calls' edges) ----
    called = {}
    for m in re.finditer(r"(?<![\w$.])(?P<n>[A-Za-z_$][\w$]*)\s*\(", masked):
        n = m.group("n")
        if n in bindings and n not in called and not n[0].isupper():
            called[n] = _line_of(starts, m.start())
    for m in re.finditer(r"(?<![\w$.])(?P<ns>[A-Za-z_$][\w$]*)\.(?P<n>[A-Za-z_$][\w$]*)\s*\(", masked):
        ns = m.group("ns")
        if ns in bindings and bindings[ns]["imported"] == "*":
            called.setdefault(f"{ns}.{m.group('n')}", _line_of(starts, m.start()))
    facts["calls"] = [{"name": n, "line": ln} for n, ln in sorted(called.items(), key=lambda kv: kv[1])]

    facts["functions"].sort(key=lambda f: f["line"])
    facts["components"] = sorted(set(facts["components"]), key=lambda n: next((f["line"] for f in facts["functions"] if f["name"] == n), 0))
    facts["custom_hooks"] = sorted(set(facts["custom_hooks"]))
    return facts


def _call_first_arg(code: str, masked: str, open_idx: int) -> Tuple[Optional[str], Optional[str]]:
    """Text of the first call argument (from ``code``) and the remainder (options)."""
    close = _balanced(masked, open_idx, "(", ")")
    inner_code = code[open_idx + 1:close]
    inner_mask = masked[open_idx + 1:close]
    depth, cut = 0, len(inner_mask)
    for k, ch in enumerate(inner_mask):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            cut = k
            break
    first = inner_code[:cut].strip()
    if not first:
        return None, None
    return first[:300], inner_code[cut + 1:cut + 400]
