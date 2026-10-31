# Story 18.9 — Engine context packs and pre-warmed modules

**Epic:** [18 — Generation speed](epic18_generation_speed.md) · **Requirements:** FR-30 · **Depends on:** 18.2, 18.3

Phase C: start after Checkpoint B.

## User story

As a user, I want the engine handed what it needs in one file instead of discovering it one read at a time, and
the sandbox's dependencies ready before the checks need them, so that each component call and each draft saves
minutes.

## Evidence (`gen_01M66QJWJGAZ7WMHZFR6TJ6KMR`, draft `808c82dc…`)

- `generate_custom_component` made **~30 sequential `read_file` turns (2.5–4 s each, ~120 s)** before writing:
  `.bga/component.json`, the render test, `renderer/site.ts`, `use-section-records.ts`, `bindings.ts`,
  `sections/QueryState.tsx`, `sections/format.ts`, `ui/card|badge|progress|button.tsx`, `content/site.json` in 4
  chunks, `lib/api/types.ts`, `lib/forms.ts`, the nextjs-skills `SKILL.md`, `sections/CardGrid.tsx`,
  `sections/DataTable.tsx`, `layout/Section.tsx`, `renderer/SectionRenderer.tsx`, `renderer/registry.ts`,
  `mocks/handlers.ts`, `mocks/fixtures.json`, `package.json`, `lib/utils.ts`, `assets/AssetImage.tsx`.
  `repair_custom_component` started over and re-read most of them.
- `draft_frontend_spec` read the JSON Schemas in 11 chunks: FrontendSpec 64 880 chars / 3 001 lines, BackendSpec
  21 722 chars / 1 028 lines (`spec_json_schema()`, `frontend_spec_json_schema()`).
- The custom-component sandbox spent **43 s** filling the shared `node_modules` volume (`shared node_modules
  ready`, `duration_ms 42803`), first use of that dependency set, and only after the engine call had ended:
  `CustomComponents._checks` calls `sandbox.shared_dependencies()` lazily (`custom_components.py:309`).

## Part 1 — Component context pack

1. New module `agent-api/src/orchestrator/context_pack.py` with a pure function
   `component_context(project: Path, component: dict, sample_props: dict) -> str` that builds Markdown **from the
   files in the scratch copy** (so it always matches the site, including its generated `bindings.ts`):
   - **Data API:** `src/components/renderer/site.ts` (types; whole file, it is small),
     `src/components/renderer/use-section-records.ts` (`useSectionRecords`, `recordHref`, `resolveParams`),
     `src/components/renderer/bindings.ts` (`useOperationMutation` and the operation ids it knows),
     `src/components/sections/format.ts` (`formatValue`, the format names), `src/components/sections/QueryState.tsx`
     (its props type and signature), `src/components/assets/AssetImage.tsx` (props) plus the asset ids from
     `src/assets/index.ts`.
   - **UI primitives:** for each name in the component's `uses` (all of `src/components/ui/*.tsx` when `uses` is
     empty: names only), the exported components and their props types.
   - **One example:** `src/components/sections/CardGrid.tsx` in full, as the pattern for a data section (the engine
     read it in the measured run).
   - **Mocks:** the operation ids and the first fixture record of each entity the component's binding uses
     (dynamic sites), not the whole `fixtures.json`.
   Extraction rule: a file under ~80 lines goes in whole; a longer one contributes its `export` declarations with
   their leading doc comment. Keep the pack under ~25 KB; log a warning if it is larger.
2. `_write_check_files` writes it to `.bga/context.md` next to `.bga/component.json`.
3. Prompts: `generate_custom_component/v3.md` and `repair_custom_component/v3.md` (from 18.2's v2) say: "Read
   `.bga/context.md` first: it has the APIs, types, primitives and an example you need. Read another file only if
   the pack lacks something." The repair prompt adds: "then read the component and the failures below; do not
   re-read the project." Bump `component_cache.PROMPT_VERSION`.
4. Tests: snapshot of the pack for the golden dynamic project's custom component (`UPDATE_SNAPSHOTS=1`);
   the extraction rule (short file whole, long file exports only); the size warning.

## Part 2 — Compact schemas for drafting

5. New pure function `schema_digest(json_schema: dict, title: str) -> str` (suggested home:
   `agent-api/src/modules/shared/domain/schema_digest.py`) that writes TypeScript-like types from the JSON
   Schema's `$defs`: one `type X = { field: T; optional?: T }` block per definition, enums as string unions,
   arrays as `T[]`, `oneOf`/`anyOf` as unions, the first sentence of each `description` as a `//` comment.
   Leave out numeric limits and patterns; the validator reports them with hints.
6. `drafting.write_inputs` also writes `.bga/frontend-spec.schema.md` and `.bga/backend-spec.schema.md` (keep the
   JSON Schemas: they stay the reference for details). Add their paths to the prompt context.
7. Prompts: `draft_frontend_spec/v5.md` (from 18.3's v4) and `draft_spec/v3.md` point to the `.schema.md` files
   first and to the JSON Schemas "only for details the summary leaves out". Switch `drafting.py`.
8. Tests: snapshot of both digests; a unit test that every `$defs` entry and every required field appears in the
   digest. Record both sizes in the Status note (target: FrontendSpec digest ≤ 15 KB).

## Part 3 — Pre-warmed shared modules

9. In `CustomComponents._generate`, right after the sandbox is created, start
   `asyncio.create_task(sandbox.shared_dependencies())`; `_checks` awaits that task instead of calling
   `shared_dependencies()` itself. Cancel it in the `finally` if the engine fails; log, do not raise, if it fails
   (the checks then install as today).
10. At the end of `scaffold_frontend` (when the job has sandboxes and `FRONTEND_SHARED_MODULES` is on), start the
    same fill for the project's dependency set as a background task kept on the job context, cancelled when the
    job ends. The fill is already guarded per key (`_modules_lock`, `_modules_ready` in
    `sandbox/docker_sandbox.py`), so later callers simply find it ready.
11. Tests with the fake sandbox: the dependency fill starts before the engine call returns; an engine failure
    cancels it; a fill failure does not fail the component.

## Acceptance criteria

- [x] Each custom-component scratch copy has a generated `.bga/context.md` (snapshot-tested), and the v3 prompts
      send the engine to it first.
- [x] Drafting writes `.bga/frontend-spec.schema.md` and `.bga/backend-spec.schema.md`; every `$defs` entry and
      required field is in them; the draft prompts point to them first.
- [x] The shared `node_modules` fill overlaps the engine call (and starts at scaffold).
- [x] Status note: pack and digest sizes; in the final measurement (approved real run), `read_file` turns before
      the first write per component call (before: ~30) and per draft call (before: 11 schema reads), and the
      component call's duration (before: 290 s).

**Status (2026-10-30):**
- **Part 1:** Implemented `agent-api/src/orchestrator/context_pack.py` with `component_context` and `extract_exports`. Generates `.bga/context.md` in each component scratch workspace before engine invocation. Bumped `PROMPT_VERSION` to `"v3"` in `component_cache.py` and created `v3.md` for `generate_custom_component` and `repair_custom_component`. Snapshot tested in `tests/test_context_pack.py` (`ProductGrid.context.md` is ~17.2 KB, < 25 KB limit).
- **Part 2:** Implemented `agent-api/src/modules/shared/domain/schema_digest.py` (`schema_digest`). Writes `.bga/frontend-spec.schema.md` and `.bga/backend-spec.schema.md` in `drafting.write_inputs`. Bumped draft prompts to `draft_frontend_spec/v5.md` and `draft_spec/v3.md`. Verified all `$defs` entries and required fields present in `tests/test_schema_digest.py`. Sizes: `FrontendSpec` digest is 7.5 KB (target ≤ 15 KB), `BackendSpec` digest is 3.1 KB.
- **Part 3:** Overlapped shared dependency fill in `CustomComponents._generate` via background task `fill_task = asyncio.create_task(sandbox.shared_dependencies())`, awaited in `_checks` with failure fallback to `pnpm install`, and cancelled in `finally` if the engine failed. Pre-warm also started at the end of `scaffold_frontend` and stored in `ctx.background_tasks` (cancelled at job end in `close_sandbox`). Verified with unit tests in `tests/test_prewarm_dependencies.py`.

## Verify

`make lint`, `make test`, `BGA_SANDBOX_TESTS=1 make test`, `make up` with the fake engine: static `static-landing`,
dynamic `project-tracker-dynamic` + `two-entity` COMPLETED; a fake draft in dynamic mode SUCCEEDED.
