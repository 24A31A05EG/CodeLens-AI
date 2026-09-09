# CodeLens-AI Development Instructions

## 1. Project Overview

CodeLens-AI is an existing code-intelligence application with a React/Vite frontend and a Python/FastAPI backend. It accepts source files, ZIP archives, and supported public Git repository URLs, then parses the project and exposes explanations, generated documentation, dependency diagrams, codebase Q&A, and analysis history.

The active product is split between `backend/` and `frontend/`. `code-intelligence/` is a separate, lightweight prototype service and is not currently mounted or called by the backend.

Read the repository documentation before making broad changes:

- [Root README](README.md)
- [Backend README](backend/README.md)
- [Frontend README](frontend/README.md)

## 2. Core Purpose

The core purpose is to help developers understand an uploaded codebase through:

- Static file, symbol, and import analysis
- Multi-level code explanations
- Generated README and API-documentation artifacts
- Mermaid module-dependency output
- Natural-language questions over indexed code chunks
- Persistent project history and audit records

Do not describe deterministic fallback output as production LLM output. The current application is useful without a model provider, but the real WatsonX/IBM Bob call remains a placeholder.

## 3. Current Frontend Architecture

The frontend is a Vite application using React 19 and plain JSX/CSS.

- `frontend/src/main.jsx` mounts the application.
- `frontend/src/App.jsx` contains the main application state, navigation, upload flow, polling, API calls, and page rendering in one component.
- `frontend/src/App.css` contains the product UI styles.
- `frontend/src/index.css` contains global/template styles.
- `frontend/vite.config.js` configures the React Vite plugin.
- `frontend/package.json` defines the dev, build, lint, and preview commands.

The UI uses direct `fetch` calls. There is no client router, frontend API client module, Markdown renderer, Mermaid renderer, or frontend test suite currently present. The architecture screen currently displays Mermaid source text rather than rendering a graph.

Use the existing state and API patterns when making focused changes. Avoid introducing a new frontend framework or state library unless the task explicitly requires it.

## 4. Current Backend Architecture

The active backend is a FastAPI application started from `backend/main.py`.

- `backend/main.py` creates the app, initializes database tables in the lifespan hook, configures CORS, exposes `/health`, and mounts routers.
- `backend/db/database.py` creates the SQLAlchemy engine and sessions from `DATABASE_URL`.
- `backend/models/db_models.py` defines the SQLAlchemy tables.
- `backend/routers/` owns HTTP request validation, status guards, persistence coordination, and response shapes.
- `backend/services/parser.py` owns file walking, language detection, symbol/import extraction, and chunking.
- `backend/services/ai_client.py` is the generation and embedding boundary.
- `backend/services/audit.py` persists audit records.
- `backend/services/user_service.py` currently supplies one default demo user.

Keep route-specific behavior in the corresponding router and shared analysis/generation behavior in services. Preserve the existing public endpoint paths and response shapes unless the task explicitly includes an API change.

## 5. Current Data Flow

1. The frontend submits a file or `github_url` to `POST /upload`.
2. The backend validates the request, creates a `Project` with `processing` status, and stores or clones the source under a project-specific directory.
3. A FastAPI background task runs `parse_project`.
4. Supported files become `ProjectFile` rows with language, symbols, and imports.
5. Each file is chunked and each chunk receives a deterministic local embedding; chunks are stored in `Chunk` rows.
6. The project becomes `ready` or `failed`.
7. The frontend polls `/upload/{project_id}/status` and then loads `/projects/{project_id}/structure`.
8. Explanation requests read source files and cache results in `Explanation`.
9. Documentation and diagram requests build summaries from persisted file metadata and cache results in `GeneratedArtifact`.
10. Q&A embeds the question, ranks stored chunks using in-process cosine similarity, and returns an answer plus source paths.
11. Uploads and generation actions write `AuditLog` records.

## 6. Important Directories and Files

### Active backend

- `backend/main.py`: FastAPI entry point and router registration.
- `backend/requirements.txt`: Python dependencies.
- `backend/test_endpoints.py`: Existing endpoint smoke test.
- `backend/routers/upload.py`: file/ZIP/repository ingestion and status endpoints.
- `backend/routers/structure.py`: project file and language summary.
- `backend/routers/explain.py`: cached single-file and project-wide explanations.
- `backend/routers/docs.py`: README and API-documentation artifact generation.
- `backend/routers/diagram.py`: Mermaid dependency artifact generation.
- `backend/routers/ask.py`: chunk retrieval and codebase Q&A.
- `backend/routers/history.py`: project and artifact history.
- `backend/routers/audit.py`: audit-log endpoint mounted by the application.
- `backend/services/parser.py`: active parser and chunker.
- `backend/services/ai_client.py`: deterministic generation/embedding fallbacks and model boundary.
- `backend/db/database.py`: engine, sessions, and table initialization.
- `backend/models/db_models.py`: `User`, `Project`, `ProjectFile`, `Explanation`, `GeneratedArtifact`, `Chunk`, and `AuditLog` models.

`backend/audit.py` is a duplicate-looking router module and is not the router imported by `backend/main.py`; do not assume it is active without checking imports.

### Frontend

- `frontend/src/App.jsx`: current feature UI and API orchestration.
- `frontend/src/App.css`: application styling.
- `frontend/src/index.css`: global styles.
- `frontend/package.json`: scripts and dependencies.

### Separate prototype

- `code-intelligence/main.py`: standalone `/` health endpoint and `/analyze` path scanner.
- `code-intelligence/analyzer/scanner.py`: prototype supported-extension scanner.
- `code-intelligence/analyzer/parser.py`: prototype Python AST parser.
- `code-intelligence/analyzer/chunker.py`: prototype fixed-size chunker.
- `code-intelligence/ai/engine.py` and `ai/prompts.py`: prompt construction only; no model call.
- `code-intelligence/generators/`: simple documentation and Mermaid string generators.

The `code-intelligence` README and schemas file are empty. Do not treat this prototype as an integrated subsystem.

## 7. API and Router Responsibilities

`backend/main.py` mounts these active routes:

- `GET /health`: service health response.
- `POST /upload` and hidden alias `POST /projects`: accept a source file, ZIP, or allowed Git URL.
- `GET /upload/{project_id}/status`: return processing status.
- `GET /projects/{project_id}/structure`: return file count, language counts, and file symbol counts.
- `POST /explain`: explain one file or all parsed files at beginner, developer, or technical level.
- `POST /generate-docs`: generate or retrieve `readme` or `api_docs` artifacts.
- `POST /generate-diagram`: generate or retrieve a Mermaid dependency diagram.
- `POST /ask`: retrieve relevant chunks and answer a natural-language codebase question.
- `GET /history`: list recent projects or return one project when `project_id` is supplied.
- `GET /history/{project_id}`: return detailed project history.
- `GET /audit-logs`: return up to 100 audit records, optionally filtered by project.

Processing endpoints return a `202` response while a project is still being parsed and a `400` response for failed parsing. Preserve these status semantics when changing route behavior.

## 8. AI/LLM Integration Status

The runtime does not currently call IBM Bob or WatsonX. In `backend/services/ai_client.py`:

- `_call_model()` is a placeholder that returns `None`.
- `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, and `CODELENS_ENABLE_WATSONX` are read, but no SDK or REST invocation is wired.
- Explanations, README/API docs, Mermaid output, and Q&A use deterministic local fallback functions.
- `embed_text()` uses a synthetic 384-dimensional character-based embedding.

IBM Bob is a development-time coding tool for this repository, not a runtime dependency. Do not add IBM Bob runtime code, credentials, SDK setup, fake model calls, or claimed AI integration as part of ordinary development work.

## 9. Parsing and Retrieval Pipeline

The active parser in `backend/services/parser.py`:

- Walks the project while ignoring `.git`, `node_modules`, virtual environments, caches, build directories, and common editor directories.
- Detects files by extension using `EXT_TO_LANG`.
- Extracts symbols and imports using line-based prefix/regex-style logic.
- Chunks by detected symbol boundaries when possible; otherwise uses 60-line windows with 10-line overlap.

The active Q&A path in `backend/routers/ask.py`:

- Embeds the question with `embed_text()`.
- Loads all embedded chunks for the project.
- Computes cosine similarity in Python.
- Uses `ASK_TOP_K` (default `5`) and `ASK_SIMILARITY_THRESHOLD` (default `0.0`).
- Sends the top chunks to `answer_question()` and returns source paths and scores.

Do not claim that this is AST-complete parsing, production vector search, or semantic model retrieval. Those are potential future improvements, not current functionality.

## 10. Database Structure

SQLAlchemy models are declared in `backend/models/db_models.py`:

- `User`: currently supports the single default demo user.
- `Project`: project identity, user association, source, source reference, status, and creation time.
- `ProjectFile`: parsed file path, language, symbols, and imports.
- `Explanation`: cached explanation by project, file, and level.
- `GeneratedArtifact`: cached README, API-doc, or diagram content.
- `Chunk`: chunk text and JSON embedding for retrieval.
- `AuditLog`: action, optional user/project association, details, and timestamp.

Tables are created with `Base.metadata.create_all()` during application lifespan. There are no migrations in the repository. `DATABASE_URL` is mandatory; the README commonly uses SQLite for local execution, and `psycopg2-binary` is present for PostgreSQL connectivity. Do not assume a specific production database beyond the configured SQLAlchemy URL.

## 11. Frontend Development Conventions

- Follow the existing React/Vite setup and plain JSX style.
- Keep API calls consistent with the `API_BASE` value from `VITE_API_URL`.
- Preserve the current endpoint payloads and loading/error states when making UI changes.
- Keep upload polling behavior compatible with `processing`, `ready`, and `failed` statuses.
- Avoid adding dependencies when browser APIs and existing code are sufficient.
- Do not silently turn raw generated content into executable HTML or Mermaid without considering sanitization.
- Keep UI changes scoped; `App.jsx` is currently monolithic, so split components only when the requested change justifies it.

## 12. Backend Development Conventions

- Use the existing FastAPI router/service/model organization.
- Use SQLAlchemy sessions through `get_db()` and close resources reliably.
- Validate request models with Pydantic and preserve existing HTTP status behavior.
- Use project IDs and normalized relative paths when accessing stored project files.
- Keep generation and embedding provider logic behind `services/ai_client.py`.
- Preserve caching behavior unless cache invalidation is explicitly part of the task.
- Use the existing audit helper for actions that already record audit events.
- Keep changes minimal and avoid reformatting unrelated code.
- Run Python compile/import validation after backend changes.

## 13. Security Requirements

Treat uploaded repositories and source code as untrusted input.

- Do not weaken project-path containment checks.
- Do not expose arbitrary local filesystem paths.
- Do not remove upload size limits, decompressed ZIP limits, or allowed-extension checks.
- Do not broaden allowed clone URLs without validating the security implications.
- Do not expose source, history, or audit data to a user without an authorization decision; the current application has no real authentication, so this is a known limitation.
- Do not log source code, secrets, API keys, or full external responses.
- Treat generated Markdown, Mermaid, and model output as untrusted content before rendering.
- Preserve or improve resource limits for file count, disk use, clone time, decompression, and processing duration.
- Do not introduce shell command interpolation; repository cloning currently uses an argument list with `subprocess.run`.

## 14. File Upload and ZIP Security Rules

The current upload implementation must retain these protections:

- Read no more than `MAX_UPLOAD_BYTES + 1` bytes from an upload.
- Reject empty uploads and uploads over `MAX_UPLOAD_MB` (default `100`).
- Sanitize uploaded filenames and use only the basename for single-file storage.
- Accept only extensions in `backend/services/parser.py`, unless a deliberate feature change updates validation and parsing together.
- Detect ZIP payloads and reject invalid archives.
- Reject decompressed ZIP content over ten times the configured upload limit.
- Resolve every ZIP member against the project root and reject path traversal.
- Keep project files isolated under the per-project storage directory.
- Keep the Git URL allowlist limited to HTTPS GitHub, GitLab, and Bitbucket hosts unless security review supports a change.
- Preserve the 60-second Git clone timeout and inspect cleanup/resource behavior before changing it.

ZIP symlinks, special files, file-count limits, retention, and cleanup remain areas for future hardening.

## 15. Environment Variables and Configuration

Backend variables:

- `DATABASE_URL`: required SQLAlchemy connection URL.
- `ALLOWED_ORIGIN`: CORS origin; currently defaults to `*`.
- `CODELENS_STORAGE_ROOT`: extracted project storage root; defaults under the system temporary directory.
- `MAX_UPLOAD_MB`: upload limit in megabytes; defaults to `100`.
- `WATSONX_API_KEY`: read by the placeholder AI boundary only.
- `WATSONX_PROJECT_ID`: read by the placeholder AI boundary only.
- `CODELENS_ENABLE_WATSONX`: defaults to `0`; does not currently create a runtime model integration.
- `ASK_TOP_K`: number of retrieved chunks; defaults to `5`.
- `ASK_SIMILARITY_THRESHOLD`: retrieval threshold; defaults to `0.0`.

Frontend variable:

- `VITE_API_URL`: backend base URL; defaults to `http://127.0.0.1:8000`.

Never commit `.env` files, credentials, tokens, or real API keys. Use local environment variables or an untracked environment file. Update documentation when adding configuration, but do not include secret values.

## 16. Testing Commands

From `backend/`:

```powershell
pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./codelens.db"
python test_endpoints.py
```

The smoke test can use a running server via `CODELENS_BASE_URL`, or fall back to FastAPI `TestClient`. If using the local `TestClient` path, initialize the configured database schema first because application lifespan behavior can depend on the installed Starlette/httpx versions:

```powershell
python -c "from db.database import init_db; init_db()"
python test_endpoints.py
```

The smoke suite covers health, ZIP and single-file uploads, parsing/status, structure, explanations, documentation, diagrams, Q&A, history, invalid file types, missing projects, path traversal, and unsafe Git URLs.

From `frontend/`:

```powershell
npm install
npm run lint
npm run build
```

There is currently no dedicated frontend test suite. `code-intelligence/` has `tests/test_analyzer.py`, but it belongs to the separate prototype and is not the active backend integration test suite.

## 17. Development and Run Commands

Backend, from `backend/`:

```powershell
pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./codelens.db"
uvicorn main:app --reload --port 8000
```

Frontend, from `frontend/`:

```powershell
npm install
npm run dev
```

The frontend normally runs at `http://localhost:5173` and the backend at `http://127.0.0.1:8000`. FastAPI interactive docs are at `/docs`.

The separate `code-intelligence/` service has no maintained README or documented integration command. Treat it as prototype code and inspect its imports before attempting to run or connect it.

## 18. Rules for Modifying Existing Functionality

- Work from the existing implementation; do not rebuild the project or replace working layers with a new stack.
- Before editing, identify the owning router, service, model, or component and inspect nearby tests/callers.
- Make the smallest change that satisfies the request.
- Preserve endpoint names, request fields, response fields, status codes, storage layout, and cache semantics unless the task explicitly requires a contract change.
- Do not refactor unrelated files or fold the separate `code-intelligence` prototype into the active backend without an explicit integration task.
- Do not add placeholder functionality presented as complete functionality.
- Validate changed Python with compilation/import checks and run the relevant existing smoke/build/lint checks.
- Report pre-existing failures separately from regressions caused by a change.

## 19. Secrets and API Keys

- Never hardcode API keys, database credentials, Git credentials, or tokens.
- Never print secrets in logs, test output, generated documentation, prompts, or audit details.
- Do not send source code to an external model provider unless the provider integration, configuration, privacy expectations, and failure handling are explicitly approved.
- Keep provider credentials in environment variables or a managed secret store.
- Treat `WATSONX_API_KEY` and `WATSONX_PROJECT_ID` as sensitive even though the current runtime does not use them.
- Do not add IBM Bob credentials or IBM Bob runtime dependencies.

## 20. Instructions for Future AI Coding Agents

- Start by reading this file and the relevant README, then inspect the local owning code path.
- Confirm whether a requested feature already exists before implementing a parallel version.
- Distinguish active backend/frontend behavior from the unintegrated `code-intelligence` prototype.
- Treat the current deterministic AI behavior and synthetic embeddings as the implementation baseline.
- Check git status before editing and do not revert unrelated user changes.
- Do not modify application functionality during documentation or instruction-file tasks.
- For security-sensitive changes, preserve containment, validation, quotas, and untrusted-input handling.
- Keep IBM Bob as a development-time assistant only; it must never become a runtime dependency.
- After changes, run the narrowest useful executable validation first, then the relevant broader test or build.
- Summarize modified files, validation commands, failures, and any remaining risks in the final response.
