# Test doubles and testing-only switches

Everything in this list exists **for tests, demos or local development only**. None of it is used when a real
engine (`claude_code`, `antigravity`) generates a backend. If you add a new fake, stub, fixture-driven mode or
test-only flag, add it here and mark it at its definition.

## Fakes that run inside the product

| What | Where | Used by | Real-generation behaviour it replaces |
|---|---|---|---|
| **Fake engine** (`engine: "fake"`) | `agent-api/src/engines/fake_engine.py` | unit/workflow tests, UI demos, `make up` smoke runs | The LLM CLI. It replays scripted file writes (`FakeStep`s) and never calls a model. Shown in the engine list only when `ENABLE_FAKE_ENGINE=true`. Each run reports two scripted model calls (model `fake`, $0, 1000 in / 200 out tokens) so traces and usage rollups have data (Epic 8). |
| **Golden backend projects** | `agent-api/src/engines/golden/{two_entity,shop}/` | the fake engine's script (`demo_scenario` / `shop_demo_scenario`); tests (`tests/generation_helpers.golden_project`) | Hand-written, convention-correct implementations of **`examples/specs/two-entity.json` and `examples/specs/shop.json` only** (dispatched by `.bga/spec.json`'s `project.name`). The fake engine copies each one module per call and plants one syntax error in the last module's router (`tasks` or `contact_messages`) so the repair loop runs. With any other spec a fake run **fails validation** — that is expected. Since Story 17.6 the CRUD backend is written from templates, so these steps only run on the engine path (`options.crudFromTemplates=false`): `tests/workflow_helpers.submit`, `tests/test_parallel_generation.py` and `tests/test_generation_modes.py` submit with it to keep testing the engine, repair, cancel and resume plumbing. |
| **Static validation runner** | `StaticValidationRunner` in `agent-api/src/orchestrator/validation.py` | `SANDBOX_ENABLED=false` (the default in `tests/conftest.py`) | The sandbox pipeline. It only runs the syntax and conventions checks; every check that would execute code is reported `not_run`, never `passed`. |
| **Golden frontend** | `agent-api/src/engines/golden/frontend/corner_shop/` (`GOLDEN_FRONTENDS` in `fake_engine.py`) | the fake engine's `generate_frontend` / `repair_frontend` steps; `tests/test_frontend_scaffold.py`, `tests/test_parallel_generation.py` (the frontend lane's engine path) | Hand-written, nextjs-skills-conformant pages and components for **`examples/frontend-specs/shop-dynamic.json` only** (picked by the FrontendSpec's project name), used when its components have no `propsSchema` (`tests/generation_helpers.engine_path`); the example itself has them, so it is rendered (Story 17.3). `static-landing.json` and `project-tracker-dynamic.json` have none: the section renderer (Stories 17.2, 17.4) builds them without the engine, so their fake runs make no frontend engine call. The first `generate_frontend` call copies the whole golden frontend with one planted defect (a hard-coded colour in the shell, caught by the `conventions` check) so the repair loop runs; `repair_frontend` copies it again. Other FrontendSpecs need a real engine. |
| **Golden custom components** | `agent-api/src/engines/golden/frontend/custom_components/` (`GOLDEN_COMPONENTS`, `FakeStep.custom_component` / `plant_component_defect` in `fake_engine.py`) | the fake engine's `generate_custom_component` / `repair_custom_component` steps (Story 17.3); `tests/test_component_cache.py`, `tests/sandbox/test_frontend_sandbox.py` | The engine call that writes one custom component in its scratch copy. The fake reads `.bga/component.json` and writes the hand-written component of that name (`ProductGrid`, `ProductDetail`, `CartList` of `shop-dynamic.json`), or a plain generic component for any other name; `plant_component_defect` adds a hard-coded colour so the isolated repair runs. |
| **Draft fixtures** | `DRAFT_FIXTURES` / `DRAFT_DEFAULTS` / `write_draft_fixture` (`FakeStep.draft_fixture`) in `agent-api/src/engines/fake_engine.py` | the fake engine's `draft_spec` / `draft_frontend_spec` steps (Stories 2.4, 12.4); `tests/test_drafting.py`, the Requirement tab with engine `fake` | The engine call that drafts spec(s) from a requirement. The fake reads `.bga/draft.json` and the requirement, and copies **example specs** from `EXAMPLES_DIR` (the repo's `examples/`): a requirement mentioning "Corner Shop" gets `specs/shop.json` (backend) or `shop-dynamic.json` + `shop.json` (dynamic); "Northwind" gets `static-landing.json`; anything else gets `two-entity.json` (backend), `static-landing.json` (static) or `project-tracker-dynamic.json` + `two-entity.json` (dynamic). So `examples/requirements/*.md` each draft to their matching example. A "Refine with AI" draft returns the importer's base spec unchanged. It writes one assumption and (except static) one unresolved item, so the review step shows. `repair_spec` changes nothing. The draft does not reflect the requirement's content beyond the keyword. |
| **Golden drawings** | `agent-api/src/engines/golden/assets/*.svg` (`GOLDEN_ASSETS`, `FakeStep.golden_assets` / `unsafe_assets` in `fake_engine.py`) | the fake engine's `generate_assets` step (Story 15.2); `tests/test_site_assets.py`, `tests/sandbox/test_frontend_sandbox.py`, `make up` runs of the examples | The engine call that draws a job's SVG assets in its scratch directory. The fake reads `.bga/assets.json` and writes the hand-drawn SVG of each id (`hero`, `work-1` of `static-landing.json`; `empty-projects` of `project-tracker-dynamic.json`, all in theme variables), or a simple generic drawing for any other id. `unsafe_assets` writes a drawing with a `<script>`, an `onload`, an external link and a hex colour in each file instead, so the `frontend:assets` check, the repair and the placeholder fallback (Story 15.3) run. |
| **Static frontend validation runner** | `StaticFrontendValidationRunner` in `agent-api/src/orchestrator/frontend_validation.py` | `SANDBOX_ENABLED=false` | The Node sandbox pipeline. It only runs the conventions check; install, typecheck, lint, build, routes and tests are reported `not_run`, never `passed`. |

`FAKE_ENGINE_DELAY_SECONDS` (default 0.3) slows each fake step so the UI's live view can be watched.

## Test-only fixtures

| What | Where | Purpose |
|---|---|---|
| Fake CLI binaries | `agent-api/tests/fixtures/engines/bin/fake_claude`, `fake_agy` | Stand in for the real `claude` / `agy` executables in adapter tests (argv, stream parsing, timeouts). |
| Recorded Claude stream | `agent-api/tests/fixtures/engines/claude_stream_ok.jsonl` | Sanitized stream-json output for parser tests. |
| Recorded Antigravity stream | `agent-api/tests/fixtures/engines/agy_stream_ok.jsonl` | A real `agy` 1.4 run (a one-line ruff fix), host paths replaced by `/work/project`; model-call and cost parsing tests. |
| Recording LangSmith client | `agent-api/tests/tracing_fakes.py` (`RecordingLangSmithClient`) | Replaces `langsmith.Client` in `tests/test_tracing.py`: keeps every posted/patched run after the same hide hooks, so the span tree and secret masking are tested without sending anything. `tests/conftest.py` also forces `LANGSMITH_TRACING=false`, so no test run reaches LangSmith. |
| Invalid / base specs | `agent-api/tests/fixtures/specs/` | One invalid spec per validator error code. |
| Plan snapshots | `agent-api/tests/fixtures/plans/*.plan.json` | Expected planner output; refresh deliberately with `UPDATE_SNAPSHOTS=1`. |
| Frontend plan snapshots | `agent-api/tests/fixtures/frontend-plans/*.plan.json` | Expected frontend planner output per FrontendSpec example (Story 13.1); refresh with `UPDATE_SNAPSHOTS=1`. |
| Contract snapshots | `agent-api/tests/fixtures/contracts/*.contract.json` | Expected API contract per example spec (Story 12.3); refresh with `UPDATE_SNAPSHOTS=1`. |
| Exported OpenAPI documents | `agent-api/tests/fixtures/openapi/two-entity.{golden,engine}.json` | Real `openapi.json` exports of two generated two-entity backends (the golden project, and an engine-generated one); the contract conformance check is tested against them and against mutated copies. |
| Section-library spec | `agent-api/tests/fixtures/frontend-specs/section-library.json` | A static FrontendSpec that uses every section the renderer ships and every layout node, nested three deep (Story 17.2). `tests/sandbox/test_frontend_sandbox.py` builds it and renders every page with Playwright; `tests/test_section_renderer.py` checks the generated files. |
| Asset snapshots | `agent-api/tests/fixtures/assets-registry.ts`, `agent-api/tests/fixtures/assets/Work1Asset.tsx` | Expected asset registry and SVG → component conversion (Stories 15.1, 15.2); refresh with `UPDATE_SNAPSHOTS=1`. Hostile SVG samples (script, event handler, external link, `data:` image, CSS `url(https://…)`, billion laughs, an oversized path, hex colours) are inline in `tests/test_site_assets.py`. |
| Section props types snapshot | `agent-api/tests/fixtures/section-props.ts` | Expected `section_props_ts()` output (Story 17.1); refresh with `UPDATE_SNAPSHOTS=1`. |
| Frontend site snapshot | `agent-api/tests/fixtures/frontend/` | Importer regression input. |
| Fixing sandbox | `agent-api/tests/test_autofix.py` (`FixingSandbox`) | Records sandbox commands and rewrites chosen files when a `ruff` / `eslint` command runs, as the tools would, so the Story 17.5 auto-fix (which files reach the fixer, what is reported as fixed, the install-or-shared-node_modules choice) is tested without Docker. Real ruff and ESLint runs are covered by `tests/sandbox/test_sandbox_pipeline.py` and `tests/sandbox/test_frontend_sandbox.py`. |
| Passing sandboxes | `agent-api/tests/test_component_cache.py` (`PassingSandboxes`, `CommandTrackingSandboxes`, `BuildBreaksOnce`) | Every sandbox command succeeds, so the custom-component flow (one sandbox per component, the isolated checks, caching, eviction) is tested without Docker; `CommandTrackingSandboxes` records commands and timeouts and can simulate lint failures; `BuildBreaksOnce` fails the first site validation on a cached component. The real checks run in `tests/sandbox/test_frontend_sandbox.py`. Without any sandbox, components are used but never cached. |
| Loop component fixture | `agent-api/tests/fixtures/components/loop_component.tsx` | Test component with endless render loop (`useEffect` setting state synchronously from `useSectionRecords`); tests fail-fast lint and render loop timeout guard (Story 18.1). |
| Fake preview runtime | `agent-api/tests/preview_fakes.py` (`FakePreviewRuntime`) | In-memory stand-in for `DockerPreviewRuntime` / `DockerFrontendPreviewRuntime` so the preview lifecycle (start, limits, TTL, reconcile, commands) and live-API integration switch (`probe` with scripted `responses` for `/health`, `/openapi.json`, `/api/runtime-config` and contract operations, Stories 14.2–14.3) are tested without Docker. The real containers are covered by `tests/sandbox/test_preview_docker.py` and `tests/sandbox/test_frontend_sandbox.py`. |

`examples/` (repo root) is **not** test-only: the UI serves it for "Load example" / "Load sample". The golden
project above is written against `examples/specs/two-entity.json`, so change both together.
`examples/frontend-specs/project-tracker-dynamic.json` is the frontend for that spec: with the golden frontends
above, the fake engine runs both lanes of a `dynamic` job and the frontend lane of a `static-landing.json` job.
`examples/requirements/*.md` are sample requirements for those specs (input for requirement drafting, 2.4/12.4).

## Local-development defaults (never production values)

| What | Where | Note |
|---|---|---|
| Seeded users | `SEED_USERS` in `.env.example` (`admin@bga.local`, `user@bga.local`) | Created at API startup for local login. Replace or empty it for any shared deployment. |
| Test databases | `tests/conftest.py` | Uses `<DB>_test`, Redis db 15, a fixed JWT secret, in-memory rate limits, a temporary `ARTIFACT_ROOT` and a 1 s `PREVIEW_COMMAND_TIMEOUT_SECONDS`. |

## Opt-in test suites and flags

| Flag | Effect |
|---|---|
| `BGA_SANDBOX_TESTS=1` | Runs `tests/sandbox/` against the real Docker sandbox (needs Docker and `make runner`), including a real preview container built from `backend.zip` (needs network for its `pip install`). Workspaces go under `.data/test-sandbox/` because Docker Desktop only shares configured paths. |
| `BGA_KEEP_SANDBOX_DIRS=1` | Keeps those sandbox workspaces for inspection. |
| `BGA_LIVE_ENGINE_TESTS=1` | Runs `tests/live/` with the real CLIs (costs money, needs credentials). |
| `UPDATE_SNAPSHOTS=1` | Rewrites the plan snapshots. |

Sandboxes and previews are labelled with the agent instance (a hash of the database name, so the Docker worker and a host dev worker on the same database are one instance), so the test suite and the
Docker stack can share one Docker daemon without cleaning up each other's containers.
