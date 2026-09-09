# CodeLens-AI Implementation Plan

## Scope and Baseline

This plan is for the existing CodeLens-AI repository. It does not rebuild the application, change application code, or add IBM Bob to the runtime.

The current baseline is:

- `backend/` is the active FastAPI application.
- `frontend/` is the active React/Vite application.
- `code-intelligence/` is a separate prototype and is not mounted or called by the active backend.
- Upload, ZIP extraction, Git URL cloning, background parsing, project structure, explanations, generated documentation, Mermaid output, Q&A, history, caching, and audit logging are already present.
- `backend/routers/explain.py` has the cached-result indentation fix.
- `backend/routers/docs.py` and `backend/routers/diagram.py` import the existing `log_action` helper.
- The backend smoke suite passed after those fixes.
- `backend/services/ai_client.py` still uses deterministic fallbacks. `_call_model()` is a placeholder; there is no runtime IBM Bob integration.

Proposed work below must preserve existing endpoint contracts and working fallback behavior unless a phase explicitly calls for a reviewed API change.

## Priority Summary

| Priority | Improvement | Primary reason |
|---|---|---|
| P0 | Establish project ownership and authorization | Current project, history, and audit access is not user-isolated. |
| P0 | Add regression tests and deterministic test setup | The existing smoke test depends on runtime/database setup and has limited unit coverage. |
| P0 | Harden upload, ZIP, clone, and storage limits | Uploaded repositories are untrusted and can consume filesystem or process resources. |
| P1 | Centralize validation and error handling | Validation and failure responses are distributed across routers and background tasks. |
| P1 | Integrate a real model provider behind the existing boundary | Current explanations and Q&A are deterministic placeholders, not LLM output. |
| P1 | Improve parsing and retrieval quality | Current extraction is mostly line based and embeddings are synthetic. |
| P2 | Improve documentation and architecture artifacts | Current docs are symbol summaries and diagrams are import heuristics. |
| P2 | Make the frontend maintainable and more usable | Most UI/API orchestration lives in one large `App.jsx`. |
| P3 | Add production operations and deployment safeguards | Current database initialization, jobs, storage, and observability are demo-oriented. |

# Proposed Improvements

## 1. Security Hardening and Project Authorization

### Problem

The database has a `User` and `Project.user_id`, but the application always uses the default `codelens_demo` user. Project, history, and audit routes do not authenticate callers or enforce ownership. Any caller that knows a project ID can request its derived data, and `/audit-logs` is publicly accessible.

### Current implementation

- `backend/services/user_service.py` creates or reuses one default user.
- `backend/routers/upload.py` assigns all uploads to that user.
- `backend/routers/structure.py`, `explain.py`, `docs.py`, `diagram.py`, `ask.py`, and `history.py` query by project ID without an authorization dependency.
- `backend/routers/audit.py` returns audit entries without authentication.
- `backend/main.py` enables permissive development CORS by default with `ALLOWED_ORIGIN` defaulting to `*`.

### Proposed solution

Introduce an explicit authentication/identity boundary and a shared project-access dependency. Every project-scoped route should verify that the current principal owns or is allowed to access the project. Keep the current default user only as a clearly scoped local-development fallback, disabled or rejected in production configuration. Restrict audit-log access to authorized users and administrators. Replace wildcard CORS with an explicit configured origin list.

Do not choose or invent an authentication provider in this plan. First decide whether the project will use an existing identity proxy, signed tokens, or another approved mechanism, then keep the implementation behind a small dependency module.

### Files likely to change

- `backend/main.py`
- `backend/routers/upload.py`
- `backend/routers/structure.py`
- `backend/routers/explain.py`
- `backend/routers/docs.py`
- `backend/routers/diagram.py`
- `backend/routers/ask.py`
- `backend/routers/history.py`
- `backend/routers/audit.py`
- `backend/services/user_service.py`
- `backend/models/db_models.py`
- New authentication/access dependency module under `backend/` if needed
- `backend/.env` documentation or a new non-secret environment example

### Dependencies/configuration required

- An approved authentication mechanism and its Python dependencies, if any
- Configured allowed origins instead of `*`
- Production setting that disables the demo user fallback
- Possibly a migration path for existing `Project.user_id` values

### Security considerations

This is the primary security boundary. Avoid accepting user IDs from request bodies as proof of identity. Enforce access before reading source files or returning cached artifacts. Do not expose token values in logs or audit details. Use constant-time or library-provided token validation rather than custom cryptography.

### Testing strategy

Add tests for authenticated and unauthenticated requests, owner access, cross-user access denial, audit-log access, missing projects, and CORS behavior. Use two isolated users and two projects in a temporary database. Retain the current smoke-test flows using a documented local-development identity.

### Expected benefit

Prevents cross-project source and artifact disclosure and creates the foundation for safe multi-user operation.

### Risk of breaking existing functionality

High. Existing clients send only `project_id` and the backend creates a default user. Introduce the access layer compatibly for local development, update the frontend authentication contract only after the identity decision, and preserve response shapes where possible.

## 2. File Upload, Repository Isolation, and Resource Limits

### Problem

The upload path has useful filename, ZIP traversal, upload-size, decompressed-size, extension, and Git-host checks, but it lacks comprehensive file-count, per-project disk, symlink/special-file, retention, and concurrent-job limits. Extracted project directories remain on disk and clone/parsing work is performed in-process.

### Current implementation

- `backend/routers/upload.py` stores projects under `CODELENS_STORAGE_ROOT`.
- Uploads are limited by `MAX_UPLOAD_MB`, defaulting to 100 MB.
- ZIP decompressed size is limited to ten times the upload limit.
- ZIP member paths are checked with `realpath` and `commonpath` before extraction.
- Single-file names are sanitized.
- Git URLs are restricted to HTTPS GitHub, GitLab, and Bitbucket patterns.
- Git cloning uses `--depth 1` and a 60-second timeout.
- `backend/services/parser.py` ignores common dependency/build directories.

### Proposed solution

Add explicit limits for ZIP member count, individual extracted file size, total project disk usage, parser runtime, and concurrent jobs. Reject or safely handle symbolic links and special ZIP entries. Use a controlled extraction routine rather than relying only on `extractall`. Add cleanup on parse failure and an explicit project deletion/retention policy. Keep each project directory keyed by an opaque project ID and verify containment for every file operation.

### Files likely to change

- `backend/routers/upload.py`
- `backend/services/parser.py`
- `backend/models/db_models.py` if quota/status metadata is persisted
- `backend/routers/history.py` for deletion/retention behavior
- `backend/main.py` or a new job/storage service for lifecycle cleanup
- `backend/test_endpoints.py` and new upload security tests

### Dependencies/configuration required

- New documented limits such as maximum file count, extracted file size, project size, job duration, and retention period
- Possibly a filesystem quota or background cleanup mechanism
- No IBM Bob dependency

### Security considerations

Treat archive metadata, filenames, symlinks, and repository contents as hostile. Do not allow extraction outside the project root. Do not follow links into host paths. Avoid shell interpolation when invoking Git. Keep clone error output truncated and free of credentials.

### Testing strategy

Test traversal names, absolute paths, Windows-style separators, symlink entries, special entries, invalid archives, compression bombs, too many files, oversized files, clone timeout/failure, parser failure cleanup, and cross-project path access. Use temporary storage and assert that no files are created outside it.

### Expected benefit

Reduces arbitrary-file-write, denial-of-service, data-retention, and cross-project contamination risks while preserving current upload types.

### Risk of breaking existing functionality

Medium. New limits may reject repositories that currently parse. Make limits configurable, return explicit validation errors, and document defaults before enforcing stricter production values.

## 3. Input Validation and API Contract Discipline

### Problem

Some request validation is handled by Pydantic or manual checks, but project IDs, questions, file paths, generated content sizes, environment values, and query parameters do not have one consistent validation policy. A few routes duplicate status guards and database lookups.

### Current implementation

- `ExplainRequest` validates explanation levels with `Literal`.
- `DocsRequest` validates `readme` and `api_docs` kinds.
- Upload and Q&A routes manually validate empty values.
- File paths use realpath containment in `explain.py`.
- `ASK_TOP_K` and thresholds are parsed directly from environment variables.
- Response payloads are returned as untyped dictionaries.

### Proposed solution

Create shared Pydantic request/response schemas for project IDs, file paths, questions, artifact requests, status responses, and source metadata. Centralize project lookup/status guards and path normalization. Validate environment configuration at startup with useful messages and bounded numeric values. Add maximum question/prompt/context lengths before model calls. Preserve existing JSON fields while gradually improving OpenAPI schemas.

### Files likely to change

- `backend/routers/*.py`
- `backend/main.py`
- `backend/services/parser.py`
- `backend/services/ai_client.py`
- New schemas/config modules under `backend/`
- `backend/test_endpoints.py`

### Dependencies/configuration required

- Existing Pydantic/FastAPI capabilities are likely sufficient.
- Optional settings-management dependency only if approved; do not add it merely for abstraction.

### Security considerations

Bound input sizes before database queries, file reads, prompt construction, and model calls. Never use client-provided paths or IDs as filesystem paths without project containment and authorization checks.

### Testing strategy

Add parameterized tests for malformed IDs, blank/oversized questions, invalid levels/kinds, invalid numeric environment values, path separators, nonexistent files, and status transitions. Assert stable error status and response formats.

### Expected benefit

Makes behavior predictable for the frontend, improves OpenAPI documentation, and reduces malformed-input and resource-exhaustion paths.

### Risk of breaking existing functionality

Medium. Stricter bounds can reject previously accepted inputs. Introduce explicit limits and compatibility tests before changing defaults.

## 4. Error Handling, Background Jobs, and Observability

### Problem

The background parser marks projects as failed and logs exceptions, but the job has no durable error detail, retry policy, cancellation, progress, or queue isolation. Routes repeat error handling, and model/generation failures are not consistently translated into safe API responses. Local test behavior depends on database initialization and framework lifecycle behavior.

### Current implementation

- `backend/routers/upload.py` uses FastAPI `BackgroundTasks` and stores only `processing`, `ready`, or `failed` status.
- `backend/services/ai_client.py` falls back when no model response exists.
- `backend/routers/ask.py` raises a 500 with embedding exception text.
- Logging uses the standard Python logger, with no structured correlation ID or metrics.
- `backend/db/database.py` relies on `Base.metadata.create_all()`.

### Proposed solution

Define safe error categories and consistent response schemas. Store a user-safe failure reason and internal correlation ID separately. Add request/job correlation IDs, structured logs, and bounded retries only for transient operations. Make startup/database initialization and tests deterministic without changing production semantics. Evaluate a durable job queue only after the current flow has regression coverage; do not introduce one as an unrelated refactor.

### Files likely to change

- `backend/main.py`
- `backend/routers/upload.py`, `ask.py`, and generation routers
- `backend/db/database.py`
- `backend/models/db_models.py`
- `backend/test_endpoints.py`
- New error/config/logging helpers

### Dependencies/configuration required

- Existing Python logging and FastAPI exception handling may be enough initially.
- Optional metrics or durable queue dependencies should be deferred to the production-readiness phase.

### Security considerations

Never return stack traces, SQL, local paths, Git output, prompt contents, or provider credentials to clients. Ensure retries do not duplicate projects, artifacts, audit records, or expensive model calls.

### Testing strategy

Test parser exceptions, missing storage files, database failures, embedding failures, provider timeouts, invalid configuration, and duplicate/retry behavior. Verify safe client errors and useful server logs.

### Expected benefit

Improves diagnosability and prevents ambiguous stuck projects or leaked internal details.

### Risk of breaking existing functionality

Medium. Error status and body changes can affect the frontend and smoke tests. Introduce shared response formats while retaining existing successful responses.

## 5. Automated Testing and Regression Coverage

### Problem

`backend/test_endpoints.py` is a valuable smoke test, but it is a script rather than a structured test suite and does not cover many parser, storage, authorization, cache, or failure cases. The frontend has no automated tests. The separate prototype has `code-intelligence/tests/test_analyzer.py`, but it does not cover the active backend.

### Current implementation

- Backend smoke tests cover health, uploads, status, structure, explanations, docs, diagrams, Q&A, history, unsupported files, missing projects, traversal, and unsafe URLs.
- The smoke test can use `httpx` against a live service or FastAPI `TestClient`.
- Local `TestClient` execution may require explicit database schema initialization because of lifespan behavior in the installed stack.
- Frontend scripts provide lint and build, but no test script exists.

### Proposed solution

Convert backend checks into a repeatable pytest-compatible suite or add a focused test suite alongside the existing script without deleting the smoke test. Build fixtures for temporary SQLite and storage, isolate environment variables before imports, and test background parsing deterministically. Add parser unit tests, upload security tests, router contract tests, and cache tests. Add frontend component/API-mocking tests only after extracting stable UI boundaries.

### Files likely to change

- `backend/test_endpoints.py`
- New backend test modules and fixtures
- `backend/requirements.txt`
- `code-intelligence/tests/test_analyzer.py` only for prototype-specific coverage
- `frontend/package.json`
- New frontend test files/configuration if approved

### Dependencies/configuration required

- A test runner such as pytest for backend, if not already adopted
- A frontend test runner and DOM/API mocking tools, selected only when frontend boundaries are extracted
- Temporary database/storage configuration

### Security considerations

Tests must use fake credentials and temporary directories. Do not upload real repositories or expose `.env` values in logs. Include negative security cases as first-class tests.

### Testing strategy

Run fast unit tests first, then API integration tests, then the existing smoke flow, followed by frontend lint/build and frontend tests when added. Preserve a minimal no-provider test mode so tests do not call external AI services.

### Expected benefit

Prevents regressions while security, parsing, and provider changes are introduced incrementally.

### Risk of breaking existing functionality

Low to medium. Test infrastructure changes can expose existing lifecycle assumptions. Keep the current smoke script during migration and use isolated fixtures.

## 6. AI/LLM Provider Integration Without IBM Bob Runtime Code

### Problem

The application advertises AI-driven explanations, documentation, diagrams, and Q&A, but `_call_model()` is a placeholder. The current fallback behavior is deterministic and generic. The embedding implementation is synthetic and does not provide reliable semantic retrieval.

### Current implementation

- `backend/services/ai_client.py` builds prompts and calls `_call_model()`.
- `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, and `CODELENS_ENABLE_WATSONX` are read.
- No provider SDK or REST request is implemented.
- Fallback functions generate text from symbols/imports.
- `embed_text()` produces 384-dimensional character-based vectors.

### Proposed solution

Define a provider-neutral interface behind `services/ai_client.py` with explicit operations for generation and embeddings. Add one approved runtime provider implementation, such as an approved WatsonX integration, only after credentials, data handling, model IDs, timeouts, quotas, and privacy requirements are documented. Keep deterministic fallback mode enabled for local development and tests. Add provider selection through configuration, not IBM Bob tooling. Add prompt size limits, timeouts, retries for safe transient failures, response validation, and usage/error logging without source or secret leakage.

IBM Bob remains development-time tooling only and must not appear in `requirements.txt`, runtime code, deployment configuration, or application prompts as a runtime service.

### Files likely to change

- `backend/services/ai_client.py`
- `backend/requirements.txt`
- `backend/main.py` or a configuration module
- `backend/routers/ask.py`
- Documentation and non-secret environment examples
- New provider adapter and provider tests

### Dependencies/configuration required

- Approved provider SDK or HTTP client
- Model and embedding identifiers
- `WATSONX_API_KEY` and `WATSONX_PROJECT_ID` or the approved provider's equivalent, stored outside source control
- Timeouts, retry limits, token/context limits, and provider enablement flag

### Security considerations

Source code may contain credentials or proprietary code. Make provider transmission explicit, minimize context, redact known secrets where appropriate, enforce tenant boundaries, and never log prompts or provider credentials. Validate model-returned Mermaid/Markdown before rendering or storage.

### Testing strategy

Mock the provider adapter in unit tests. Test fallback mode, provider-disabled mode, timeout, malformed response, rate limit, authentication failure, context limits, and caching. Keep smoke tests provider-free and deterministic.

### Expected benefit

Enables actual model-quality explanations and answers without destroying the current offline fallback or coupling the app to IBM Bob.

### Risk of breaking existing functionality

High. Provider failures, latency, cost, output variation, and prompt limits affect user-visible behavior. Roll out behind a feature flag and retain fallback behavior.

## 7. Code Parsing and Intelligence Quality

### Problem

The active parser uses extension detection and line-prefix extraction for multiple languages. It does not reliably represent nested symbols, line ranges, types, routes, call relationships, inheritance, or resolved imports. Retrieval quality is further limited by synthetic embeddings and in-process ranking.

### Current implementation

- `backend/services/parser.py` supports many extensions through `EXT_TO_LANG`.
- Symbols/imports are extracted by reading lines and matching prefixes.
- Python-aware summarization exists in `ai_client.py`, but it is not the primary persisted parser.
- Chunks are symbol-boundary or fixed-window text.
- Q&A loads all project chunks into Python and ranks them with cosine similarity.
- `code-intelligence/analyzer/parser.py` has a separate Python AST parser, but it is not integrated.

### Proposed solution

Define a stable parsed-file schema with symbol names, kinds, qualified names, line ranges, imports, and parse diagnostics. Improve Python parsing with AST first, then add language-aware parsers only where justified by supported languages. Resolve internal imports conservatively and preserve unresolved imports as metadata. Replace synthetic embeddings only as part of the provider/vector-storage decision; do not combine parser rewrites and infrastructure migration without tests.

Decide explicitly whether to integrate selected code from `code-intelligence/` or retire the duplicate prototype. Do not silently maintain two competing active pipelines.

### Files likely to change

- `backend/services/parser.py`
- `backend/models/db_models.py`
- `backend/routers/structure.py`
- `backend/routers/ask.py`
- `backend/services/ai_client.py`
- `code-intelligence/analyzer/*` only if integration is approved
- Parser and retrieval tests

### Dependencies/configuration required

- Language parser libraries only for languages with a clear product requirement
- A real embedding provider and possibly vector storage for production-scale retrieval
- Database migration support if persisted schemas change

### Security considerations

Parsers must treat source as data, avoid executing it, and cap memory/time use. Do not run project build scripts or imports merely to analyze a repository.

### Testing strategy

Use fixture projects for each supported language, nested symbols, malformed files, imports, ignored directories, large files, and mixed encodings. Verify stable line ranges, chunk boundaries, retrieval source attribution, and no code execution.

### Expected benefit

Improves explanation context, dependency accuracy, Q&A relevance, and future documentation quality.

### Risk of breaking existing functionality

High. Changes to symbol names, file metadata, chunks, and embeddings can invalidate caches and alter API counts. Version parsed data or rebuild project indexes deliberately.

## 8. Documentation Generation and API Documentation

### Problem

README generation is a deterministic template based on file/language/symbol summaries. API documentation lists detected symbols and does not discover actual web routes or parameters. Generated Markdown is returned as plain content and is not rendered in the frontend.

### Current implementation

- `backend/routers/docs.py` supports `readme` and `api_docs` with caching and force regeneration.
- `backend/services/ai_client.py` provides `_fallback_readme()` and `_fallback_api_docs()`.
- The summary is built from `ProjectFile` rows.
- No route extraction or framework-specific API metadata exists.
- `frontend/src/App.jsx` displays `docContent` as plain text.

### Proposed solution

First improve deterministic output from the parsed metadata: stable headings, language summaries, symbol details, known limitations, and source paths. Add framework-aware route extraction only for explicitly supported frameworks. When an approved LLM is enabled, validate and normalize the generated Markdown before caching it. Add safe Markdown rendering in the frontend with sanitization and preserve a raw-copy option.

### Files likely to change

- `backend/routers/docs.py`
- `backend/services/ai_client.py`
- `backend/services/parser.py` or a documentation service
- `frontend/src/App.jsx`
- `frontend/package.json`
- Documentation and tests

### Dependencies/configuration required

- A Markdown parser/sanitizer for frontend rendering, if approved
- Optional framework-specific parsing libraries
- No IBM Bob runtime dependency

### Security considerations

Do not render generated HTML or model output unsanitized. Escape file paths and content appropriately. Avoid including secrets found in source code in generated artifacts.

### Testing strategy

Snapshot or assert stable deterministic Markdown sections. Test empty projects, mixed languages, unusual symbols, route-like code, malicious Markdown/HTML, cache hits, and force regeneration.

### Expected benefit

Produces more useful artifacts and a safer, clearer documentation experience without depending on a model.

### Risk of breaking existing functionality

Medium. Artifact content and frontend rendering will change. Keep the existing API fields and raw Markdown copy behavior.

## 9. Architecture Diagram Generation

### Problem

The current diagram uses heuristic import matching and returns Mermaid source. It does not render the graph in the frontend, represent non-import relationships, or guard against unsafe/invalid generated Mermaid.

### Current implementation

- `backend/routers/diagram.py` builds a path-to-import graph from `ProjectFile` rows.
- `backend/services/ai_client.py` resolves simple candidates and emits `graph TD` fallback syntax.
- The frontend shows the Mermaid text in a `<pre>` block.
- The generated artifact is cached as `diagram`.

### Proposed solution

Make deterministic import graph generation the baseline and improve path/module resolution using parser metadata. Add graph-size limits, stable node IDs, escaping, and a clear “unresolved external import” policy. Render Mermaid only with a maintained, sanitized frontend renderer after validating diagram syntax. Keep raw source available for copying and troubleshooting. Treat model-generated Mermaid as optional and untrusted.

### Files likely to change

- `backend/services/ai_client.py` or a dedicated diagram service
- `backend/routers/diagram.py`
- `backend/services/parser.py`
- `frontend/src/App.jsx`
- `frontend/package.json`
- Diagram tests

### Dependencies/configuration required

- A Mermaid frontend dependency if visual rendering is approved
- Optional syntax validation tooling
- Limits for nodes, edges, and output size

### Security considerations

Escape labels and reject or sanitize unsafe Mermaid constructs before rendering. Do not allow source paths or model output to become arbitrary HTML/JavaScript.

### Testing strategy

Test empty graphs, cycles, duplicate stems, Windows paths, unresolved imports, large graphs, malicious labels, cache behavior, and frontend rendering failure fallback.

### Expected benefit

Turns the existing artifact into a useful visual architecture feature while retaining the current raw syntax response.

### Risk of breaking existing functionality

Medium. Diagram content and frontend behavior change, but the existing `mermaid` response field should remain compatible.

## 10. Frontend Maintainability and UX

### Problem

`frontend/src/App.jsx` owns navigation, API requests, polling, all feature state, and all page markup. This makes changes risky, duplicates loading/error patterns, and makes automated testing difficult. The UI has no router, shared API client, or typed response models.

### Current implementation

- One React component stores all project, explanation, documentation, diagram, Q&A, and history state.
- API requests use direct `fetch` calls.
- Navigation is local state over named pages.
- Loading and error behavior is repeated inline.
- Documentation and Mermaid are displayed as raw text.

### Proposed solution

Extract a small API client and shared request/error utilities first. Then split feature views and hooks by workflow: upload/status, analysis, documentation, architecture, Q&A, and history. Preserve the current local navigation until a router is justified. Add stable loading, empty, error, and retry states. Add tests around extracted API and feature boundaries before changing visual behavior.

### Files likely to change

- `frontend/src/App.jsx`
- New frontend API/hooks/components files
- `frontend/src/App.css` and possibly `index.css`
- `frontend/package.json`
- `frontend/eslint.config.js`
- New frontend tests/configuration

### Dependencies/configuration required

- Existing React/Vite dependencies are sufficient for initial extraction.
- Add router, testing, Markdown, or Mermaid dependencies only for an approved feature and after evaluating bundle/security impact.

### Security considerations

Centralize response handling so failed requests do not accidentally display server internals. Sanitize rendered artifacts. Keep API base URLs configurable and avoid embedding credentials in the frontend bundle.

### Testing strategy

Run existing lint/build commands after each extraction slice. Add mocked API tests for upload polling, failed parsing, project switching, cache responses, and feature empty states.

### Expected benefit

Reduces change risk, makes workflows independently testable, and improves recovery from backend errors.

### Risk of breaking existing functionality

Medium to high during extraction. Move one workflow at a time, preserve state transitions and payloads, and run the backend smoke test plus frontend build after each slice.

# Prioritized Implementation Roadmap

## Phase 1 - Critical Fixes

1. **Create a regression baseline.** Preserve the passing backend smoke test, add isolated test database/storage setup, and add focused tests for the recently fixed explanation/docs/diagram paths.
2. **Establish project access control.** Decide the approved identity mechanism, add a shared project authorization dependency, and protect structure, explanation, documentation, diagram, Q&A, history, and audit routes. Keep an explicitly local-only default-user mode during transition.
3. **Make failures safe and deterministic.** Add consistent error responses, safe logging, and durable failure details without exposing paths, source, SQL, or provider data.
4. **Tighten CORS and configuration validation.** Require explicit production origins and validate required/bounded environment variables at startup.

### Recommended first Phase 1 improvement

Implement the project ownership/authorization boundary first, beginning with tests that demonstrate cross-project access is denied. It addresses the largest current security risk and prevents later AI, documentation, and frontend work from being built on an unsafe data-access model.

## Phase 2 - Security and Reliability

1. Add ZIP symlink/special-file checks, file-count and per-file limits, project disk quotas, parser/job timeouts, and cleanup policies.
2. Add project deletion/retention behavior and ensure database rows and stored files are removed together.
3. Centralize request validation, path normalization, project status guards, and safe error responses.
4. Add structured logging, correlation IDs, retry rules, and bounded background-job handling.
5. Add migrations instead of relying only on `Base.metadata.create_all()`.

## Phase 3 - AI and Code Intelligence Improvements

1. Define the provider-neutral generation/embedding interface behind `backend/services/ai_client.py`.
2. Add a real, approved LLM/embedding provider behind configuration while preserving deterministic fallback mode.
3. Add provider timeouts, quotas, context limits, redaction, response validation, and provider mocks.
4. Define a stable parsed-symbol schema and improve the active parser, starting with Python AST support.
5. Improve import resolution, chunk metadata, retrieval thresholds, and source attribution.
6. Decide whether to integrate or retire the separate `code-intelligence` prototype; do not maintain two silently competing pipelines.

IBM Bob remains a development-time tool throughout this phase and is not added to the runtime.

## Phase 4 - UX and Documentation Improvements

1. Extract the frontend API client and workflow hooks from `App.jsx`.
2. Add safe Markdown rendering and preserve raw-copy functionality.
3. Render validated Mermaid diagrams while retaining the source view and fallback.
4. Improve deterministic README/API documentation from parser metadata.
5. Add stable loading, empty, retry, and failure states and frontend tests.
6. Update root/backend/frontend documentation and add a non-secret environment example.

## Phase 5 - Production Readiness

1. Move parsing/indexing to a durable job system only after the job contract and tests are stable.
2. Add production database operations, migrations, backups, indexes, and vector-storage evaluation.
3. Add metrics, health/readiness checks, tracing, alerting, and operational dashboards.
4. Add deployment configuration, secret management, resource quotas, retention jobs, and dependency scanning.
5. Run security review, load testing, provider failure testing, and end-to-end frontend/backend validation.

# Change Control Rules

- Preserve the existing upload, parsing, explanation, documentation, diagram, Q&A, history, and fallback workflows while each phase is introduced.
- Make one bounded improvement at a time and run the narrowest relevant test before expanding scope.
- Do not change endpoint paths or response fields without documenting and testing a compatibility plan.
- Do not add IBM Bob runtime functionality, credentials, SDKs, or fake provider behavior.
- Do not treat the unintegrated `code-intelligence/` prototype as active product functionality.
- Do not commit secrets or inspect the contents of local environment files into documentation.
