"""
Tests for project-aware analysis: file-type extraction, relationship graph,
explanations, Ask Codebase, docs/diagram, secret handling and project isolation.

Fixtures are synthetic repositories from ``fixture_projects.py``.
"""

import io
import os
import tempfile
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from db.database import SessionLocal, init_db
from fixture_projects import FASTAPI_APP, REACT_THREE_APP, build_zip
from main import app
from models.db_models import Explanation, FileAnalysis, ProjectAnalysis, User
from services.analysis.docgen import _label, build_mermaid
from services.analysis.extract_js import extract_js_facts
from services.analysis.extractors import extract_file
from services.analysis.graph import api_call_path, build_graph, normalize_route_path
from services.analysis.pipeline import analyze_files
from services.analysis.redact import is_secret_file, redact_secrets
from services.parser import is_supported_file, walk_repo

OLD_GENERIC_PHRASE = "contains reusable project logic"


# ---------------------------------------------------------------- helpers
def _write_tree(files: dict) -> str:
    root = tempfile.mkdtemp(prefix="ci_fixture_")
    for path, content in files.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
    return root


def _analysis(files: dict, name: str = "proj"):
    return analyze_files(walk_repo(_write_tree(files)), name)


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


def _upload(client, files, name, root="", headers=None):
    buf = build_zip(files, root=root)
    r = client.post("/upload", files={"file": (f"{name}.zip", buf, "application/zip")}, headers=headers or {})
    assert r.status_code == 201, r.text
    pid = r.json()["project_id"]
    for _ in range(40):
        st = client.get(f"/upload/{pid}/status", headers=headers or {}).json()["status"]
        if st == "ready":
            return pid
        assert st != "failed", "parse failed"
        time.sleep(0.25)
    raise AssertionError("project never became ready")


@pytest.fixture(scope="module")
def react_pid(client):
    return _upload(client, REACT_THREE_APP, "holo-core", root="holo-core")


@pytest.fixture(scope="module")
def api_pid(client):
    return _upload(client, FASTAPI_APP, "inventory", root="inventory")


def _explain(client, pid, path, level="developer"):
    r = client.post("/explain", json={"project_id": pid, "file_path": path, "level": level})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- parser / ingestion
def test_ingestion_rules():
    assert is_supported_file("requirements.txt") and is_supported_file("Dockerfile")
    assert not is_supported_file("notes.txt")  # arbitrary .txt stays unsupported
    assert not is_supported_file(".env") and not is_secret_file("src/app.py")
    assert is_secret_file("config/.env.production") and is_secret_file("deploy/id_rsa")
    parsed = {p["path"] for p in walk_repo(_write_tree(FASTAPI_APP | REACT_THREE_APP))}
    assert ".env" not in parsed  # secret file never ingested
    assert "package-lock.json" not in parsed  # generated lock file skipped
    assert "requirements.txt" in parsed and "Dockerfile" in parsed


def test_redaction_patterns():
    text = 'API_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"\npassword = "hunter2-hardcoded"\nurl="postgresql://admin:pw123@db/x"'
    out = redact_secrets(text)
    assert "hunter2" not in out and "ghp_" not in out and "pw123" not in out
    assert "[REDACTED]" in out
    assert redact_secrets("count = 5") == "count = 5"


# ---------------------------------------------------------------- extraction
def test_js_component_facts():
    f = extract_js_facts(REACT_THREE_APP["src/3d/EnergyCore.jsx"], "src/3d/EnergyCore.jsx", "JavaScript")
    assert f["components"] == ["EnergyCore"]
    assert f["exports"]["default"] == "EnergyCore"
    assert {"useFrame", "useMemo", "useRef"} <= set(f["hooks_used"])
    assert "Color" in f["three_classes"]
    assert f["props"]["EnergyCore"] == ["intensity", "color"]
    assert "icosahedronGeometry" in f["jsx"]["intrinsic"]


def test_js_hook_definition_not_counted_as_use():
    f = extract_js_facts(REACT_THREE_APP["src/hooks/useScrollProgress.js"], "src/hooks/useScrollProgress.js", "JavaScript")
    assert f["custom_hooks"] == ["useScrollProgress"]
    assert "useScrollProgress" not in f["hooks_used"]


def test_js_ignores_imports_in_strings_and_comments():
    src = "// import Ghost from './ghost'\nconst s = \"import Fake from './fake'\"\nimport Real from './real'\n"
    f = extract_js_facts(src, "a.js", "JavaScript")
    assert [i["source"] for i in f["imports"]] == ["./real"]


def test_file_kinds():
    a = _analysis(REACT_THREE_APP)
    kinds = {p: f["kind"] for p, f in a["files"].items()}
    assert kinds["src/3d/EnergyCore.jsx"] == "component"
    assert kinds["src/hooks/useScrollProgress.js"] == "hook"
    assert kinds["package.json"] == "package_manifest"
    assert kinds["vite.config.js"] == "build_config"
    assert kinds["eslint.config.js"] == "lint_config"
    assert kinds["src/index.css"] == "stylesheet"
    assert kinds["index.html"] == "markup"
    assert kinds["README.md"] == "documentation"
    b = _analysis(FASTAPI_APP)
    kinds = {p: f["kind"] for p, f in b["files"].items()}
    assert kinds["app/routers/items.py"] == "api_router"
    assert kinds["app/main.py"] == "app_setup"  # creates the app AND has a route
    assert kinds["app/models.py"] == "data_model"
    assert kinds["app/db.py"] == "database"
    assert kinds["requirements.txt"] == "dependency_list"
    assert kinds["Dockerfile"] == "container"
    assert kinds["tests/test_pricing.py"] == "test"


# ---------------------------------------------------------------- graph
def _edge(graph, src, dst):
    return next((e for e in graph["edges"] if e["source"] == src and e["target"] == dst), None)


def test_graph_react_relationships():
    g = _analysis(REACT_THREE_APP)["graph"]
    assert [e["path"] for e in g["entry_points"]] == ["src/main.jsx"]
    assert "renders" in _edge(g, "src/3d/Scene.jsx", "src/3d/EnergyCore.jsx")["kinds"]
    assert "renders" in _edge(g, "src/App.jsx", "src/3d/Scene.jsx")["kinds"]
    assert "loads" in _edge(g, "index.html", "src/main.jsx")["kinds"]
    assert "styles" in _edge(g, "src/main.jsx", "src/index.css")["kinds"]
    assert _edge(g, "src/3d/EnergyCore.jsx", "src/utils/math.js")["confidence"] == "extracted"
    assert g["nodes"]["src/3d/EnergyCore.jsx"]["depth"] == 3


def test_graph_python_endpoints_and_mounts():
    g = _analysis(FASTAPI_APP)["graph"]
    ids = {e["id"] for e in g["endpoints"]}
    assert ids == {"GET /health", "GET /items", "GET /items/{item_id}/discounted"}  # prefix resolved
    assert "mounts" in _edge(g, "app/main.py", "app/routers/items.py")["kinds"]
    assert "calls" in _edge(g, "app/routers/items.py", "app/services/pricing.py")["kinds"]
    assert [e["path"] for e in g["entry_points"]] == ["app/main.py"]


def test_api_consumption_is_inferred_and_matched():
    files = {
        "frontend/package.json": '{"name":"fe","dependencies":{"react":"18"}}',
        "frontend/src/App.jsx": "const API = 'http://x'\nexport default function App(){ fetch(`${API}/items/${id}/discounted`); fetch(`${API}/nothing/here`); return <div/> }\n",
        **{f"backend/{k}": v for k, v in FASTAPI_APP.items() if not k.startswith(".env")},
    }
    g = _analysis(files)["graph"]
    consumers = g["consumers"]
    assert [c["endpoint"] for c in consumers] == ["GET /items/{item_id}/discounted"]  # unmatched URL ignored
    e = _edge(g, "frontend/src/App.jsx", "backend/app/routers/items.py")
    assert e["type"] == "calls_api" and e["confidence"] == "inferred"


def test_path_helpers():
    assert normalize_route_path("/a/{id}/b/:x") == "/a/{}/b/{}"
    assert api_call_path("`${API_BASE}/upload/${id}/status`") == "/upload/{}/status"
    assert api_call_path("'https://h.io/api/x?y=1'") == "/api/x"


# ---------------------------------------------------------------- context
def test_project_context():
    ctx = _analysis(REACT_THREE_APP, "holo-core")["context"]
    assert "React" in ctx["project_type"] and "Vite" in ctx["project_type"]
    assert ctx["main_application"] == "src/App.jsx"
    assert {"Three.js", "React Three Fiber", "GSAP"} <= {t["name"] for t in ctx["technologies"]}
    assert any(s["label"] == "3D visualization" and s["path"] == "src/3d" for s in ctx["subsystems"])
    assert ctx["architecture"]["startup_chains"][0][:3] == ["index.html", "src/main.jsx", "src/App.jsx"]
    cmds = {c["command"]: c["source"] for b in ctx["commands"].values() for c in b}
    assert "npm run dev" in cmds and "scripts.dev" in cmds["npm run dev"]
    api = _analysis(FASTAPI_APP, "inv")["context"]
    assert any(c["command"] == "uvicorn app.main:app --reload" for c in api["commands"]["run"])


def test_fullstack_project_type():
    files = {
        "frontend/package.json": '{"name":"fe","dependencies":{"react":"18"},"devDependencies":{"vite":"5"}}',
        "frontend/index.html": '<div id="root"></div><script type="module" src="/src/main.jsx"></script>',
        "frontend/src/main.jsx": "import {createRoot} from 'react-dom/client'\ncreateRoot(document.getElementById('root')).render(<div/>)\n",
        **{f"backend/{k}": v for k, v in FASTAPI_APP.items() if not k.startswith(".env")},
    }
    ctx = _analysis(files, "fs")["context"]
    assert ctx["project_type"].startswith("Full-stack application")
    assert {p["role"] for p in ctx["parts"]} >= {"frontend", "backend"}


# ---------------------------------------------------------------- explanations via API
def test_explanations_are_file_specific_and_not_generic(client, react_pid):
    energy = _explain(client, react_pid, "holo-core/src/3d/EnergyCore.jsx")
    navbar = _explain(client, react_pid, "holo-core/src/components/Navbar.jsx")
    text = energy["explanation"]
    assert OLD_GENERIC_PHRASE not in text and OLD_GENERIC_PHRASE not in navbar["explanation"]
    for needle in ("EnergyCore", "useFrame", "Three.js", "Scene.jsx", "src/main.jsx"):
        assert needle in text, needle
    assert "Navbar" in navbar["explanation"] and "useState" in navbar["explanation"]
    assert "EnergyCore" not in navbar["explanation"]
    assert energy["source"] == "static-analysis"
    rel = energy["analysis"]
    assert rel["kind"] == "component"
    assert [u["path"] for u in rel["used_by"]] == ["holo-core/src/3d/Scene.jsx"]
    assert "holo-core/src/utils/math.js" in [d["path"] for d in rel["depends_on"]]


def test_levels_differ_in_content(client, react_pid):
    p = "holo-core/src/3d/EnergyCore.jsx"
    b = _explain(client, react_pid, p, "beginner")["explanation"]
    d = _explain(client, react_pid, p, "developer")["explanation"]
    t = _explain(client, react_pid, p, "technical")["explanation"]
    assert len({b, d, t}) == 3
    assert len(b) < len(d) < len(t)
    assert "useFrame" in t and "Relationship evidence" in t and "Extraction confidence" in t
    assert "Relationship evidence" not in b and "Relationship evidence" not in d
    assert "hook" not in b.lower()  # beginner avoids jargon


def test_config_and_style_files_explained_by_content(client, react_pid):
    vite = _explain(client, react_pid, "holo-core/vite.config.js")["explanation"]
    assert "Vite" in vite and "react" in vite
    css = _explain(client, react_pid, "holo-core/src/index.css")["explanation"]
    assert "--bg" in css and "pulse" in css
    pkg = _explain(client, react_pid, "holo-core/package.json")["explanation"]
    assert "npm scripts" in pkg and "Three.js" in pkg and "`dev` → `vite`" in pkg


def test_python_explanations(client, api_pid):
    r = _explain(client, api_pid, "inventory/app/routers/items.py")["explanation"]
    assert "GET /items/{item_id}/discounted" in r and "list_items" in r
    assert "inventory/app/main.py" in r and "inventory/app/services/pricing.py" in r
    m = _explain(client, api_pid, "inventory/app/models.py")["explanation"]
    assert "items" in m and "price" in m


# ---------------------------------------------------------------- secrets
def test_secrets_never_leak(client, api_pid):
    secrets = ["hunter2", "ghp_abcdefghij", "super-secret-value", "admin:hunter2pass"]
    blobs = []
    struct = client.get(f"/projects/{api_pid}/structure").json()
    assert all(".env" not in f["path"] for f in struct["files"])
    for f in struct["files"]:
        for lvl in ("beginner", "developer", "technical"):
            blobs.append(_explain(client, api_pid, f["path"], lvl)["explanation"])
    for kind in ("readme", "api_docs"):
        blobs.append(client.post("/generate-docs", json={"project_id": api_pid, "kind": kind}).json()["content"])
    blobs.append(client.post("/generate-diagram", json={"project_id": api_pid}).json()["mermaid"])
    blobs.append(client.get(f"/projects/{api_pid}/overview").text)
    blobs.append(client.post("/ask", json={"project_id": api_pid, "question": "what is the api token and password?"}).text)
    for blob in blobs:
        for s in secrets:
            assert s not in blob, s
    # ...and files skipped at ingestion cannot be explained even though they exist on disk
    r = client.post("/explain", json={"project_id": api_pid, "file_path": "inventory/.env"})
    assert r.status_code == 404


def test_chunks_are_redacted(client, api_pid):
    db = SessionLocal()
    try:
        from models.db_models import Chunk
        text = " ".join(c.chunk_text for c in db.query(Chunk).filter(Chunk.project_id == api_pid))
    finally:
        db.close()
    assert "hunter2-hardcoded" not in text and "ghp_abcdefghij" not in text
    assert "DATABASE_URL" in text  # the env var NAME is kept, only values are scrubbed


# ---------------------------------------------------------------- overview / graph endpoints
def test_overview_and_graph_endpoints(client, react_pid):
    ov = client.get(f"/projects/{react_pid}/overview").json()
    assert "React" in ov["project_type"] and ov["main_application"] == "holo-core/src/App.jsx"
    assert ov["entry_points"][0]["path"] == "holo-core/src/main.jsx"
    g = client.get(f"/projects/{react_pid}/graph").json()
    assert g["stats"]["entry_points"] == 1 and any(e["type"] == "renders" for e in g["edges"])
    s = client.get(f"/projects/{react_pid}/structure").json()
    assert s["analysis_available"] and any(f.get("kind") == "component" for f in s["files"])


# ---------------------------------------------------------------- ask
def _ask(client, pid, q):
    r = client.post("/ask", json={"project_id": pid, "question": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_ask_startup_traces_real_path(client, react_pid):
    r = _ask(client, react_pid, "How does the application start?")
    assert r["intent"] == "startup"
    path_line = next(l for l in r["answer"].splitlines() if l.startswith("Startup path:"))
    assert path_line.index("index.html") < path_line.index("main.jsx") < path_line.index("App.jsx") < path_line.index("Scene.jsx")
    assert {"holo-core/src/main.jsx", "holo-core/src/App.jsx"} <= {s["file_path"] for s in r["sources"]}


def test_ask_locates_3d_files(client, react_pid):
    r = _ask(client, react_pid, "Which files are responsible for the 3D scene?")
    top = [s["file_path"] for s in r["sources"]]
    assert top[0] == "holo-core/src/3d/Scene.jsx"
    assert {"EnergyCore", "HolographicRings", "Particles"} <= {n for n in ("EnergyCore", "HolographicRings", "Particles") if any(n in p for p in top)}
    assert all(s["reason"] for s in r["sources"])
    assert not any("Navbar" in p for p in top)


def test_ask_dependencies_and_stack_and_api(client, react_pid, api_pid):
    r = _ask(client, react_pid, "What uses EnergyCore?")
    assert "holo-core/src/3d/Scene.jsx" in r["answer"]
    r = _ask(client, react_pid, "What technologies does this project use?")
    assert "Three.js" in r["answer"] and "GSAP" in r["answer"]
    r = _ask(client, api_pid, "What API endpoints exist?")
    assert "GET /items/{item_id}/discounted" in r["answer"]


def test_ask_unrelated_question_is_honest(client, react_pid):
    r = _ask(client, react_pid, "how do I bake a sourdough cake")
    assert r["sources"] == [] and "couldn't find" in r["answer"]


# ---------------------------------------------------------------- docs / diagram
def test_docs_reflect_project(client, react_pid, api_pid):
    readme = client.post("/generate-docs", json={"project_id": react_pid, "kind": "readme"}).json()["content"]
    for needle in ("## Technology stack", "Three.js", "## Architecture", "npm run dev", "3D visualization", "src/main.jsx"):
        assert needle in readme, needle
    api = client.post("/generate-docs", json={"project_id": api_pid, "kind": "api_docs"}).json()["content"]
    assert "GET /items/{item_id}/discounted" in api and "apply_discount(price, percent)" in api


def test_diagram_reflects_structure(client, react_pid):
    d = client.post("/generate-diagram", json={"project_id": react_pid, "force_regenerate": True}).json()
    m = d["mermaid"]
    assert m.startswith("graph TD") and "subgraph" in m and "renders" in m
    assert "EnergyCore.jsx" in m and "HolographicRings.jsx" in m and "Particles.jsx" in m
    tree = d["tree"][0]
    assert tree["path"] == "holo-core/src/main.jsx"
    assert tree["children"][0]["path"] == "holo-core/src/App.jsx"


def test_mermaid_label_sanitised():
    assert '"' not in _label('evil"]; click x call alert(1)') and "]" not in _label("a]b[c")


# ---------------------------------------------------------------- isolation
def test_project_isolation(client, react_pid, api_pid):
    # Ask about the other project's concepts: nothing from it may appear.
    r = _ask(client, react_pid, "Where is the database session and items endpoint?")
    assert all(s["file_path"].startswith("holo-core/") for s in r["sources"])
    assert "inventory" not in r["answer"].lower()
    r = _ask(client, api_pid, "Which files are responsible for the 3D scene EnergyCore?")
    assert all(s["file_path"].startswith("inventory/") for s in r["sources"])
    assert "EnergyCore" not in r["answer"].replace("EnergyCore?", "")
    ov_a = client.get(f"/projects/{react_pid}/overview").json()
    ov_b = client.get(f"/projects/{api_pid}/overview").json()
    assert ov_a["name"] != ov_b["name"] and not ({t["name"] for t in ov_a["technologies"]} & {"FastAPI", "SQLAlchemy"})
    # a file of project A cannot be explained through project B
    r = client.post("/explain", json={"project_id": api_pid, "file_path": "holo-core/src/App.jsx"})
    assert r.status_code == 404
    db = SessionLocal()
    try:
        paths_a = {f.path for f in db.query(FileAnalysis).filter(FileAnalysis.project_id == react_pid)}
        assert paths_a and all(p.startswith("holo-core/") for p in paths_a)
    finally:
        db.close()


def test_new_endpoints_enforce_ownership(client):
    init_db()
    db = SessionLocal()
    try:
        for name in ("owner_x", "other_x"):
            if not db.query(User).filter(User.username == name).first():
                db.add(User(username=name, email=f"{name}@example.test"))
        db.commit()
    finally:
        db.close()
    owner, other = {"X-CodeLens-User": "owner_x"}, {"X-CodeLens-User": "other_x"}
    pid = _upload(client, REACT_THREE_APP, "own", headers=owner)
    for path in ("overview", "graph", "structure"):
        assert client.get(f"/projects/{pid}/{path}", headers=owner).status_code == 200
        assert client.get(f"/projects/{pid}/{path}", headers=other).status_code == 404
    assert client.post("/ask", json={"project_id": pid, "question": "start?"}, headers=other).status_code == 404


# ---------------------------------------------------------------- cache & lazy rebuild
def test_stale_generic_cache_is_replaced(client, react_pid):
    path = "holo-core/src/utils/math.js"
    db = SessionLocal()
    try:
        db.add(Explanation(project_id=react_pid, file_path=path, level="beginner",
                           content=f"old {OLD_GENERIC_PHRASE}", created_at=datetime.utcnow() - timedelta(days=30)))
        db.commit()
    finally:
        db.close()
    r = _explain(client, react_pid, path, "beginner")
    assert OLD_GENERIC_PHRASE not in r["explanation"] and r["cached"] is False
    again = _explain(client, react_pid, path, "beginner")
    assert again["cached"] is True and again["explanation"] == r["explanation"]


def test_analysis_rebuilt_lazily_for_legacy_projects(client, react_pid):
    db = SessionLocal()
    try:
        db.query(FileAnalysis).filter(FileAnalysis.project_id == react_pid).delete()
        db.query(ProjectAnalysis).filter(ProjectAnalysis.project_id == react_pid).delete()
        db.commit()
    finally:
        db.close()
    ov = client.get(f"/projects/{react_pid}/overview")
    assert ov.status_code == 200 and "React" in ov.json()["project_type"]


def test_analysis_failure_does_not_break_extraction():
    root = _write_tree({"broken.py": "def x(:\n  pass", "ok.py": "def y():\n    return 1\n", "bad.json": "{nope"})
    a = analyze_files(walk_repo(root), "p")
    assert "ok.py" in a["files"] and a["files"]["broken.py"]["confidence"] == "low"


# ---------------------------------------------------------------- regressions found on a real repository
def test_utf8_bom_files_are_parsed_normally():
    root = _write_tree({})
    with open(os.path.join(root, "bom.py"), "wb") as fh:
        fh.write(b"\xef\xbb\xbfdef hello():\n    return 1\n")
    a = analyze_files(walk_repo(root), "p")
    assert a["files"]["bom.py"]["confidence"] == "high"
    assert [f["name"] for f in a["files"]["bom.py"]["functions"]] == ["hello"]


def test_test_modules_are_not_entry_points():
    files = {"app/main.py": FASTAPI_APP["app/main.py"], "tests/test_x.py": "def test_a():\n    pass\n\nif __name__ == '__main__':\n    test_a()\n"}
    g = _analysis(files)["graph"]
    assert [e["path"] for e in g["entry_points"]] == ["app/main.py"]


def test_class_not_listed_twice_for_models(client, api_pid):
    text = _explain(client, api_pid, "inventory/app/models.py")["explanation"]
    assert text.count("`Item`") >= 1 and "Defines class `Item`" not in text


# ---------------------------------------------------------------- regressions found on a third-party repo
def test_pep758_except_syntax_still_parses_with_ast():
    src = "try:\n    pass\nexcept ValueError, KeyError:\n    pass\n\ndef f():\n    return 1\n"
    from services.analysis.extract_py import extract_python_facts
    f = extract_python_facts(src, "x.py")
    assert f is not None and f["confidence"] == "high" and [x["name"] for x in f["functions"]] == ["f"]


def test_short_generated_barrel_file_is_not_treated_as_minified():
    long_line = "export { " + ", ".join(f"Name{i}" for i in range(120)) + " } from './sdk';\n"
    root = _write_tree({"index.ts": "// auto-generated\n" + long_line})
    a = analyze_files(walk_repo(root), "p")
    assert a["files"]["index.ts"]["confidence"] != "low" and a["files"]["index.ts"]["imports"]


def test_main_application_ignores_wrappers_and_is_never_guessed():
    wrap = {
        "package.json": '{"name":"w","dependencies":{"react":"18"}}',
        "src/main.jsx": "import {createRoot} from 'react-dom/client'\nimport Theme from './Theme'\nimport Toaster from './Toaster'\n"
                        "createRoot(document.getElementById('root')).render(<Theme><Toaster/></Theme>)\n",
        "src/Theme.jsx": "export default function ThemeProvider({children}){ return <div>{children}</div> }\n",
        "src/Toaster.jsx": "export default function Toaster(){ return <div/> }\n",
    }
    assert _analysis(wrap)["context"]["main_application"] in (None, "src/main.jsx")
    assert _analysis(wrap)["context"]["main_application"] != "src/Toaster.jsx"
    assert _analysis(REACT_THREE_APP)["context"]["main_application"] == "src/App.jsx"
    two = {"backend/app/main.py": FASTAPI_APP["app/main.py"], "backend/requirements.txt": "fastapi\n",
           "frontend/package.json": wrap["package.json"], "frontend/src/main.jsx": wrap["src/main.jsx"]}
    assert _analysis(two)["context"]["main_application"] is None  # ambiguous in a full-stack repo


def test_ui_routes_folder_is_not_an_api_and_word_forms_match():
    files = {
        "package.json": '{"name":"w","dependencies":{"react":"18"}}',
        "src/routes/Home.jsx": "export default function Home(){ return <div/> }\n",
        "src/routes/About.jsx": "export default function About(){ return <div/> }\n",
        "src/hooks/useAuth.js": "import {useState} from 'react'\nexport default function useAuth(){ const [user]=useState(null); return user }\n",
        "src/pages/login.jsx": "export default function Login(){ return <form/> }\n",
    }
    a = _analysis(files)
    assert a["graph"]["nodes"]["src/routes/Home.jsx"]["subsystem"] == "Pages / screens"
    assert any(s["path"] == "src/routes" and s["label"] == "Pages / screens" for s in a["context"]["subsystems"])
    from services.analysis.retrieval import answer_question
    r = answer_question(a, [(p, "x") for p in a["files"]], "Which files handle authentication?")
    assert "src/hooks/useAuth.js" in [s["file_path"] for s in r["sources"]]


def test_non_literal_router_prefix_is_flagged_not_hidden(client):
    files = {
        "app/api.py": "from fastapi import APIRouter\nrouter = APIRouter()\n\n@router.get('/items')\ndef items():\n    return []\n",
        "app/main.py": "from fastapi import FastAPI\nfrom app import api\nfrom app.config import settings\n\n"
                       "app = FastAPI()\napp.include_router(api.router, prefix=settings.API_V1_STR)\n",
        "app/config.py": "class S:\n    API_V1_STR = '/api/v1'\nsettings = S()\n",
        "app/__init__.py": "",
    }
    a = _analysis(files)
    ep = a["graph"]["endpoints"][0]
    assert ep["path"] == "/items" and ep["prefix_expr"] == "settings.API_V1_STR"
    from services.analysis.docgen import generate_api_docs, generate_readme
    from services.analysis.retrieval import answer_question
    assert "settings.API_V1_STR" in generate_api_docs(a) and "settings.API_V1_STR" in generate_readme(a)
    assert "settings.API_V1_STR" in answer_question(a, [(p, "x") for p in a["files"]], "What API endpoints exist?")["answer"]
