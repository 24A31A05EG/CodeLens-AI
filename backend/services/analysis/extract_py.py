"""
Static fact extraction for Python using the standard-library ``ast`` module.

Python facts are reported with ``confidence: "high"`` because they come from a
real parse tree. If the file has a syntax error the caller falls back to the
generic extractor.
"""

import ast
import re
from typing import Dict, List, Optional

from services.analysis.redact import redact_secrets

_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}
_ORM_BASES = {"Base", "DeclarativeBase", "Model", "db.Model", "SQLModel"}
_DB_CALL_ATTRS = {"query", "add", "add_all", "commit", "rollback", "execute", "flush", "refresh", "merge"}
_SESSION_FACTORIES = {"create_engine", "sessionmaker", "scoped_session", "create_async_engine", "MongoClient", "connect"}


def _unparse(node: Optional[ast.AST]) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return ""


def _first_doc_line(node) -> Optional[str]:
    doc = ast.get_docstring(node)
    if not doc:
        return None
    line = doc.strip().splitlines()[0].strip()
    return redact_secrets(line)[:200] or None


def _const_str(node: Optional[ast.AST]) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _complexity(fn: ast.AST) -> int:
    score = 1
    for node in ast.walk(fn):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.comprehension)):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
    return score


def _attr_root(node: ast.AST) -> Optional[str]:
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return None


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def extract_python_facts(source: str, path: str) -> Optional[Dict]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        # Python 3.14 allows `except A, B:` without parentheses (PEP 758). Older
        # parsers reject it, so parenthesise it (line numbers are preserved) and retry.
        patched = re.sub(r"(?m)^(\s*except\*?\s+)([\w.]+(?:\s*,\s*[\w.]+)+)(\s*:)", r"\1(\2)\3", source)
        if patched == source:
            return None
        try:
            tree = ast.parse(patched)
        except (SyntaxError, ValueError):
            return None

    facts: Dict = {
        "imports": [], "bindings": {}, "exports": {"default": None, "named": []},
        "functions": [], "classes": [], "types": [], "components": [], "custom_hooks": [],
        "routes": [], "router_prefixes": {}, "include_routers": [], "api_calls": [],
        "models": [], "env_vars": [], "db_usage": [], "calls": [], "entry_signals": [],
        "app_objects": [], "side_effects": [], "summary_hint": None, "confidence": "high",
        "line_count": source.count("\n") + 1, "test_functions": [],
    }
    facts["summary_hint"] = _first_doc_line(tree)

    bindings: Dict[str, Dict] = {}

    # ---- imports (any depth, but top-level bindings matter most) ----
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                facts["imports"].append({
                    "source": alias.name, "level": 0, "names": [], "imported": [],
                    "alias": alias.asname, "line": node.lineno, "kind": "import",
                })
                local = alias.asname or alias.name.split(".")[0]
                bindings[local] = {"source": alias.name, "imported": "*", "level": 0}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [a.name for a in node.names]
            facts["imports"].append({
                "source": module, "level": node.level, "names": [a.asname or a.name for a in node.names],
                "imported": names, "line": node.lineno, "kind": "from",
            })
            for alias in node.names:
                bindings[alias.asname or alias.name] = {"source": module, "imported": alias.name, "level": node.level}
    facts["bindings"] = bindings

    # ---- top-level functions / classes / assignments ----
    def handle_function(fn, owner: Optional[str] = None):
        params = [a.arg for a in fn.args.args if a.arg not in ("self", "cls")]
        params += [a.arg for a in fn.args.kwonlyargs]
        decorators = [redact_secrets(_unparse(d))[:120] for d in fn.decorator_list]
        info = {
            "name": f"{owner}.{fn.name}" if owner else fn.name,
            "line": fn.lineno, "async": isinstance(fn, ast.AsyncFunctionDef),
            "params": params[:12], "decorators": decorators[:4],
            "doc": _first_doc_line(fn), "returns": _unparse(fn.returns)[:60] or None,
            "complexity": _complexity(fn), "method": owner is not None,
            "length": (getattr(fn, "end_lineno", fn.lineno) or fn.lineno) - fn.lineno + 1,
            "exported": not fn.name.startswith("_"),
        }
        facts["functions"].append(info)
        if fn.name.startswith("test_"):
            facts["test_functions"].append(info["name"])
        # routes via decorators
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                attr = dec.func.attr
                obj = _dotted(dec.func.value)
                first = _const_str(dec.args[0]) if dec.args else None
                if first is None:
                    for kw in dec.keywords:
                        if kw.arg == "path":
                            first = _const_str(kw.value)
                if attr in _HTTP_VERBS and first is not None:
                    facts["routes"].append({
                        "method": attr.upper(), "path": first, "handler": fn.name,
                        "line": fn.lineno, "framework": "fastapi/flask", "object": obj,
                        "summary": info["doc"],
                    })
                elif attr in {"route", "api_route"} and first is not None:
                    methods = ["GET"]
                    for kw in dec.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            methods = [_const_str(e).upper() for e in kw.value.elts if _const_str(e)] or methods
                    for meth in methods:
                        facts["routes"].append({
                            "method": meth, "path": first, "handler": fn.name, "line": fn.lineno,
                            "framework": "fastapi/flask", "object": obj, "summary": info["doc"],
                        })
                elif attr == "websocket" and first is not None:
                    facts["routes"].append({
                        "method": "WEBSOCKET", "path": first, "handler": fn.name, "line": fn.lineno,
                        "framework": "fastapi", "object": obj, "summary": info["doc"],
                    })
        return info

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            handle_function(node)
        elif isinstance(node, ast.ClassDef):
            bases = [_unparse(b) for b in node.bases]
            methods = []
            columns: List[str] = []
            tablename = None
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    handle_function(item, owner=node.name)
                    methods.append(item.name)
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            if t.id == "__tablename__":
                                tablename = _const_str(item.value)
                            elif isinstance(item.value, ast.Call) and _dotted(item.value.func).split(".")[-1] in {"Column", "mapped_column", "relationship", "Field"}:
                                columns.append(t.id)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if isinstance(item.value, ast.Call) and _dotted(item.value.func).split(".")[-1] in {"mapped_column", "Column", "Field", "relationship"}:
                        columns.append(item.target.id)
                    elif tablename is None and node.bases:
                        columns.append(item.target.id)
            flavor = None
            if tablename or any(b in _ORM_BASES or b.endswith(".Model") for b in bases):
                flavor = "orm"
            elif any(b.split(".")[-1] in {"BaseModel", "BaseSettings"} for b in bases):
                flavor = "pydantic"
            elif any(b.split(".")[-1].endswith(("Exception", "Error")) for b in bases):
                flavor = "exception"
            elif any(b.split(".")[-1] in {"Enum", "IntEnum", "StrEnum"} for b in bases):
                flavor = "enum"
            facts["classes"].append({
                "name": node.name, "line": node.lineno, "bases": bases[:4], "methods": methods[:30],
                "doc": _first_doc_line(node), "flavor": flavor, "table": tablename, "columns": columns[:25],
            })
            if flavor in {"orm", "pydantic"}:
                facts["models"].append({"name": node.name, "kind": flavor, "table": tablename, "fields": columns[:25]})
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            callee = _dotted(node.value.func)
            last = callee.split(".")[-1]
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if last in {"FastAPI", "Flask", "Quart", "Sanic"} and targets:
                title = None
                for kw in node.value.keywords:
                    if kw.arg == "title":
                        title = _const_str(kw.value)
                facts["app_objects"].append({"name": targets[0], "framework": last, "title": title})
                facts["entry_signals"].append(f"{last.lower()}_app")
            elif last in {"APIRouter", "Blueprint"} and targets:
                prefix = ""
                for kw in node.value.keywords:
                    if kw.arg in {"prefix", "url_prefix"}:
                        prefix = _const_str(kw.value) or ""
                facts["router_prefixes"][targets[0]] = prefix
            elif last in _SESSION_FACTORIES:
                facts["db_usage"].append(f"{last}()")
        elif isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "__name__":
                facts["entry_signals"].append("dunder_main")

    # ---- whole-tree walks: calls, env vars, db usage, include_router, side effects ----
    calls: Dict[str, int] = {}
    env_vars = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # include_router / register_blueprint
            if isinstance(func, ast.Attribute) and func.attr in {"include_router", "register_blueprint"} and node.args:
                target = _dotted(node.args[0])
                prefix, prefix_expr = "", None
                for kw in node.keywords:
                    if kw.arg in {"prefix", "url_prefix"}:
                        prefix = _const_str(kw.value)
                        if prefix is None:  # e.g. settings.API_V1_STR: real value unknown statically
                            prefix, prefix_expr = "", redact_secrets(_unparse(kw.value))[:60]
                facts["include_routers"].append(
                    {"target": target, "prefix": prefix, "prefix_expr": prefix_expr, "line": node.lineno})
            # env access
            dotted = _dotted(func)
            if dotted in {"os.getenv", "os.environ.get", "getenv"} and node.args:
                name = _const_str(node.args[0])
                if name:
                    env_vars.add(name)
            # db session usage
            if isinstance(func, ast.Attribute) and func.attr in _DB_CALL_ATTRS:
                root = _attr_root(func)
                if root and root not in {"self"} and func.attr in {"query", "execute", "commit", "add", "add_all"}:
                    facts["db_usage"].append(f"{func.attr}()")
            # side effects
            if dotted == "open":
                facts["side_effects"].append("file I/O")
            elif dotted.startswith("subprocess."):
                facts["side_effects"].append("runs subprocesses")
            elif dotted.split(".")[0] in {"requests", "httpx", "urllib", "aiohttp"}:
                facts["side_effects"].append("makes outbound HTTP calls")
            # calls to imported names
            if isinstance(func, ast.Name) and func.id in bindings:
                calls.setdefault(func.id, node.lineno)
            elif isinstance(func, ast.Attribute):
                root = _attr_root(func)
                if root and root in bindings:
                    calls.setdefault(_dotted(func), node.lineno)
        elif isinstance(node, ast.Subscript):
            if _dotted(node.value) == "os.environ":
                sl = node.slice
                name = _const_str(sl)
                if name:
                    env_vars.add(name)
    facts["env_vars"] = sorted(env_vars)
    facts["calls"] = [{"name": n, "line": ln} for n, ln in sorted(calls.items(), key=lambda kv: kv[1])]
    facts["db_usage"] = sorted(set(facts["db_usage"]))
    facts["side_effects"] = sorted(set(facts["side_effects"]))
    if any(f["name"] == "get_db" for f in facts["functions"]) or any(
        isinstance(n, ast.Name) and n.id in {"get_db", "SessionLocal"} for n in ast.walk(tree)
    ):
        if "session management" not in facts["db_usage"] and any(
            u in facts["db_usage"] for u in ("sessionmaker()", "create_engine()")
        ):
            facts["db_usage"].append("session management")

    facts["exports"]["named"] = sorted(
        {f["name"] for f in facts["functions"] if not f["method"] and f["exported"]}
        | {c["name"] for c in facts["classes"] if not c["name"].startswith("_")}
    )
    facts["functions"].sort(key=lambda f: f["line"])
    return facts
