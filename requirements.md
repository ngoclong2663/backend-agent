# AI Fullstack Generation Agent — Requirements Specification

**Version:** 1.12  
**Status:** Approved for MVP — backlog in [`pdm/`](pdm/README.md)  
**Priority:** High

**Changes in 1.12 (2026-11-07, proposed):**
- **Draft provider** (FR-38, Epic 24): every LLM-only step (drafting, repairs, workflow discovery, expectations,
  binding, screen judging, summary) runs on one provider: the Antigravity or Claude Code CLI in a one-turn JSON mode
  with structured output (no per-token cost on their account / subscription logins) or the Gemini API. Drafting stays one-turn; the agent-loop draft stays refused.
- **App correctness** (FR-39, Epic 25): records tied to a person are private to that person by default (staff see
  what their role needs), actions are guarded by the role they belong to, a record staff create for someone belongs to
  that person, and demo data belongs to the demo users. Found by the business-value lab on three requirements.
- **Business workflows** (FR-40, Epic 26): the main workflows are discovered from the requirement, their expectations
  frozen before generation, each step bound to the app; generated apps show a guided tour per role (react-joyride);
  a read-only Business tab evaluates the running app against the expectations. The evaluation never changes a
  generation's status.

**Changes in 1.11 (2026-11-06):**
- **App design** (FR-37, Epic 23): a dynamic app's layout follows its data and its kind of product. The draft writes a
  design brief (archetype, shell, a view per entity, field roles, home, filters, three looks) and, when roles use the
  app differently, areas with a layout each; code checks every choice against the contract and builds it from tested
  kit components (no engine call by default). Lists may take date ranges; records some roles may not see are hidden by
  the backend (visibility rules). Apps in Japanese get Japanese text and a bundled Japanese face.

**Changes in 1.10 (2026-11-06):**
- **One dynamic flow**: every dynamic app is built by the app flow (FR-36). The legacy dynamic flow is gone: no
  designed pages, direction cards, Manage area, journeys or journey tests for dynamic apps (FR-32's parts on them are
  superseded). Static sites are unchanged.
- App forms type every field (dates, choices, numbers with units and currency), pick references from a searchable
  list instead of asking for ids, and the plugins have screens: sign-in and roles, status changes, uploads, payments
  and many-to-many links (FR-36).
- Drafting runs on the API engine only (one request per step, about 6K input tokens for an app); the CLI engines
  write code. An API draft answers in the shape of its files (structured output), and code fixes mechanical mistakes,
  so a spec repair is the exception (FR-24).
- Backlog: Stories 22.5–22.8.

**Changes in 1.9 (2026-11-05):**
- **Dynamic app frontend**: a dynamic app's frontend is its own flow, separate from static sites. The model drafts
  what the app is (entities, navigation, labels, dashboard) in one call; every screen is built by code from the API
  contract on one component kit, and every operation is reachable from a screen. Static sites do not change (new
  FR-36).
- Backlog: Epic 10 is built backend and contract first (12 stories); its frontend halves and the form kit move to
  the new Epic 22 (8 stories).

**Changes in 1.8 (2026-11-04):**
- **Backend feature plugins**: auth, roles and ownership, rules, file storage, background jobs and events, email,
  webhooks and payments are written from tested plugin code, with their frontend half in dynamic mode; the engine
  writes only custom operations, custom rules and custom job bodies (FR-06, FR-07, new FR-34).
- **Forms that fit the API**: every request field has a source (server, signed-in user, route, a picked record, an
  upload, or the user's input), so no form asks for an id; forms use designed components and show server errors on
  their fields (new FR-35).
- Capacity, no-overlap and unique-together rules are enforced by the database, and many-to-many and one-to-one
  relations are generated from templates (FR-04, FR-07).
- Backlog: Epic 10 re-planned (13 stories). FR-33 stays reserved for Epic 20 (design directions).

**Changes in 1.7 (2026-11-04):**
- **Lanes deliver on their own** (dynamic mode): each lane's preview starts as soon as the lane passes; the switch to
  the live API and the live checks run in the background; a failed frontend lane no longer fails the generation or
  cancels the backend (FR-21, FR-27).
- **Lean backend validation**: no engine step writes tests (`generate_tests` removed; template tests only), and only
  the checks that prove the app starts and its API works can fail the backend or start a repair (FR-09, FR-11).
- Backlog: Stories 18.11, 18.12, 18.13.

**Changes in 1.6 (2026-10-31):**
- **Real photos**: FrontendSpec assets can have `source: "photo"` with Gemini image API generation (`gemini-3.1-flash-lite-image`), WebP post-processing, and caching. Photos are created during drafting and stored as uploads, with fallback to placeholders when unconfigured (FR-31).
- **API-driven dynamic apps**: Dynamic web apps start from user journeys; the section library supports row actions, edit forms with record loading, list controls, and action bars; uncovered operations get an auto-generated Manage area; Playwright journey tests verify user journeys on mocks and the live API; one-click generation flow (FR-32).
- Backlog: Epic 19.

**Changes in 1.5 (2026-10-30):**
- The requirement for drafting can be plain text or Markdown, typed or uploaded as a `.md` / `.txt` file, in all
  three modes (FR-01, FR-24).
- Drafted static and dynamic sites get a **design direction** (palette, font pairing, page structure) chosen from
  curated design data for the kind of site described, with alternatives to switch between in the review (FR-24).
  Backlog: Stories 2.4, 12.4, 12.6, 17.7.

**Changes in 1.4 (2026-10-28):**
- **Fast generation and reuse**: catalogue sections are rendered from the FrontendSpec without an engine call,
  custom components are generated in parallel and reused from a cache once validated, backend CRUD modules come
  from templates, and mechanical lint fixes no longer need an engine repair (FR-30). Backlog: Epic 17.

**Changes in 1.3 (2026-10-27):**
- Site images: FrontendSpec assets can be **drawn as SVG by the code engine** in the theme's colours, uploaded,
  linked, or (optionally, opt-in) generated by an image model (FR-28).
- **Revisions**: after a frontend is generated, the user changes it through spec edits (theme, content, assets)
  or feedback on a section, component or page, each validated and redeployed as a new revision (FR-29).
- FR-18 (UI) and FR-22 (assets) extended. Backlog: Epics 15–16.

**Changes in 1.2 (2026-10-26):**
- Frontend generation is in scope. The user picks a **generation mode**: backend API only, **static website**
  (frontend only), or **dynamic web app** (frontend + backend generated **in parallel** from one API contract).
- New **FrontendSpec** JSON (pages, theme, layout, components, data bindings, forms, content), drafted from a
  requirement and reviewed in the UI before generation.
- Generated frontends follow the project's `nextjs-skills` (Next.js App Router, pnpm, shadcn/ui, design tokens,
  React Query, Zustand, RHF + Zod), exactly as generated backends follow `fastapi-skills`.
- In dynamic mode the frontend runs on a mock API generated from the contract (`MOCK_TEST_API=true`) and switches
  to the real backend (`MOCK_TEST_API=false`) once the backend is generated and healthy.
- New requirements FR-21 … FR-27; FR-18 (UI) extended. Backlog: Epics 12–14, Stories 9.7–9.8.

**Changes in 1.1 (2026-10-23):**
- Code generation goes through a pluggable engine: Claude Code CLI (default) and Antigravity CLI.
- Generated backends follow the project's `fastapi-skills` (template `feat/fastapi` + hexagonal modules + SQLModel), replacing the original §6 layout.
- Two more input modes: natural-language requirement drafting, and Frontend-Agent site JSON import with seed data.
- Successfully generated backends run as a local **preview container** that clients can call.
- Agent UI (Next.js, `nextjs-skills`) for input, live workflow steps, tracing, results and an OpenAPI explorer.
- Local runtime is Docker Compose on PostgreSQL 18.

## 1. Project Overview

### 1.1 Objective

Develop an AI-powered Fullstack Generation Agent (formerly Backend Generation Agent) capable of automatically generating complete, executable FastAPI backend applications based on structured JSON specifications.

The agent must use LangGraph to orchestrate the generation workflow and a pluggable code-generation engine — Claude Code CLI (default) or Antigravity CLI — to generate, modify, and repair source code.

LangSmith will provide observability, tracing, and evaluation of the agent's execution.

The generated backend must be independent of the frontend and expose machine-readable API contracts that a separate Integration Agent can consume.

Since v1.2 the agent can also generate the frontend: a static website, or a dynamic web app whose frontend and
backend are generated in parallel from a shared API contract (FR-21 … FR-27). Since v1.3 generated sites get
images (FR-28) and can be revised from user feedback (FR-29).

### 1.2 Goals

- Generate backend applications automatically from structured JSON input, a natural-language requirement, or an imported Frontend-Agent site JSON.
- Support database models, REST APIs, authentication, authorization, validation, and business logic.
- Generate maintainable Python code following FastAPI best practices.
- Automatically install dependencies, validate source code, execute tests, and repair errors.
- Support asynchronous generation jobs and progress monitoring.
- Maintain execution state and support recovery from failures.
- Provide traceability through LangSmith.
- Produce standardized artifacts for future frontend/backend integration.
- Run each successfully generated backend as its own local container so clients can call it immediately.
- Provide a web UI to submit inputs, watch the workflow, inspect traces and results, and test the generated API.
- Generate Next.js frontends (`nextjs-skills`) from a FrontendSpec: static sites, or dynamic apps generated in
  parallel with their backend and connected to it through a contract-first API, mocks first, then the live API.

### 1.3 Out of Scope — Initial MVP

- Frontend frameworks other than Next.js (frontend generation itself is in scope since v1.2).
- Integrating with arbitrary existing frontends or backends (only the pairs this agent generates).
- Automatic production deployment (local preview containers only; see FR-19).
- GraphQL generation.
- Microservices architecture generation.
- Automatic creation of cloud infrastructure.
- Modifying arbitrary existing backend repositories.
- Generating applications in frameworks other than FastAPI.

---

## 2. Technology Stack

| Component | Technology |
|---|---|
| Agent API Server | Python + FastAPI, built with `.agents/skills/fastapi-skills` |
| Agent UI | Next.js (App Router), built with `.agents/skills/nextjs-skills` |
| Agent Orchestration | LangGraph (Python) |
| LLM Utilities | LangChain |
| Code Generation Engine | Pluggable: Claude Code CLI (default), Antigravity CLI (`agy`) |
| Tracing & Evaluation | LangSmith |
| Specification Validation | Pydantic / JSON Schema |
| Job Database | PostgreSQL 18 |
| Checkpoint Persistence | LangGraph PostgreSQL Checkpointer |
| Background Job Execution | Dedicated Python worker + Redis queue |
| Execution Environment | Isolated Docker containers (per-job sandbox) |
| Preview Runtime | One local Docker container (+ PostgreSQL 18) per generated backend |
| Local Deployment | Docker Compose (`make up`); dev mode runs infra only in Docker |
| Artifact Storage | Local filesystem for MVP; S3-compatible storage later |
| Generated Framework | FastAPI, from the `fastapi-skills` template (`feat/fastapi`, pinned commit) |
| Generated ORM | SQLModel (on SQLAlchemy 2.x) |
| Database Migrations | Alembic (autogenerated) |
| Generated Validation | Pydantic v2 |
| Generated Tests | Pytest |
| Code Quality | Ruff + `fastapi-skills` conventions check |
| Generated Frontend | Next.js (App Router) from `nextjs-skills`: pnpm, shadcn/ui, design tokens, React Query, Zustand, RHF + Zod |
| API Contract | OpenAPI 3.1, generated deterministically from the BackendSpec plan (dynamic mode) |
| Frontend API Client / Mocks | `openapi-typescript` types + typed fetch client; MSW handlers and example data from the contract |
| Frontend Tests | TypeScript check, ESLint, `next build`, Vitest, Playwright smoke tests (Node sandbox) |

The agent service and generated applications are separate projects. A generated application's Python dependencies and runtime environment must not be shared with the agent service.

---

## 3. High-Level Architecture

The system consists of nine primary components.

### 3.1 Backend Generation API

A FastAPI service responsible for:

- Accepting JSON backend specifications.
- Validating incoming requests.
- Creating generation jobs.
- Retrieving execution status.
- Providing execution logs and progress.
- Allowing users to cancel jobs.
- Returning generated artifacts.

All generation requests must execute asynchronously.

### 3.2 LangGraph Orchestrator

Responsible for:

- Controlling execution order.
- Managing workflow state.
- Invoking generation tools.
- Handling conditional branches.
- Managing retries.
- Recording checkpoints.
- Determining generation success or failure.

### 3.3 Code Engine Adapters (Claude Code CLI, Antigravity CLI)

A reusable Python port (`CodeEngine`) with one adapter per engine, responsible for:

- Executing the engine CLI in non-interactive mode.
- Providing the `fastapi-skills` skill and project conventions to the engine inside the workspace.
- Passing instructions and file references.
- Setting the correct working directory.
- Capturing stdout, stderr, and structured output.
- Collecting execution metadata.
- Enforcing execution limits.
- Handling timeouts and cancellation.
- Returning normalized results to LangGraph.

The engine is selected per job. Adding or replacing an engine must not require changes to the LangGraph workflow. A fake engine exists for tests.

### 3.4 Validation and Testing Engine

Responsible for:

- Validating generated Python syntax.
- Checking code quality.
- Installing dependencies in an isolated environment.
- Checking database model consistency.
- Running automated tests.
- Capturing errors for the repair workflow.

### 3.5 Artifact Manager

Responsible for:

- Packaging generated source code.
- Exporting OpenAPI specifications.
- Creating generation manifests.
- Saving test reports.
- Providing artifact download references.
- Preparing outputs for the future Integration Agent.

### 3.6 Preview Runtime

Responsible for building each successfully generated backend into an image and running it as a local container with its own PostgreSQL, so that clients can call it (FR-19).

### 3.7 Agent UI

A Next.js application for choosing the generation mode, submitting inputs, reviewing specs, following progress, inspecting traces and results, and testing the generated API (FR-18).

### 3.8 Frontend Lane

Plans and generates a Next.js frontend from a FrontendSpec on the `nextjs-skills` foundation (pinned base +
overlay, skill installed in the workspace for the engine), validates it in a Node sandbox, repairs failures, and
runs it as a preview container (FR-25, FR-26).

### 3.9 Contract & Integration

Derives the API contract before generation in dynamic mode, runs the frontend and backend lanes in parallel,
then checks the backend and switches the frontend from the mock API to the live backend (FR-23, FR-27).

---

## 4. Functional Requirements

### FR-01: Backend Specification Input

The system shall accept a structured JSON document called `BackendSpec`.

The specification must support:

1. Project metadata.
2. Technology configuration.
3. Database entities.
4. Entity relationships.
5. API endpoint definitions.
6. Request and response schemas.
7. Authentication configuration.
8. Authorization policies.
9. Business rules.
10. External integrations.
11. Background jobs.

12. Seed data (`seed[]`), loaded into preview databases only.

The initial MVP may support only a subset of these features, but the specification must be versioned to allow future extensions.

A BackendSpec may be written directly, drafted from a natural-language requirement (the engine produces a draft with explicit assumptions; the user reviews it before submitting), or imported from a Frontend-Agent site JSON (FR-20). The requirement is plain text or Markdown, typed or uploaded as a `.md` / `.txt` file (UTF-8, up to 64 KB); it is kept with the generation's artifacts.

**Acceptance Criteria**

- Accept valid BackendSpec JSON.
- Reject malformed JSON.
- Validate required fields and supported values.
- Detect duplicate entities, fields, and endpoint definitions.
- Detect invalid entity and relationship references.
- Return clear, structured validation errors.
- Preserve the original specification and its version.

### FR-02: Backend Specification Validation

Before code generation, the system must validate the specification using Pydantic or JSON Schema.

Validation must include:

- Supported technology stack.
- Field type compatibility.
- Relationship integrity.
- API path and HTTP method conflicts.
- Authentication references.
- Authorization policy references.
- Request and response schema integrity.
- Unsupported or ambiguous configurations.

Deterministic validation must run before invoking the code-generation engine.

### FR-03: Architecture Planning

The system must generate an internal implementation plan based on BackendSpec.

The plan must define:

- Project folder structure.
- Database models.
- API routers.
- Service modules.
- Repository or data-access modules.
- Authentication dependencies.
- Authorization dependencies.
- Business logic implementations.
- Required dependencies.
- Required tests.

The architecture plan must be saved as an intermediate artifact.

### FR-04: Database Generation

The agent must generate database definitions using SQLModel (SQLAlchemy 2.x), following `fastapi-skills`: pure Pydantic domain entities separate from ORM models.

Required capabilities:

- Table creation.
- Primary keys.
- Foreign keys.
- One-to-one relationships.
- One-to-many relationships.
- Many-to-many relationships.
- Unique constraints.
- Nullable fields.
- Default values.
- Database indexes.
- Enumerated values.

The system must generate Alembic migration files that create the database schema. Migrations are autogenerated from the models in the sandbox, not handwritten by the engine.

Generated migrations must be tested against an isolated PostgreSQL database.

### FR-05: REST API Generation

The system must generate FastAPI routers based on the operation definitions.

Initially supported operations:

- Create a record.
- Retrieve a record.
- List records.
- Update a record.
- Delete a record.
- Execute a custom business operation.

Supported API capabilities must include:

- Path parameters.
- Query parameters.
- Request bodies.
- Response models.
- Validation rules.
- Pagination.
- Filtering.
- Sorting.
- Standard HTTP status codes.
- Structured error responses.

Each generated operation must retain the stable `operationId` supplied by BackendSpec.

### FR-06: Authentication and Authorization

The MVP must support JWT-based authentication and resource ownership policies.

Required features:

- User registration.
- User login.
- Password hashing.
- Token generation.
- Token validation.
- Protected endpoints.
- Authenticated-user context.
- Role-based access control.
- Resource ownership checks.

Authorization must be enforced by the backend and must not depend on frontend validation.

Security-sensitive configuration, such as signing keys, must be provided through environment variables rather than generated hardcoded secrets.

Authentication and authorization code is written from tested plugin code (FR-34), not by the code engine. In dynamic
mode the generated frontend has sign-up and sign-in pages, sends the token on protected calls, redirects to sign-in on
401, and hides actions the signed-in user may not take.

### FR-07: Business Logic Generation

The agent must support declarative business rules.

Examples:

- Only a task owner can update the task.
- An order cannot be canceled after shipment.
- A completed task cannot return to an earlier status.
- An order total must equal the sum of its line items.

For predefined rules, the system should use deterministic generation where feasible.

For complex custom rules, the code-generation engine may generate use-case implementations.

Generated business logic must include tests covering both expected and rejected behavior.

When requirements are ambiguous, the system must record unresolved assumptions instead of inventing critical business policies.

In dynamic mode the frontend follows the predefined rules too (only allowed status changes are offered, locked
records cannot be edited), and the mock API enforces them with the same errors as the backend.

### FR-08: Code Engine Integration (Claude Code CLI, Antigravity CLI)

The system must invoke the selected engine CLI from a LangGraph node through the reusable adapter.

Required capabilities:

- Non-interactive execution.
- Structured JSON or streaming JSON output.
- Working-directory isolation.
- Maximum execution duration.
- Maximum agent turns.
- Capturing exit codes.
- Capturing standard output and errors.
- Execution cancellation.
- Normalized failure reporting.

The agent must provide the engine with:

- The `fastapi-skills` skill (copied into the workspace in the engine's skill/context location).
- Validated BackendSpec.
- Architecture plan.
- Code conventions.
- Permitted working directory.
- Current project state.
- Required implementation scope.
- Relevant validation errors during repair.

CLI commands must use subprocess argument arrays rather than interpolating untrusted strings into shell commands.

### FR-09: LangGraph Workflow

The workflow must include the following nodes:

1. `validate_spec`
2. `plan_architecture`
3. `generate_database`
4. `generate_backend` (also writes the template tests; no engine call writes tests, since v1.7)
5. `run_validation`
6. `repair_code`
7. `package_artifacts`

Required conditional behavior:

- Invalid specification → terminate with validation errors.
- Successful generation → proceed to testing.
- Failed validation → invoke repair node.
- Successful repair → run validation again.
- Maximum repair attempts reached → terminate with failed status and diagnostic report.
- All checks passed → package artifacts.

The initial repair limit should be configurable, with a default of three attempts.

### FR-10: Workflow State Management

LangGraph must maintain execution state containing:

- Generation ID.
- Original specification reference.
- Validated specification.
- Architecture plan reference.
- Workspace location.
- Current workflow step.
- Generation status.
- Repair attempt count.
- Validation results.
- Error summaries.
- Artifact references.

State must be persisted using a PostgreSQL-backed LangGraph checkpointer.

Large source files and logs should be stored as artifacts; graph state should contain references rather than entire file contents.

The workflow must support recovery after worker interruption. Recovery must avoid duplicating completed side effects or corrupting generated workspaces.

### FR-11: Automatic Validation

After generating backend code, the system must execute:

1. Python syntax checks.
2. Ruff linting.
3. Import and application startup checks.
4. Dependency consistency checks.
5. Alembic migration validation.
6. `fastapi-skills` conventions check (layer boundaries, `@Transactional`, DI aliases, exception hierarchy, router and model registration).
7. Pytest test suite.
8. FastAPI OpenAPI schema generation (from the started application).

Since v1.7 only the checks that prove the application starts (dependencies, syntax, migration upgrade to head,
startup) and that its API works (OpenAPI; one call per endpoint against the seeded database, which fails only on a
server error or no answer; the template tests when `BACKEND_TESTS` is on) are blocking. Ruff, the conventions check and migration details (downgrade round trip, index and
constraint names) are warnings: recorded and shown, never repaired, and they end the job
`COMPLETED_WITH_WARNINGS`.

The agent must only report validation as passed when the corresponding command actually succeeds.

If a blocking check fails, the captured errors must be forwarded to the repair node.

### FR-12: Automatic Repair

The agent must automatically attempt to fix generated code when validation fails.

The repair process must:

- Collect failing command output.
- Identify relevant files.
- Instruct the engine to apply targeted fixes that keep `fastapi-skills` conventions.
- Rerun failed validation checks and appropriate regression tests.
- Record the changes made.
- Respect the configured repair limit.

The process must stop if errors cannot be resolved within the configured limit.

### FR-13: LangSmith Tracing

LangSmith must trace the LangGraph workflow.

Each generation job must have a unique trace correlation identifier.

Tracing must capture, where available:

- Workflow name.
- Generation ID.
- Node execution duration.
- CLI invocation duration.
- CLI execution status.
- CLI-reported token usage and costs.
- Every model call inside a CLI session that the CLI reports in its structured output (model, tokens by kind,
  latency where available, cost reported or estimated from a configurable price table and labelled as estimated).
- Per-node, per-lane and per-generation rollups of wall time, engine time, sandbox time, model calls, tokens and
  cost, viewable in the Agent UI (Trace tab per generation, Usage & traces page across generations) with or
  without LangSmith.
- Validation results.
- Repair attempts.
- Errors.
- Final job status.

Engine CLI internal execution details are not assumed to be automatically instrumented by LangSmith. The adapter must explicitly record available CLI events and metadata as trace spans when deeper visibility is required.

Secrets and sensitive data must be removed or masked before tracing.

### FR-14: Generation Job API

The FastAPI application must expose the following endpoints:

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/generations` | Submit generation |
| GET | `/api/v1/generations/{id}` | Retrieve status |
| GET | `/api/v1/generations/{id}/events` | Stream progress |
| GET | `/api/v1/generations/{id}/artifacts` | List generated artifacts |
| GET | `/api/v1/generations/{id}/artifacts/{artifactId}` | Download an artifact |
| POST | `/api/v1/generations/{id}/cancel` | Request cancellation |
| GET | `/api/v1/generations/{id}/trace` | Span tree for the UI trace view |
| GET | `/api/v1/generations/{id}/preview` · POST `…/preview/{start,stop,restart,reset-db,touch}` · DELETE `…/preview` | Preview container lifecycle (FR-19) |
| POST | `/api/v1/specs/validate` · POST `/api/v1/specs` | Validate / store a BackendSpec |
| POST | `/api/v1/spec-drafts` · GET `/api/v1/spec-drafts/{id}` | Draft a spec from a requirement (async) |
| POST | `/api/v1/spec-imports/frontend` | Convert a Frontend-Agent site JSON to a BackendSpec draft (FR-20) |

A successful generation submission must return HTTP 202 with the generation ID.

The API must implement appropriate access control so that users can only access generation jobs and artifacts they are authorized to view.

### FR-15: Progress Monitoring

The system must track the current step and execution status.

Supported statuses:

- `PENDING`
- `RUNNING`
- `VALIDATING`
- `REPAIRING`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

Progress events must be accessible through Server-Sent Events (SSE).

Events must include timestamps, step identifiers, status changes, and useful non-sensitive diagnostic information.

### FR-16: Artifact Generation

After successful code generation, the system must produce:

- FastAPI source code.
- Dependency manifest (`requirements.txt`, `requirements-dev.txt`; `pyproject.toml` for ruff/pytest config).
- Database models.
- Alembic migrations.
- API routers.
- Pydantic request and response schemas.
- Service implementations.
- Test suite.
- `.env.ex` (template convention).
- README with local setup instructions.
- Dockerfile.
- OpenAPI JSON specification.
- Backend artifact manifest.
- Generation and validation report.

Source code must be packaged as a ZIP archive.

### FR-17: Integration Compatibility

A future Integration Agent will connect generated backends to frontend applications.

The Fullstack Generation Agent must expose sufficient metadata to support that integration without requiring the frontend agent to inspect all source files.

The manifest must contain:

- Backend framework, architecture (`fastapi-skills-hexagonal`) and template commit.
- Module list.
- API specification location.
- Stable operation identifiers.
- Authentication requirements.
- Environment variable requirements.
- Artifact locations.
- Generation version.
- Validation status.
- Unsupported or unresolved requirements.
- Frontend bindings (component → operationId), when the spec was imported from a site JSON.

The generated OpenAPI specification must accurately represent the implemented API, including security requirements, request bodies, response models, and status codes.

### FR-18: Agent UI

The system must provide a web UI that supports:

- Input by natural-language requirement, Frontend-Agent site JSON import, or BackendSpec JSON (editor with schema autocomplete and live validation).
- Live visualization of the LangGraph workflow steps, including repair loops, from the SSE stream.
- A trace view (nodes, engine invocations, tool uses, validation checks) with a link to LangSmith.
- Validation results, artifact downloads, manifest and source browsing.
- An OpenAPI explorer that sends test requests to the generated backend's preview container.
- A first step that asks which **mode** to generate: static website, dynamic web app, or backend API only (FR-21).
- FrontendSpec editing and review: page count and routes, theme (colours, fonts, radius, light/dark), the
  component catalogue, and the operations each page uses (FR-22); an assets panel to upload images (FR-28).
- A parallel view of the frontend and backend lanes, the frontend preview with a Mock API / Live API badge, and
  controls to re-check the backend or switch back to mocks (FR-27).
- An **App** view where the user uses the generated web app itself (embedded frontend preview talking to the live
  generated backend), with device sizes, a page jumper, and panels showing the backend calls and resulting data.
- Revisions of a generated frontend (FR-29): an inspect mode to comment on a section of the preview, a theme and
  content editor with live preview, and a revision history with diffs and restore.

Authentication tokens must be kept in httpOnly cookies, never in browser storage.

### FR-19: Preview Container

After a generation completes (and unless disabled by `options.deployPreview=false`), the system must build the generated Dockerfile and run the backend as its own container with its own PostgreSQL, run migrations, load seed data if present, and expose it on a local port.

- A preview failure must not change a COMPLETED generation's status.
- Previews must bind to `127.0.0.1` by default and must never be deployed beyond the local machine.
- Previews must support start, stop, restart, database reset, delete, an idle TTL, and a maximum number running at once.

### FR-20: Frontend Site JSON Import

The system must convert a Frontend-Agent site JSON (`collections` + `pages`) into a BackendSpec draft deterministically:

- One entity per collection, with field types inferred from its records.
- Operations derived from data-bound components (list with pagination, sort, search and filter; get by id; related lists).
- Collection records as `seed[]` data.
- Assumptions recorded instead of guessed (e.g. suggested enums or separate entities).
- A component → operationId bindings list kept for the manifest.

An optional engine-assisted refinement may improve the draft but must keep operationIds and bindings intact.


### FR-21: Generation Modes

The user must choose one mode per generation:

- `backend` — backend API only (FR-01 … FR-20, unchanged; the default for API clients).
- `static` — frontend only, content baked in, no backend and no contract.
- `dynamic` — frontend and backend generated in parallel from one API contract.

A generation has an overall status and one status per lane (`frontend`, `backend`, `integration`). In dynamic
mode a failed backend lane leaves the frontend usable on mocks and the overall status is
`COMPLETED_WITH_WARNINGS`; since v1.7 a failed frontend lane likewise leaves the backend running as its own
preview, with the overall status `COMPLETED_WITH_WARNINGS`. Neither lane cancels the other.

### FR-22: FrontendSpec

A versioned FrontendSpec JSON must describe the frontend to generate:

- `project` (name, mode, locales), `theme` (preset, colour tokens, typography, radius, light/dark, density),
  `layout` (shell, header, navigation, footer). Typography names fonts from a bundled set that loads offline and
  in the static export; another family is accepted with a warning that suggests the closest bundled one.
- `pages` (id, route, title, purpose, SEO, sections). Each section names a component and either static `content`
  or a `data` binding to a contract `operationId`, with loading, empty and error states.
- `components` (the catalogue used, with the shadcn primitives each relies on), `forms` (fields, validation,
  target operation, success behaviour), `content` and `assets` for static data. Each asset names its source
  (`placeholder`, `generate`, `upload:<id>`, `lucide:<Icon>`, or an `https://` URL; FR-28).

It must be validated structurally and semantically (unique routes, known components and pages, static mode
without bindings) and exposed as a JSON Schema for editors.

### FR-23: API Contract

In dynamic mode the system must derive an OpenAPI 3.1 contract deterministically from the BackendSpec plan before
generation starts (operations, operationIds, request/response schemas, list and error envelopes, examples from
seed data). Every FrontendSpec binding must exist in the contract (consistency check before any engine call). The
generated backend must conform to the contract; neither lane may change it.

### FR-24: Requirement Drafting for Frontend

From a natural-language requirement and a mode, the system must draft a FrontendSpec (and in dynamic mode the
matching BackendSpec), listing assumptions and unresolved questions for the user to acknowledge. The page list
must cover every user-visible feature of the requirement. The requirement is accepted as in FR-01 (text, `.md`,
`.txt`).

The draft's theme (colours, font pairing) and home page structure come from a **design direction** chosen from
curated design data for the kind of site described (not invented by the model), unless the requirement names brand
colours or fonts. The draft offers alternative directions that the user can switch between without an engine
call. Testimonials, client logos, figures and awards are never invented; sample content is listed as an assumption.

### FR-25: Frontend Generation

The system must generate a Next.js frontend on the `nextjs-skills` foundation:

- a pinned base project plus overlay (providers, layout primitives, runtime config, test setup, Dockerfile),
  with the skill installed in the workspace so the engine follows it;
- theme tokens from the FrontendSpec, one route per page, composite components with companion hooks, forms
  with RHF + Zod;
- in dynamic mode, a typed API client and a mock layer generated from the contract — no other network access;
- validation in an isolated Node sandbox (install, type check, lint, `nextjs-skills` conventions, build, route
  coverage, tests) with the same bounded repair loop as the backend.

### FR-26: Frontend Preview and Artifacts

A generated frontend must be downloadable (ZIP, FrontendSpec, plan, report) and run as a local preview container
(static: web server for the export; dynamic: Node server), bound to `127.0.0.1`.

### FR-27: Parallel Generation and Live-API Switch

In dynamic mode the frontend and backend lanes must run concurrently. Each lane's preview starts as soon as that
lane passes, without waiting for the other lane or for integration; the frontend starts with `MOCK_TEST_API=true`
unless the backend preview is already running. Once both previews run, the system must, in the background, check
the backend (lane COMPLETED, preview `/health` OK, OpenAPI matching the contract) and, if healthy, restart the
frontend preview with `MOCK_TEST_API=false` and `API_BASE_URL` set to the backend preview, then run live smoke
tests (every page renders, data-bound sections show backend data, forms submit). If the backend is not healthy, the frontend stays
on mocks with the reason recorded, and the user can re-check later.

### FR-28: Site Assets

Generated frontends (static and dynamic) must render the FrontendSpec's assets:

- `generate`: SVG illustrations drawn by the code engine in one batched call, using only the theme's colour
  variables so they follow light/dark mode and theme changes; converted to components deterministically.
- `upload:<id>`: images the user uploads (PNG, JPEG, WebP, SVG), type-checked by content, size-limited,
  re-encoded without metadata, owned by the user, copied into the project.
- `https://` links rendered as remote images (never fetched by the sandbox); `lucide:<Icon>` icons from the base.
- Every SVG must pass a safety and theme check (no scripts, event handlers, external references or raw colours)
  before it is built. An asset that still fails after repair falls back to a placeholder with a warning; it never
  fails the generation.
- Optionally, opt-in per generation and only with a configured provider, photo-like images from an image model,
  with their cost recorded.

### FR-29: Site Revisions and Feedback

After a frontend lane completes, the user must be able to request **revisions** of the generated frontend:

- **Spec edits** (theme, section content, navigation labels, assets) patch the FrontendSpec and regenerate the
  affected generated files without an engine call.
- **Feedback** on a page, section or component (typed, or by clicking it in the preview's inspect mode) is sent
  to the engine together with only that target's files; changes outside that scope are reverted.
- Each revision is validated with the frontend checks and repair loop, committed to the frontend repository,
  packaged and redeployed. A failed revision leaves the previous version and preview untouched.
- Revisions are listed with their changes and can be diffed and restored (restore creates a new revision).
- Revisions work after the workspace retention period (restored from the artifacts). In dynamic mode the
  contract stays fixed; changes that need it are reported as backend spec changes.

### FR-30: Fast Generation and Reuse

The code engine must be used only for what cannot be produced deterministically:

- Sections from the built-in catalogue (and layout nodes holding them) are rendered from the FrontendSpec by a
  section library shipped with the frontend overlay. Each section's content is validated against its props
  schema when the spec is validated. A static or dynamic spec that uses only the catalogue needs no engine call
  on the frontend lane.
- Custom components are generated with one engine call each, in parallel, and checked in isolation. Components
  that pass are cached by a content key (props schema, description, base and prompt versions); a cache hit
  reuses the files and skips the engine call and the component's own checks, while the site-level checks still
  run.
- Backend CRUD modules (model, repository, use cases, router, migration, tests) are generated from templates;
  the engine writes only custom operations and business rules.
- Library sections offer variants (a background per section, hero layouts, card styles) that switch between
  theme tokens only, and the library keeps a design checklist (one accent, one radius system, two font families,
  five type sizes per page, readable line length, short hero headlines, off-black and off-white in dark mode).
- Mechanical fixes (`ruff --fix`, `eslint --fix`, restoring generator-owned files) run before validation, and
  sandboxes start with the pinned dependencies installed.
- Engine calls avoided, cache hits and the time they saved are recorded in usage.

### FR-31: Real Photos

The platform supports photorealistic images generated through the Gemini image API (`gemini-3.1-flash-lite-image`):
- FrontendSpec assets can declare `source: "photo"`, with `prompt` and `style`, restricted to `kind: "image"`.
- During requirement drafting, photos are generated concurrently, post-processed to optimized WebP format, and stored as uploads attached to the draft owner (`upload:<id>`), retaining their prompts for regeneration.
- Collections and seed records can reference photo assets (`asset:<id>`), enabling dishes, products, or locations to display real-world imagery.
- Photo generation is cached by content hash to prevent redundant paid API calls. When photos are unconfigured or fail, assets safely fall back to placeholders with clear warnings.
- Users can preview, regenerate, or replace draft photos before generation.

### FR-32: API-Driven Dynamic Apps

> Superseded in part by FR-36 (1.10): dynamic apps are built by the app flow; journeys, journey tests and the
> generated Manage area no longer exist. Complete operation coverage, the mock API and the one-click flow remain.

Dynamic fullstack applications are driven by user journeys and complete API coverage:
- FrontendSpec defines `journeys` specifying step-by-step user interactions (`visit`, `open`, `submit`, `action`, `expect`) validating core product loops.
- BackendSpec incorporates domain operations needed by journeys with implementable rules, descriptions, and filters.
- Section components support interactive capabilities: row actions on tables and cards, edit forms with record preloading (`load`), action bars for mutations, list search/filter/sort controls, and API-driven statistics.
- Operations not covered by drafted journey screens are automatically exposed through an idempotent, generated **Manage** area (`/manage`), ensuring 100% operation coverage without requiring manual admin screen design.
- The mock API (MSW) supports custom domain operations, avoiding 501 responses during frontend development.
- Automated Playwright journey tests execute on mock fixtures during frontend validation, and against the live backend during integration.
- The UI offers a one-click generation flow from requirement to running application with automated transitions across `DRAFTING`, `PENDING`, and execution phases.

### FR-34: Backend Feature Plugins

Backend features beyond CRUD are generation-time plugins: tested source in the fastapi-skills layout, copied into the
generated project, recorded with its version in the manifest, and connected to the generated code through fixed hook
points. In dynamic mode a plugin also provides its frontend part and its mock API behaviour.

Plugins:
- JWT authentication; role and ownership authorization; predefined business rules (FR-06, FR-07).
- File storage: uploads and reads through signed URLs on an S3-compatible store (MinIO locally; S3 by configuration).
- Background jobs and events: a Postgres-backed queue with retries and schedules; events are recorded in the same
  transaction as the change that caused them, so nothing runs for a change that was rolled back.
- Email through SMTP (a console sender for development), sent as jobs; previews collect sent emails for inspection.
- Webhooks: signed outgoing deliveries with retries, signed incoming events handled exactly once.
- Payments through a provider port, starting with a fake provider that runs the full checkout and webhook flow
  without keys; real providers are added as adapters.

Integrations with no plugin are generated as a stub adapter and listed in `unresolved`. Previews run the generated
backend's job worker and use shared local storage and email services.

### FR-35: Forms That Fit the API

Every request field in the API contract states where its value comes from: the server, the signed-in user, the route,
a related record picked by its label, an upload, or the user's input. A generated frontend never asks the user for an
id. Before generation, each form is checked to have a working source for every required field; drafts that cannot be
repaired are rejected.

Generated forms validate with a schema for every form, use designed input components (calendar date and time pickers,
pickers for related records, switches, selects with readable labels, number limits), and show server rejections on the
field that caused them.

### FR-36: Dynamic App Frontend

In dynamic mode the frontend is generated by its own flow, separate from static sites:

- The draft is one model call that returns the BackendSpec and an app outline: the app's name, navigation, labels,
  the fields lists and details show, and the dashboard's figures. It does not design page layouts.
- Code builds every screen from the API contract and the outline on one component kit (app shell, lists, details,
  forms, actions, dashboard) that uses the design system's components, with loading, empty and error states. The
  design direction sets only the theme (colours, fonts, radius, density).
- Every operation of the contract is reachable from a screen or an action; the frontend lane makes no code-engine
  call.
- Changing the dynamic flow must not change static output; a golden test of the static examples proves it.
- Forms never ask for an id: each field is typed from the contract (calendar dates, choices, numbers with their
  unit or currency), a reference is picked from a searchable list of its records, and server-set fields are hidden.
- The backend plugins have screens: sign-in, sign-up and an account menu (tokens in the browser or, for production,
  an httpOnly cookie), navigation and actions filtered by role, status changes as actions, uploads with progress,
  pay and return pages, and many-to-many links. The mock API emulates them, so the app works before its backend.
- It is the only dynamic flow: a dynamic FrontendSpec that is not an app (`project.flow: "app"`) is refused.

### FR-37: App Design

A dynamic app is presented the way its data and its users need, while every binding stays the contract's:

- The draft writes a design brief from a fixed design space: an archetype (back office, catalogue, feed, workspace,
  booking, learning, storefront), a shell (sidebar, rail, top bar, top bar with tabs; drawer or bottom tabs on phones),
  a home (dashboard, feed, catalogue, agenda, bento), a view per entity (table, cards, media grid, feed, board,
  calendar) with field roles (media, title, subtitle, meta, badge, stat, price, avatar), filter styles and three looks
  (style recipes). Code checks each choice against the BackendSpec, replaces what does not fit with a note, and adds the
  list features a view needs (date ranges, date sorts) before the contract is built.
- The three looks are different style recipes (tokens and CSS on the kit's components): the requirement's own style
  words first, the product type's styles from the design data, calmer recipes for sensitive products, and a range from
  quiet to bold. The user picks a look, the shell and each list's view in the review, with no model call.
- When groups of roles use the app differently, each group gets an area with its own routes, shell, home and screens,
  planned from the operations its roles may call; sign-up leads to the first area, signing in to the role's area.
- What a role may see is a backend rule (a visibility policy): lists narrow and hidden records are 404 for that role
  and for signed-out callers, the entity's figures belong to the other roles, and the mocks apply the same rule.
- An app drafted in Japanese has Japanese labels, kit text, dates and a bundled Japanese face after the Latin one.
- Engine-written view slots (the shell, record cards) are an opt-in experiment (`APP_VIEW_SLOTS=engine`); a slot that
  loads data or renders a form is refused and the kit's view is used.

### FR-38: Draft Provider

_Implemented 2026-11-07 (Epic 24); the user's default is `antigravity` (`LLM_PROVIDER`)._

Every step that only needs an answer from a model (no files, no tools) runs on one provider, chosen by a setting and
per draft or generation:

- **Antigravity CLI, JSON mode:** one `agy` turn (`--print`, `--output-format json`, `--mode plan`) with the inline
  prompt, no tool permissions, an empty scratch directory, and the answer schema as structured output
  (`--json-schema`); the result is the same JSON envelope the API returns.
- **Claude Code CLI, JSON mode:** one `claude -p` turn (`--output-format json`, `--tools ""`, no MCP servers) with the
  inline prompt and the answer schema as structured output (`--json-schema`); on a subscription login (no per-token
  cost) without `--bare`, which accepts only an API key.
- **Gemini API:** one `generateContent` request with the answer schema as structured output (`responseJsonSchema`).
- Both are also checked against the answer schema in code; a schema error is one repair round. Usage is recorded per call
  (provider, model, tokens, cost source). Drafting is one-turn only; an agent-loop draft engine is refused.

### FR-39: Correct by Default: Roles, Ownership, Visibility, Demo Data

_Implemented 2026-11-07 (Epic 25)._

- A record tied to a person (any reference to the signed-in user's entity, directly or through a parent) is visible and changeable only by that
  person, by an assigned worker once assigned, and by the staff roles that manage it; other users of the same role get
  404. Records with no person reference stay as the draft says (a catalogue stays public).
- An action that belongs to one role is guarded by that role; owner actions (approve, decline, confirm) allow no staff
  bypass; a status with a flow changes only through its actions, never through the generic update.
- A record one role creates on behalf of a user of another role belongs to that user (a picker of users with that
  role); a user cannot create a record that belongs to someone else.
- The seed gives each demo user of a person role records of their own, and a second demo user per role.
- A draft the generation would refuse is refused by the draft check; the mocks agree with the contract on unique fields.

### FR-40: Business Workflows, Guided Tour and Evaluation

- **Discovery:** the main workflows are found from the requirement (values, actors, workflows marked core or later,
  branches for refusals and exceptions, the value each step delivers, a golden path) and given to the draft as a brief.
- **Expectations:** before generation, every core workflow step gets frozen expectations in business words: who may do
  it, who must be refused, the status after it, who may and may not see the record, its effects, the steps refused
  too early, the outcome per actor.
- **Binding:** each step is bound to the contract's operation, page and action, checked by code.
- **Guided tour:** the generated app shows each role its steps of the core workflows (react-joyride), once on first
  sign-in and on demand from the user menu.
- **Evaluation:** after the app is ready, the expectations are checked automatically against the running app as each
  role's demo user, with evidence per line and screenshots per step; the score is computed (met of all, met of
  decided). The result is a read-only Business tab; it never fails a generation, adds warnings or triggers repairs.

### FR-41: Stock Photos with Attribution (proposed, Epic 27)

- **Source:** with `IMAGE_PROVIDER=unsplash`, a photo the draft asks for (a short phrase of what it shows) is found
  through the Unsplash API by the agent's code (the LLM engines cannot fetch), in the orientation of its place.
- **Use:** the photo is hotlinked from Unsplash at the size of its place, never downloaded; its use is tracked once
  through Unsplash's download endpoint; repeated phrases are cached within the hourly request limit.
- **Credit:** every photo shows "Photo by <name> on Unsplash" with links, and the project README lists them.
- **Fallback:** with no result or no requests left, the place falls back as today (placeholder) and the draft goes on.

### FR-42: Interactive Guided Tour (proposed, Epic 28)

- **Doing, not reading:** a tour step that performs an operation waits until the user performs it on the real screen
  and the API reports success; steps that show data or another role's part keep a Next button.
- **Form help:** form steps walk the required fields and offer "Fill with an example" (values from the contract's
  success scenarios); the tour never submits a form or performs an action itself.
- **Ready records:** a step on a record opens one whose allowed actions include the step's action, or names the earlier
  step that makes one.
- **Progress:** a checklist per user and step that survives leaving; in demos, "Continue as <role>" follows a workflow
  across roles.
- **Check:** the evaluation plays each role's tour on mocks and reports each step as completed, skipped or stuck
  (information only, as FR-40).

### FR-43: Media Fields (proposed, Epic 29)

- **Types:** BackendSpec fields `video`, `audio` and `subtitles`, stored like `file` / `image`, with defaults limited to
  formats browsers play natively and sizes that fit media.
- **Subtitles:** a subtitle field on the media record, or a child entity with a language field for several languages;
  WebVTT and SubRip accepted.
- **Kit:** uploads with progress and cancel; native players styled by the theme with captions; posters, durations and
  play affordances in lists; audio that keeps playing across pages.
- **Samples:** mocks, seeds and the evaluation use small sample media of our own.

### FR-44: Design Plugins (Epic 30, done 2026-11-09)

- **Plugins:** every option of the app design space (shell, list view, detail view, home, filters, card, recipe, font
  pairing) is a folder with a descriptor (when to choose it, what it needs from the contract, its fallback) and its kit
  files.
- **One source:** schema enums, the drafting prompt's choices, the checks and the kit's dispatch come from the registry;
  an app contains only the plugins it uses.
- **Gates:** a plugin is offered only after passing the design checks (widths, schemes, recipes, contrast, keyboard,
  reduced motion and transparency, all states).
- **Choice:** the model chooses, code checks; equal candidates are picked by the draft's seed; the review can switch.
- **Measure:** apps are compared signed in, by structure and screens.

### FR-45: Sample Videos with Attribution (proposed, Epic 31)

- **Sources:** with `VIDEO_PROVIDERS`, a video the draft asks for (a short phrase and its place) is found by the
  agent's code: YouTube (Data API: embeddable, safe search, the app's language) for videos people watch, Pixabay
  (videos API: MP4 files under the Pixabay Content License) for hero backgrounds and seeded video fields; each within its limits,
  cached, and the other provider as the fallback.
- **Use:** YouTube videos are embedded through `youtube-nocookie.com`, loaded only when the user presses play; Pixabay
  files play in our own `<video>` (muted, pausable background loops that stay still under reduced motion; app players
  with our subtitles). Nothing is downloaded; the keys stay in the agent.
- **Credit:** the title and channel (YouTube) or the author (Pixabay) with links next to each video, and in the README.
- **Fallback:** no result, no quota or an unavailable video leaves the place as today and the draft goes on.

---

## 5. BackendSpec Input Example

```json
{
  "specVersion": "1.0",
  "project": {
    "name": "Task Management",
    "description": "Backend for task management"
  },
  "stack": {
    "framework": "fastapi",
    "database": "postgresql",
    "orm": "sqlalchemy",
    "migration": "alembic"
  },
  "entities": [
    {
      "name": "Task",
      "fields": [
        {
          "name": "id",
          "type": "uuid",
          "primary": true
        },
        {
          "name": "title",
          "type": "string",
          "required": true
        },
        {
          "name": "status",
          "type": "enum",
          "values": ["TODO", "IN_PROGRESS", "DONE"],
          "default": "TODO"
        }
      ]
    }
  ],
  "operations": [
    {
      "operationId": "task.create",
      "type": "crud",
      "action": "create",
      "entity": "Task",
      "method": "POST",
      "path": "/tasks"
    },
    {
      "operationId": "task.list",
      "type": "crud",
      "action": "list",
      "entity": "Task",
      "method": "GET",
      "path": "/tasks"
    }
  ]
}
```

This example represents the minimum required input for a simple CRUD backend. The full specification must support the additional fields described in Section 4.

---

## 6. Expected Generated Project Structure

Generated backends follow `.agents/skills/fastapi-skills` (template `longtk26/template-frameworks@feat/fastapi`, pinned commit, plus the agent's overlay):

```text
generated-backend/
├── src/
│   ├── main.py
│   ├── routers.py
│   ├── configs/{config.py, logger.py}
│   ├── libs/{database, decorators, exceptions, repository, rate_limit, security}/
│   └── modules/
│       ├── __init__.py                       # imports all ORM models
│       ├── health/
│       ├── shared/domain/entities/           # pure Pydantic entities
│       ├── shared/infrastructure/models/     # SQLModel tables
│       └── <module>/{ports, usecases, infrastructure, presenter}/
├── alembic/versions/
├── tests/
├── alembic.ini
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── Dockerfile
├── docker-entrypoint.sh
├── Makefile
├── .env.ex
├── CLAUDE.md
└── README.md
```

The generated project structure should remain consistent across generation jobs to simplify maintenance and integration.

---

## 7. Example API Request and Response

### Submit Generation

`POST /api/v1/generations`

```json
{
  "backendSpec": {
    "specVersion": "1.0",
    "project": {
      "name": "Task Management"
    },
    "stack": {
      "framework": "fastapi",
      "database": "postgresql",
      "orm": "sqlalchemy",
      "migration": "alembic"
    },
    "entities": [],
    "operations": []
  },
  "options": {
    "maxRepairAttempts": 3,
    "runTests": true,
    "generateDockerfile": true,
    "deployPreview": true,
    "engine": "claude_code"
  }
}
```

### Initial Response

```json
{
  "generationId": "gen_001",
  "status": "PENDING",
  "createdAt": "2026-10-23T03:00:00Z"
}
```

### Completed Generation Response

```json
{
  "generationId": "gen_001",
  "status": "COMPLETED",
  "currentStep": "package_artifacts",
  "validation": {
    "syntax": "passed",
    "lint": "passed",
    "tests": "passed",
    "migration": "passed",
    "conventions": "passed",
    "openapi": "passed"
  },
  "artifacts": {
    "source": "backend.zip",
    "openapi": "openapi.json",
    "manifest": "manifest.json"
  },
  "preview": {
    "status": "RUNNING",
    "url": "http://localhost:18000"
  }
}
```

Artifact names are identifiers resolved through authenticated artifact APIs, not unrestricted filesystem paths.

---

## 8. Non-Functional Requirements

### 8.1 Security

- Generated code must execute only within isolated workspaces.
- Each generation job must have its own isolated environment.
- The sandbox must not access production secrets or infrastructure credentials.
- Filesystem access must be restricted to approved directories.
- Container privileges and resource access must be limited.
- Network access must be restricted according to an explicit allowlist.
- CLI permissions must be restricted to approved operations.
- Generated projects must not automatically deploy to production. Local preview containers bind to `127.0.0.1` by default.
- Engine CLIs may only edit files in the job workspace (no shell); all generated code runs inside the sandbox.
- Input specifications, CLI instructions, generated code, and tool outputs must be treated as untrusted data.
- Uploaded files and generated SVGs must be validated by content and sanitised before they enter a project; the
  preview inspector accepts messages only from the agent UI's origin.

### 8.2 Reliability

- Jobs must survive ordinary API server restarts.
- Workflow checkpoints must be persisted.
- Worker failures must be detectable.
- Job cancellation must terminate associated child processes.
- Timeouts and retry limits must be configurable.
- Artifact creation must be idempotent where practical.
- Failed jobs must retain useful diagnostic reports.

### 8.3 Performance

- Generation requests must not block HTTP request handling.
- Multiple jobs must be supported with configurable concurrency.
- Each job must have configurable CPU, memory, execution-time, and CLI usage limits.
- The system must prevent unbounded output buffering and disk consumption.

### 8.4 Maintainability

- LangGraph nodes must be independently testable.
- CLI invocation logic must be separated from orchestration logic.
- BackendSpec must be schema-versioned.
- Prompts and code templates must be version-controlled.
- Generated code must follow consistent project conventions.
- Agent provider configuration must be replaceable.

### 8.5 Observability

- Every job must have a unique identifier.
- Logs must correlate with LangSmith traces.
- Workflow transitions must be recorded.
- CLI failures must be distinguished from code-validation failures.
- Trace and artifact retention periods must be configurable.

---

## 9. MVP Delivery Scope

### Phase 1 — Agent Foundation

- Docker Compose stack (PostgreSQL 18, Redis, API, worker, UI) and dev mode.
- FastAPI generation API.
- BackendSpec schema and validation.
- LangGraph workflow.
- Code engine adapters (Claude Code CLI; Antigravity CLI after a spike).
- Isolated workspace management.
- Generation status tracking.

### Phase 2 — Basic Backend Generation

- FastAPI project scaffolding from the `fastapi-skills` template.
- SQLModel models.
- Alembic migrations.
- CRUD routers.
- Pydantic schemas.
- Dependency generation.

### Phase 3 — Validation and Repair

- Python syntax validation.
- Ruff checks.
- Pytest execution.
- Database migration tests.
- LangGraph repair loop.
- Failure reports.

### Phase 4 — Observability and Artifacts

- LangSmith tracing.
- Persistent checkpoints.
- SSE progress streaming.
- ZIP packaging.
- OpenAPI export.
- Backend manifest.
- Preview containers.
- Agent UI (input, steps, trace, results, OpenAPI explorer).

### Phase 5 — Advanced Features

- JWT authentication.
- Role and ownership authorization.
- Custom business rules.
- File storage, background jobs and events, email, webhooks, payments (FR-34).
- Forms that fit the API (FR-35).
- Dynamic app frontend, separate from static sites (FR-36).
- Natural-language requirement drafting and Frontend site JSON import.
- Better automated evaluation.

### Phase 6 — Frontend Generation (v1.2)

- Generation modes (static, dynamic, backend) and per-lane statuses.
- FrontendSpec schema, validation and requirement drafting.
- Contract-first OpenAPI and frontend ↔ contract consistency check.
- Next.js frontend generation on `nextjs-skills`, Node sandbox validation, frontend preview.
- Parallel lanes, `MOCK_TEST_API` switch to the live backend, live smoke tests.

### Phase 7 — Site Images and Revisions (v1.3)

- Asset sources in the FrontendSpec; SVG illustrations from the code engine; asset safety checks with placeholder
  fallback; uploads and linked images; optional AI raster images.
- Revisions of generated frontends: spec edits, scoped feedback, inspect mode, history, diff and restore.

---

## 10. MVP Definition of Done

The MVP is complete when the following scenario works end to end:

**Given:** A valid BackendSpec describing a FastAPI CRUD application with at least two related entities.

**When:** The user submits the JSON to the Backend Generation API.

**Then:**

1. The API creates an asynchronous generation job.
2. LangGraph validates the specification and creates a plan.
3. The selected engine generates the FastAPI project on the `fastapi-skills` foundation.
4. The system validates the Python source code.
5. The system runs Alembic migrations against an isolated PostgreSQL database.
6. The system executes automated tests.
7. If tests fail, the agent attempts repairs within the configured limit.
8. If all checks pass, the system marks the job `COMPLETED`.
9. The system exports the project as a ZIP file.
10. The system exports an accurate OpenAPI specification.
11. The system exports a backend manifest containing stable operation IDs.
12. LangSmith records the orchestration trace and execution results.
13. The generated backend can be started independently using its documented setup commands.
14. The generated backend is running as a preview container and answers a CRUD round trip.
15. All of the above can be done from the Agent UI.

**Frontend extension (v1.2):** given a requirement for a small site with data (e.g. a shop catalogue), choosing
*Dynamic web app* drafts a FrontendSpec and BackendSpec, generates both in parallel, the frontend preview first
shows mock data and then the backend's data after the automatic `MOCK_TEST_API` switch; choosing *Static
website* for a brochure site produces a themed static site with the planned pages and no backend.

**Success criterion:** At least 90% of a defined benchmark set of valid, in-scope CRUD specifications must produce backends that pass all required automated checks without manual code changes. This is an initial project target, not a claimed current capability.

---

## 11. Future Integration Agent

The Integration Agent will be implemented as a separate system.

It will consume:

**Frontend Agent Output**
- UI component JSON.
- Pages and component metadata.
- Frontend action definitions.
- Data requirements.

**Backend Agent Output**
- OpenAPI specification.
- Backend manifest.
- Generated backend artifacts.
- Authentication metadata.

Its responsibilities will include:

- Matching frontend actions to backend operation IDs.
- Generating API client bindings.
- Connecting frontend forms and components to backend endpoints.
- Mapping API responses to frontend data models.
- Handling authentication integration.
- Identifying mismatches between frontend requirements and available APIs.
- Running integration tests.

The Integration Agent must not silently change backend API contracts without coordinating the required regeneration or explicit contract updates.

This agent is not part of the Fullstack Generation Agent MVP.

---

## 12. Final Deliverables

The project must provide:

1. A functioning Python/FastAPI Fullstack Generation Agent service.
2. A versioned BackendSpec schema with validation.
3. A LangGraph workflow supporting generation, validation, and repair.
4. Reusable code engine adapters (Claude Code CLI, Antigravity CLI).
5. LangSmith tracing integration.
6. Persistent generation job tracking.
7. Isolated execution environments.
8. Automated testing and error repair.
9. Generated FastAPI backend projects.
10. Standardized source, OpenAPI, and manifest artifacts.
11. API documentation and setup instructions.
12. Automated tests for the generation service itself.
13. An Agent UI and local preview containers for generated backends.
14. A Docker Compose setup that runs the whole system locally.
15. A versioned FrontendSpec schema, contract-first OpenAPI generation, and generated Next.js frontends
    (static and dynamic) with preview containers and the mock-to-live API switch.

