# CodeLens-AI Layer 5 Review

## Review Scope

This is a security and code-quality review of the current working tree after the project-ownership implementation. The review used [AGENTS.md](../AGENTS.md), [docs/IBM_BOB_PLAN.md](IBM_BOB_PLAN.md), the active backend/frontend code, the prototype boundary, and the focused and smoke tests.

No IBM Bob runtime functionality was added. IBM Bob remains a development-time tool only.

## Baseline Reviewed

The active product is:

- `backend/`: FastAPI, SQLAlchemy, upload/parsing/generation/retrieval API.
- `frontend/`: React/Vite UI using direct `fetch` calls.
- `code-intelligence/`: separate prototype, not mounted by `backend/main.py`.

Recent authorization changes add:

- `backend/services/access.py`
- `X-CodeLens-User` development identity handling
- Ownership checks to upload/status, structure, explanations, docs, diagrams, Q&A, history, and audit routes
- `backend/test_authorization.py`

The current tests pass for owner access, cross-user rejection, existing workflows, and ZIP special-file rejection.

## Executive Summary

No Critical findings were identified in the reviewed code.

One High-risk issue was fixed during this review: ZIP archives did not limit member count or reject special-file entries before extraction.

Three High findings remain deferred because they require an approved production identity, deployment, or job/resource architecture rather than a safe local patch:

1. `X-CodeLens-User` is a caller-supplied username, not authentication.
2. CORS defaults to wildcard origins while credentials are enabled.
3. Repository cloning and parsing remain subject to broader disk, CPU, file-count, and job-concurrency exhaustion risks.

The ownership implementation is useful as a development boundary and prevents cross-project access when distinct trusted user contexts are supplied. It must not be described as production authentication.

# Findings

## H-01: Development identity header is spoofable

- Severity: High
- File: `backend/services/access.py`
- Problem: `get_current_user()` treats the caller-supplied `X-CodeLens-User` value as the identity. Any caller who knows an existing username can send that header and select the user's project context. Requests without the header use the shared `codelens_demo` user.
- Why it matters: The current boundary prevents accidental cross-context access in development tests, but it does not prevent a malicious caller from impersonating another user. In the current frontend, no identity header is sent, so all no-header clients intentionally share the demo context.
- Recommended fix: Replace the header with an approved authenticated principal from an identity provider, trusted reverse proxy, signed token, or equivalent. Make the demo-user fallback explicitly local-development-only and reject missing identity in production.
- Status: Defer. This requires the authentication decision explicitly left open in the plan; inventing token infrastructure here would be a major architectural change.
- Test needed: Test missing/invalid credentials, valid owner credentials, cross-user credentials, expired credentials, and authorization across every project-scoped route. Keep a separate local-development fallback test if it remains supported.

## H-02: Wildcard CORS with credentials enabled

- Severity: High
- File: `backend/main.py`
- Problem: `allow_origins` defaults to `*` while `allow_credentials=True`, and all methods and headers are allowed.
- Why it matters: A permissive browser policy broadens the set of origins that can send requests and attempt to read API responses. The risk is especially important while identity and project data are being introduced. Starlette/browser behavior limits some wildcard credential combinations, but relying on that interaction is not an explicit security policy.
- Recommended fix: Require an explicit configured allowlist of trusted frontend origins in production. Keep a narrowly documented local-development default if needed, and validate that wildcard origins cannot be combined with credentialed deployments.
- Status: Defer. The user explicitly requested no CORS change for the ownership implementation, and the correct origin list is deployment-specific.
- Test needed: Test allowed origin, disallowed origin, preflight methods/headers, credentialed requests, and production configuration rejection of wildcard origins.

## H-03: Repository/job resource exhaustion remains possible

- Severity: High
- File: `backend/routers/upload.py`, `backend/services/parser.py`, `backend/routers/ask.py`
- Problem: Upload bytes and declared ZIP decompressed bytes are capped, and ZIP member count is now capped, but Git clones and parsing still have no explicit disk quota, repository file-count quota, parser CPU/time limit, concurrent-job limit, or cleanup/retention policy. Q&A loads every project chunk into Python for each request.
- Why it matters: A permitted repository or many concurrent requests can consume disk, memory, CPU, database connections, or request-worker capacity. Git repositories are not governed by the upload byte limit because they are fetched externally.
- Recommended fix: Add configurable per-project disk/file limits, clone and parser budgets, concurrency control, cleanup on failure and retention, bounded Q&A retrieval, and eventually durable job isolation.
- Status: Defer. This is the planned Phase 2/Phase 5 resource and job work and is broader than a safe ownership patch.
- Test needed: Large archive, many-entry archive, large Git repository, parser timeout, concurrent uploads, Q&A chunk-count limits, disk cleanup, and abandoned-job tests.

## H-04: ZIP special-file and member-count abuse

- Severity: High
- File: `backend/routers/upload.py`
- Problem: Before this review, ZIP extraction relied on path containment and total declared decompressed size but did not cap archive member count or reject symbolic-link/special-file metadata before `extractall`.
- Why it matters: Excessive central-directory entries can consume memory and extraction time, and special-file entries can create unsafe filesystem objects or unexpected extraction behavior on supported platforms.
- Recommended fix: Cap ZIP members and reject block, character, FIFO, socket, and symbolic-link entries before extraction. Preserve existing path and decompressed-size checks.
- Status: Fixed now. `MAX_ZIP_MEMBERS` is set to 10,000 and unsafe special-file types are rejected.
- Test needed: Archive with a symbolic-link entry, archive with each special-file type where supported, archive over the member limit, traversal names, absolute names, invalid ZIP, and decompressed-size overflow.

## M-01: Embedding exception text is returned to clients

- Severity: Medium
- File: `backend/routers/ask.py`
- Problem: The Q&A route returns `Embedding failed: {exc}` directly in a 500 response.
- Why it matters: Provider or database exception text can disclose implementation details, paths, configuration, or service information.
- Recommended fix: Log the exception server-side with a request/project correlation ID and return a generic error message.
- Status: Defer to the error-handling phase unless provider errors are exposed in the deployment. It is a small safe fix and should be grouped with the shared error response work.
- Test needed: Mock `embed_text()` to raise and assert the response contains no exception detail while the server log records the failure.

## M-02: Git clone failure detail is returned to clients

- Severity: Medium
- File: `backend/routers/upload.py`
- Problem: A failed clone returns the first 300 characters of `git` stderr.
- Why it matters: Remote output can expose repository names, local command details, URLs, or environment-dependent messages. It is not currently a direct secret source because credentials are not accepted by the URL allowlist, but it is unnecessary internal detail.
- Recommended fix: Log a truncated sanitized diagnostic server-side and return a stable generic clone failure response.
- Status: Defer to centralized error handling, with a low-risk local patch suitable for the next reliability slice.
- Test needed: Mock a nonzero Git result containing sensitive marker text and assert the response omits it.

## M-03: Project ownership depends on a development-only context

- Severity: Medium
- File: `backend/services/access.py`, `frontend/src/App.jsx`
- Problem: The frontend does not send `X-CodeLens-User`; its requests therefore use the shared demo user. There is also no endpoint or approved user-provisioning flow for creating named development users.
- Why it matters: The new tests can demonstrate isolation, but normal UI usage remains single-context. Adding arbitrary user creation from a request would create an impersonation vulnerability.
- Recommended fix: Add the real identity flow before enabling multi-user UI. Until then, keep the header as a trusted local/test context only and document the limitation.
- Status: Defer with H-01. Do not add a user-creation endpoint as a shortcut.
- Test needed: Frontend requests with a valid authenticated context once the identity mechanism exists, plus explicit tests that unknown contexts are rejected.

## M-04: Project-file path checks do not require a parsed-file record

- Severity: Medium
- File: `backend/routers/explain.py`
- Problem: `_resolve_project_file()` checks that a requested path remains inside the owned project directory and is a regular file, but it does not require the path to exist in `ProjectFile` metadata.
- Why it matters: An owner could request ignored or unsupported files that remain in their own repository directory. This is not a cross-project escape because ownership and containment are checked, but it makes the API surface broader than the parsed project model.
- Recommended fix: Resolve the requested path against an owned `ProjectFile` row before reading it, unless access to all owner-readable stored files is intentional.
- Status: Defer. This is a behavior decision and changing it could affect legitimate explanation requests.
- Test needed: Verify supported parsed file access, ignored-file behavior, missing-file behavior, and traversal attempts.

## M-05: Mermaid and generated Markdown are untrusted content

- Severity: Medium
- File: `backend/services/ai_client.py`, `backend/routers/diagram.py`, `frontend/src/App.jsx`
- Problem: Diagram and documentation content is cached and returned as generated text. The current frontend displays both as plain text, so it does not currently execute generated HTML or Mermaid. Future rendering would create an injection risk if output is treated as trusted markup.
- Why it matters: Model output, source paths, labels, and generated Markdown can contain HTML or Mermaid constructs that become active when rendered.
- Recommended fix: Validate/escape Mermaid labels, constrain diagram syntax, sanitize Markdown/HTML, and keep a safe raw-text fallback before adding visual rendering.
- Status: Defer to the planned documentation/diagram UX work. No active rendered-XSS path was found in the current frontend.
- Test needed: Malicious Markdown, HTML, Mermaid labels, model responses, and frontend rendering fallback tests.

## M-06: Future provider integration could transmit source code

- Severity: Medium
- File: `backend/services/ai_client.py`
- Problem: The placeholder `_call_model()` is inactive, but its intended prompts include source snippets, project summaries, retrieved chunks, and potentially file paths. A future provider implementation could transmit proprietary code or secrets.
- Why it matters: Uploaded repositories are untrusted and may contain credentials or private intellectual property. External transmission requires an explicit privacy and redaction decision.
- Recommended fix: Keep provider calls behind the existing boundary, add opt-in configuration, context/token limits, redaction policy, timeout/error handling, and documentation of data handling. Never add IBM Bob runtime calls.
- Status: Defer to the planned provider-integration phase.
- Test needed: Mock provider requests and assert bounded/redacted payloads, disabled-provider fallback, timeout behavior, and no prompt/secret logging.

## M-07: Secrets are environment-based but runtime configuration needs stronger enforcement

- Severity: Medium
- File: `backend/services/ai_client.py`, `backend/db/database.py`, `backend/.env`
- Problem: Sensitive settings are read from environment variables, which is appropriate, but startup does not validate production security posture. A local `backend/.env` exists on disk and must remain ignored; its contents were not inspected or committed.
- Why it matters: Accidental environment-file commits or permissive defaults could expose database/provider credentials. `DATABASE_URL` is required, but other sensitive/runtime settings have no environment mode validation.
- Recommended fix: Keep `.env` ignored, add a non-secret `.env.example`, validate required production settings, and document secret-management expectations. Do not print values.
- Status: Defer to configuration/production-readiness work.
- Test needed: Secret-file ignore checks, missing/invalid environment configuration, production-default validation, and log-scrubbing tests.

## M-08: Database schema lifecycle has no migrations

- Severity: Medium
- File: `backend/db/database.py`, `backend/models/db_models.py`
- Problem: Tables are created with `Base.metadata.create_all()` and there is no migration system. The new ownership behavior relies on existing `Project.user_id` data and direct test seeding.
- Why it matters: Schema changes, indexes, constraints, and future identity migrations cannot be safely rolled forward or audited in deployed environments.
- Recommended fix: Add a migration system and a controlled migration for ownership constraints and existing projects before production deployment.
- Status: Defer to Phase 5. It is not needed for the current SQLite-compatible ownership test.
- Test needed: Fresh database migration, upgrade from an existing database, downgrade/backup strategy, and ownership-data migration tests.

## M-09: Test lifecycle and coverage are limited

- Severity: Medium
- File: `backend/test_endpoints.py`, `backend/test_authorization.py`, `frontend/`
- Problem: The active backend tests are scripts using assertions. The smoke test may require explicit schema initialization when it falls back to `TestClient`; the frontend has no automated tests. The new authorization test uses direct database user seeding.
- Why it matters: Important security and lifecycle behavior can regress without a repeatable fixture/test-runner model. Frontend identity propagation is not tested.
- Recommended fix: Migrate incrementally to structured backend tests with isolated database/storage fixtures, retain the smoke script during migration, and add frontend API/workflow tests after identity integration.
- Status: Defer to the planned testing phase.
- Test needed: CI test command, isolated fixtures, parser/upload/security unit tests, route contract tests, and frontend mocked API tests.

## M-10: Dependency versions are broad

- Severity: Medium
- File: `backend/requirements.txt`, `frontend/package.json`
- Problem: Backend dependencies use minimum-version ranges and frontend dependencies use caret ranges. There is no dependency audit or lockfile for Python.
- Why it matters: Reproducibility and security patch tracking are weaker, and transitive upgrades can alter FastAPI/Starlette/httpx lifecycle behavior.
- Recommended fix: Use a controlled lock/update process, run dependency vulnerability checks, and test upgrades in CI. Do not pin blindly without a maintenance policy.
- Status: Defer to production-readiness/dependency maintenance.
- Test needed: Reproducible install, dependency audit, smoke/build test against approved versions.

## M-11: Prototype local-path analyzer would be unsafe if exposed

- Severity: Medium
- File: `code-intelligence/main.py`
- Problem: The separate prototype `/analyze` endpoint accepts an arbitrary `project_path` and scans it. It is not mounted by the active backend.
- Why it matters: If the prototype service is exposed or integrated without redesign, callers could probe server-local filesystem paths.
- Recommended fix: Keep the prototype unmounted, or redesign it to accept isolated uploaded project IDs rather than arbitrary server paths before deployment.
- Status: Defer. It is not part of the active runtime.
- Test needed: If integration is proposed, test path containment, authorization, and no local path disclosure.

## M-12: Audit helper commits independently inside request workflows

- Severity: Low
- File: `backend/services/audit.py`
- Problem: `log_action()` commits immediately. A successful operation followed by an audit commit failure or a later request failure can leave data and audit records inconsistent.
- Why it matters: Audit completeness and transactional interpretation become difficult, although this is not currently a cross-project disclosure path.
- Recommended fix: Decide which actions require one transaction and move audit writes into explicit transaction boundaries or an outbox/event mechanism.
- Status: Defer to reliability/observability work.
- Test needed: Simulated audit commit failure, operation rollback, and duplicate/retry behavior.

## M-13: Background task state has limited progress and failure detail

- Severity: Low
- File: `backend/routers/upload.py`
- Problem: Parsing exposes only `processing`, `ready`, and `failed`, and failures are logged rather than stored with a safe diagnostic.
- Why it matters: Users cannot distinguish unsupported/no files, parser failure, embedding failure, or infrastructure failure. This can cause retries and repeated resource use.
- Recommended fix: Add safe status/error metadata and bounded job retries as part of the reliability phase.
- Status: Defer. No current data-disclosure regression was found.
- Test needed: Parser failure/status response and retry tests.

## M-14: Q&A retrieval threshold defaults to zero

- Severity: Low
- File: `backend/routers/ask.py`
- Problem: The default `ASK_SIMILARITY_THRESHOLD` is `0.0`, so the top chunks are accepted even when relevance is weak.
- Why it matters: Answers can be misleading and may include unrelated source context. This is a quality and potential data-minimization concern, not a cross-project access issue because chunks are filtered by owned project.
- Recommended fix: Tune the threshold with real embeddings and evaluation data; do not raise it blindly while synthetic embeddings remain active.
- Status: Defer to retrieval/provider work.
- Test needed: Retrieval relevance fixtures, threshold behavior, and source attribution tests.

# Review by Requested Area

## 1. Project ownership and authorization

Ownership is now enforced through `Project.user_id` and `get_owned_project()` for all active project-scoped routes. The boundary is effective for distinct trusted user contexts but is not production authentication; see H-01.

## 2. X-CodeLens-User development identity handling

Absent header maps to the existing demo user for compatibility. A present header must name an existing user; blank or unknown values return `401`. The header is spoofable and must be replaced by authenticated identity before production.

## 3. Cross-project data access

Project-specific structure, explanation, docs, diagrams, Q&A, history, status, and audit access query through ownership. History lists filter by owner. Focused tests reject another seeded user with `404` and avoid revealing project existence.

## 4. Upload and project-status access

New projects are assigned to the resolved current user. Status uses owned-project lookup. Existing no-header smoke workflows continue to work.

## 5. History and audit-log access

History is owner-filtered. Audit logs are filtered through either the current user or an owned project; this preserves project-scoped generation/explanation events, which may have a null `AuditLog.user_id`, without exposing another user's project events.

## 6. File-path validation and traversal protection

Single-file names are sanitized and explanation paths use `realpath` plus `commonpath` containment. ZIP members use the same containment check. The explanation route does not require a `ProjectFile` row; see M-04.

## 7. ZIP extraction security

Upload size, invalid archive, declared decompressed size, path traversal, member count, and special-file checks are present. Symlink/special-entry regression coverage was added. Retention, disk, and parser resource limits remain incomplete; see H-03.

## 8. Git repository URL validation

The allowlist accepts only matching HTTPS GitHub, GitLab, and Bitbucket repository URLs. Clone uses an argument list, shallow clone, and a 60-second timeout. Clone output detail and broader clone resource limits remain review items.

## 9. Command/process execution risks

The active backend invokes `git` with a list of arguments and does not use shell interpolation. The prototype accepts local paths but is not mounted. No direct shell-injection path was found.

## 10. CORS configuration

CORS is broad by default: wildcard origin, credentials enabled, all methods, and all headers. This is a deployment security concern; see H-02. It was not changed in this review because the requested ownership work did not define trusted production origins.

## 11. API input validation

Pydantic validates explanation levels and document kinds. Upload, path, URL, and question checks exist. Numeric environment values and maximum question/prompt sizes are not centrally validated.

## 12. Error handling and information leakage

Project-not-found and unauthorized project responses are intentionally unified as `404`. Embedding exception text and Git stderr can leak internal detail; see M-01 and M-02.

## 13. AI prompt/data exposure risks

The runtime model call is inactive, and current fallbacks are local. Future provider prompts would include source-derived data; see M-06. No IBM Bob runtime integration exists.

## 14. Secret/API-key handling

Keys are read from environment variables and are not hardcoded. The local `.env` is ignored by repository rules, but production validation and secret-management documentation are incomplete; see M-07.

## 15. Database access

SQLAlchemy sessions are provided through `get_db()` and closed. Project data is filtered by ownership in routes. There are no migrations, and schema creation depends on `create_all()`; see M-08.

## 16. Resource exhaustion risks

Upload/decompressed-size and now ZIP-member limits exist. Git clone, parser execution, storage retention, concurrency, and Q&A loading remain bounded only partially; see H-03.

## 17. Mermaid/XSS risks

Current frontend displays Mermaid and Markdown as text, so no active rendering XSS was found. Any future rendering must sanitize and validate output; see M-05.

## 18. Dependency/security concerns

Dependencies are not tightly locked for Python and there is no visible dependency audit process. The frontend has a lockfile but uses range versions. See M-10.

## 19. Test coverage

The smoke suite covers the main backend workflows. New ownership tests cover owner/non-owner behavior across project endpoints, and ZIP security tests cover special entries. Structured fixtures, failure tests, frontend tests, and provider tests remain missing; see M-09.

## 20. Regression risk from authorization changes

The complete existing smoke suite passes without identity headers. The new tests pass with two named user contexts. The main compatibility assumption is that existing no-header clients remain the demo user; multi-user production behavior is intentionally not solved by this change.

# Findings Fixed During Review

1. Added a 10,000-member ZIP limit before extraction.
2. Rejected ZIP block, character, FIFO, socket, and symbolic-link entries before extraction.
3. Added `backend/test_upload_security.py` covering special-file rejection.
4. Preserved existing path traversal, upload-size, and decompressed-size checks.

The ownership changes being reviewed remain in place and passed their focused tests; they were not reverted or broadened into full authentication.

# Findings Deferred

- H-01: Replace the spoofable development header with approved authentication.
- H-02: Configure an explicit production CORS allowlist.
- H-03: Add full clone/parser/storage/concurrency resource controls and job isolation.
- M-01/M-02: Centralize safe error responses and server-side diagnostics.
- M-03/M-04: Complete identity-aware frontend behavior and decide parsed-file access policy.
- M-05/M-06: Sanitize rendered artifacts and implement provider data-handling controls before model integration.
- M-07/M-08/M-09/M-10: Production configuration, migrations, testing infrastructure, and dependency management.
- M-11/M-12/M-13/M-14: Prototype isolation, audit transactions, job diagnostics, and retrieval-quality improvements.

# Validation Performed

- Focused project-ownership tests: passed.
- Focused ZIP security test: passed.
- Python compile/import validation: passed.
- Existing backend smoke suite: passed.
- `git diff --check`: passed.

The existing smoke suite covered health, ZIP and single-file uploads, parsing/status, structure, explanations, documentation, diagrams, Q&A, history, invalid file types, missing projects, path traversal, and unsafe Git URLs.

# Overall Assessment

The current ownership implementation is a useful compatibility-preserving development boundary. It blocks cross-project access when callers use distinct known user contexts and avoids leaking unauthorized project existence through project-scoped `404` responses. It is not a production authorization system because the identity header is caller-controlled and no authentication provider exists.

The next security priority is to select and integrate an approved authenticated principal, then make the demo-user fallback local-only. Resource quotas, explicit CORS, durable job isolation, migrations, and structured tests should follow. The current code should not claim production multi-user security or production LLM behavior.
