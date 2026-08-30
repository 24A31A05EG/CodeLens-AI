# CodeLens AI — Backend Service

FastAPI-powered intelligence backend for repository parsing, AI-driven code explanations, automated documentation generation, architecture visualization, semantic codebase Q&A, and analysis history.

---

## Features & Architecture

```
backend/
├── main.py                 # FastAPI application, CORS configuration, lifecycle hooks, route mounting
├── requirements.txt        # Backend dependencies
├── test_endpoints.py       # Comprehensive endpoint test suite (supports TestClient & live server)
├── db/
│   └── database.py         # SQLAlchemy engine, SessionLocal, init_db(), get_db()
├── models/
│   └── db_models.py        # SQLAlchemy schema: Project, ProjectFile, Explanation, GeneratedArtifact, Chunk
├── routers/
│   ├── upload.py           # Code & zip upload, GitHub clone, safety checks, background parsing job
│   ├── structure.py        # File hierarchy & language breakdown (/projects/{id}/structure)
│   ├── explain.py          # Multi-level code explanations with DB caching (/explain)
│   ├── docs.py             # README and API docs generation with DB caching (/generate-docs)
│   ├── diagram.py          # Mermaid architecture flowchart generation (/generate-diagram)
│   ├── ask.py              # Semantic code Q&A using chunk retrieval & embeddings (/ask)
│   └── history.py          # Analysis history and artifact logs (/history, /history/{id})
└── services/
    ├── parser.py           # Multi-language symbol extraction (.py, .js, .ts, .java, .cpp, etc.) & chunking
    └── ai_client.py        # AI integration boundary with built-in deterministic fallbacks
```

---

## API Endpoints Summary

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check endpoint |
| `POST` | `/upload` or `/projects` | Upload a code file, `.zip` archive, or Git clone URL |
| `GET` | `/upload/{project_id}/status` | Check project parsing status (`processing`, `ready`, `failed`) |
| `GET` | `/projects/{project_id}/structure` | Get project file tree, language stats, and symbol counts |
| `POST` | `/explain` | Explain individual files or entire project (`beginner`, `developer`, `technical`) |
| `POST` | `/generate-docs` | Generate structured `readme` or `api_docs` Markdown |
| `POST` | `/generate-diagram` | Generate Mermaid flowchart diagram of module dependencies |
| `POST` | `/ask` | Semantic "Ask Your Codebase" Q&A citing sources |
| `GET` | `/history` | List recently analyzed projects with summary counts |
| `GET` | `/history/{project_id}` | Detailed project history, saved explanations, and generated artifacts |

---

## Getting Started

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Run the Development Server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Interactive API documentation will be available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

### 3. Run Backend Test Suite

```bash
python test_endpoints.py
```
