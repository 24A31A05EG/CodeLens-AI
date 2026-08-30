# CodeLens-AI
> AI-Driven Code Intelligence, Automated Documentation, Architecture Visualization & Codebase Q&A System

---

## 🏗️ Architecture

CodeLens AI consists of:
1. **Backend (`/backend`)**: FastAPI service with SQLite database, multi-language static parser, symbol extractor, chunking & semantic Q&A engine, Mermaid diagram generator, and documentation synthesizer.
2. **Frontend (`/frontend`)**: React + Vite application featuring an interactive dashboard, live code analysis with beginner/developer/technical explanation levels, automated documentation viewer, Mermaid architecture graphs, semantic Q&A, and project history.

---

## 🚀 Quick Start

### 1. Backend Setup & Run

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
- API Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health Check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### 2. Run Backend Tests

```bash
cd backend
python test_endpoints.py
```

### 3. Frontend Setup & Run

```bash
cd frontend
npm install
npm run dev
```
- Web Application: [http://localhost:5173](http://localhost:5173)

---

## 📡 API Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server health check |
| `POST` | `/upload` | Upload source file, `.zip` repo, or clone Git URL |
| `GET` | `/upload/{project_id}/status` | Check parsing & indexing status |
| `GET` | `/projects/{project_id}/structure` | Retrieve file tree, language stats & symbol counts |
| `POST` | `/explain` | Explain code at `beginner`, `developer`, or `technical` levels |
| `POST` | `/generate-docs` | Generate `readme` or `api_docs` Markdown |
| `POST` | `/generate-diagram` | Generate Mermaid flowchart of module dependencies |
| `POST` | `/ask` | Ask natural language questions with semantic code retrieval |
| `GET` | `/history` | List recently analyzed projects and counts |
| `GET` | `/history/{project_id}` | Detailed project history with stored artifacts & explanations |
