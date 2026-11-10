# Fullstack Generation Agent — Product Backlog

Source: [requirements.md](../requirements.md) (v1.5, updated to match this backlog). Created 2026-10-23,
extended 2026-10-26 with frontend generation (Epics 12–14, Stories 9.7–9.8) and 2026-10-27 with site images and
revisions (Epics 15–16) and 2026-10-28 with fast generation (Epic 17) and 2026-10-30 with requirement files and
design direction (Story 12.6).

## What we are building

A local-first agent that turns a **natural-language requirement**, a **BackendSpec JSON**, a **FrontendSpec
JSON**, or an imported **Frontend-Agent site JSON** (e.g. [`revue-de-mode.json`](../examples/frontend/revue-de-mode.json))
into tested, running software. The user first picks a **generation mode**:

| Mode | Output |
|---|---|
| **Backend API only** | a FastAPI backend (fastapi-skills), running as its own container |
| **Static website** | a Next.js site (nextjs-skills) with content baked in — no backend |
| **Dynamic web app** | frontend **and** backend generated **in parallel** from one API contract; the frontend runs on mocks (`MOCK_TEST_API=true`) until the backend is healthy, then switches to the real API |

A Next.js UI covers mode choice, input and spec review (pages, theme, components), live workflow steps for each
lane, tracing, results, and an OpenAPI explorer that sends test calls to the running generated backend.

## Runtime topology (docker compose)

```
                         REST + SSE                       enqueue / pub-sub
  browser ─▶ agent-ui ─────────────────▶ agent-api ◀──────────────────────▶ redis
            (Next.js :3000)             (FastAPI :8000)                       ▲
                │                             │ SQL                          │ dequeue
                │ try-it (CORS)               ▼                              │
                │                        postgres ◀──── checkpoints ──── agent-worker
                │                     (jobs + LangGraph)                (LangGraph + engine CLIs:
                ▼                                                        claude / agy)
   ┌──────────────────────────┐                                               │ docker.sock
   │ preview-<genId>  :18xxx  │◀──────────── docker run (after COMPLETED) ────┤
   │ preview-db-<genId>       │                                               │
   │ preview-fe-<genId> :18xxx│  frontend preview (MOCK_TEST_API → backend)   │
   └──────────────────────────┘    ┌──────────────────────────┐               │
                                   │ sandbox-<genId>          │◀── docker run ┘
                                   │ sandbox-db-<genId>       │   (ruff / alembic / pytest;
                                   │ sandbox-node-<genId>     │    pnpm / tsc / next build / playwright)
                                   └──────────────────────────┘
```

- **compose-managed:** `postgres`, `redis`, `agent-api`, `agent-worker`, `agent-ui`.
- **worker-managed (dynamic):** per-job `sandbox-*` containers for validation, and per-generation
  `preview-*` containers that keep the generated backend running for clients.
- **Dev mode:** `make dev` runs only postgres + redis in Docker. api, worker, and ui run on the
  host with hot reload. `make up` runs the full stack and is how you verify.

## Conventions

| Area | Convention |
|---|---|
| Agent API + worker | `.agents/skills/fastapi-skills`: bootstrapped from the `feat/fastapi` template; hexagonal modules, SQLModel, `@Transactional`, `BaseException` hierarchy, DI type aliases |
| Agent UI | `.agents/skills/nextjs-skills`: pnpm, shadcn/ui, React Query, Zustand, RHF + Zod, cookie-based auth through Server Actions |
| Generated frontends | **nextjs-skills** (Epic 13): pinned Next.js base + overlay, theme tokens from the FrontendSpec, typed API client and MSW mocks generated from the contract |
| Generated backends | **Also fastapi-skills** (decision Q1). Each project starts from the `feat/fastapi` template at a pinned commit plus our *overlay* (tests, ruff, entrypoint), and the skill is copied into the workspace so the engine follows it. Hexagonal `src/modules`, SQLModel, Alembic, Pydantic v2, Pytest, Ruff |
| Code engines | Pluggable `CodeEngine` port: **Claude Code CLI** (default) and **Antigravity CLI** (`agy`) |
| Story DoD | ACs met · unit tests for new logic · `make up` still boots green · API changes documented in OpenAPI |

## Epics

| # | Epic | Req. phase | Stories |
|---|---|---|---|
| 1 | [Foundation & local stack](epic1_foundation/epic1_foundation.md) | Phase 1 | 4 |
| 2 | [BackendSpec schema, validation & drafting](epic2_backend_spec/epic2_backend_spec.md) | Phase 1 | 5 |
| 3 | [Code engine adapters (Claude Code + Antigravity)](epic3_code_engine_adapters/epic3_code_engine_adapters.md) | Phase 1 | 4 |
| 4 | [LangGraph workflow & generation jobs](epic4_workflow_and_jobs/epic4_workflow_and_jobs.md) | Phase 1 / 4 | 6 |
| 5 | [Backend generation](epic5_backend_generation/epic5_backend_generation.md) | Phase 2 | 5 |
| 6 | [Validation & repair](epic6_validation_and_repair/epic6_validation_and_repair.md) | Phase 3 | 3 |
| 7 | [Artifacts & preview container](epic7_artifacts_and_preview/epic7_artifacts_and_preview.md) | Phase 4 | 4 |
| 8 | [Observability & tracing](epic8_observability/epic8_observability.md) | Phase 4 | 4 |
| 9 | [Agent UI](epic9_agent_ui/epic9_agent_ui.md) | cross-phase | 10 |
| 10 | [Advanced generation: plugins, auth, rules, files, jobs, email, webhooks, payments](epic10_advanced_generation/epic10_advanced_generation.md) (planned, next; backend only since 2026-11-05) | Phase 5 | 12 |
| 11 | [Hardening, benchmark & release](epic11_hardening_and_release/epic11_hardening_and_release.md) | DoD §10 | 4 |
| 12 | [Generation modes, FrontendSpec & API contract](epic12_contract_and_frontend_spec/epic12_contract_and_frontend_spec.md) | Phase 6 | 6 |
| 13 | [Frontend generation (Next.js on nextjs-skills)](epic13_frontend_generation/epic13_frontend_generation.md) | Phase 6 | 5 |
| 14 | [Parallel generation & live-API switch](epic14_parallel_generation/epic14_parallel_generation.md) | Phase 6 | 3 |
| 15 | [Site images & illustrations](epic15_site_assets/epic15_site_assets.md) | Phase 7 | 5 |
| 16 | [Site revisions & feedback](epic16_site_revisions/epic16_site_revisions.md) | Phase 7 | 5 |
| 17 | [Fast generation: section renderer, component cache, templated CRUD](epic17_fast_generation/epic17_fast_generation.md) | Phase 7 | 6 |
| 18 | [Generation speed: fail fast, run in parallel, cache the slow builds](epic18_generation_speed/epic18_generation_speed.md) | Phase 7 | 13 |
| 19 | [Real photos and API-driven dynamic apps](epic19_photos_and_live_apps/epic19_photos_and_live_apps.md) | Phase 7 | 10 |
| 20 | [Design diversity: distinct directions, icons and motion](epic20_design_diversity/epic20_design_diversity.md) (in progress) | Phase 7 | 11 |
| 21 | [Designed pages: element trees for static and dynamic sites](epic21_designed_pages/epic21_designed_pages.md) (approved, next after 18.10) | Phase 7 | 7 (outline) |
| 22 | [Dynamic app frontend: screens from the contract, separate from static sites](epic22_dynamic_app_frontend/epic22_dynamic_app_frontend.md) (done 2026-11-06; the only dynamic flow) | Phase 5 | 8 |
| 23 | [App design: layouts that fit the data, looks to choose from, areas per role](epic23_app_design/epic23_app_design.md) (implemented 2026-11-06 on the fake engine; real tests next) | Phase 5 | 13 |
| 24 | [Draft provider: Antigravity or Claude Code (one-turn JSON), or the Gemini API](epic24_draft_provider/epic24_draft_provider.md) (done 2026-11-07) | Phase 5 | 4 |
| 25 | [App correctness: who may do it, who may see it, demo data that works](epic25_app_correctness/epic25_app_correctness.md) (done 2026-11-07, from the business-value lab) | Phase 5 | 6 |
| 26 | [Main business workflows: discovered, shown as a guided tour, evaluated](epic26_business_workflows/epic26_business_workflows.md) (proposed 2026-11-07) | Phase 5 | 7 |
| 27 | [Stock photos from Unsplash](epic27_stock_photos/epic27_stock_photos.md) (done 2026-11-08) | Phase 5 | 3 |
| 28 | [A tour you do: steps that wait for the action, help with forms, a checklist](epic28_interactive_tour/epic28_interactive_tour.md) (done 2026-11-09) | Phase 5 | 7 |
| 29 | [Media fields: video, audio and subtitles, uploaded and played](epic29_media_fields/epic29_media_fields.md) (done 2026-11-09) | Phase 5 | 6 |
| 30 | [Design plugins: a registry of layouts and looks that grows every day](epic30_design_plugins/epic30_design_plugins.md) (done 2026-11-09; guide: [design-plugins.md](../docs/development/design-plugins.md)) | Phase 5 | 8 |
| 31 | [Sample videos: YouTube embeds and stock video files](epic31_sample_videos/epic31_sample_videos.md) (done 2026-11-09) | Phase 5 | 5 |
| 32 | [Product patterns: screens that behave like the product](epic32_product_patterns/epic32_product_patterns.md) (done 2026-11-09) | Phase 5 | 8 |
| 33 | [Domain plugins: apps built from what each kind of product really is](epic33_domain_plugins/epic33_domain_plugins.md) (proposed 2026-11-10) | Phase 5 | 14 |

### Suggested delivery order

Build a thin end-to-end skeleton first, then fill it in. The `FakeEngine` (3.1) allows the UI and
workflow to be built before real generation works.

1. E1 → E2 (2.1–2.3) → E3 (3.1, 3.2) → E4 → **E9 (9.1–9.3)**: you can submit a spec and watch fake steps live.
2. E6.1 (sandbox) → E5 → E6.2–6.3 → E7: real generation, validation and repair, then artifacts and a running preview container.
3. E8 (8.1–8.4) → E9 (9.4–9.6, 9.10): tracing with per-node time / model calls / cost, the Usage & traces page, and the OpenAPI try-it explorer.
4. E2 (2.5 frontend JSON import, 2.4 requirement drafting) + E9 (Import tab), E3 (3.3 Antigravity), E10, E11.
5. **Frontend generation (added 2026-10-26):** E7.1 + E7.3 (backend preview, needed for the live switch) →
   E12.1–12.3 + 12.5 (FrontendSpec, modes, contract) → E13 (static mode first: 13.1–13.5 without the API
   client) → E13 dynamic parts (client + mocks) → E14 (parallel lanes, `MOCK_TEST_API` switch, live smoke) →
   E12.4 + 2.4 (requirement drafting for both specs) → E9.7–9.9 (mode choice, parallel view, App tab).
6. **Site images and revisions (added 2026-10-27):** 9.7a (spec editor, both epics build on it) → E14 →
   E15 (15.1–15.3 generated SVGs, then 15.4 uploads; 15.5 only if asked) → E16 (16.1 revisions → 16.2 spec
   edits → 16.3 feedback → 16.4 inspect mode → 16.5 history). E11 (hardening & release) stays last.
7. **Fast generation (added 2026-10-28):** E17 before E15/E16, since both get simpler on the renderer:
   17.5 (auto-fix, pre-installed deps) → 17.1 → 17.2 (static, no engine call) → 17.4 (dynamic data sections;
   moved before 17.3 on 2026-10-29: the custom components in the examples are all dynamic data components) →
   17.3 (custom components + cache) → 17.6 (backend CRUD from templates) → 17.7 (fonts, section variants).
8. **After Epic 17 (agreed 2026-10-29):** 17.8 → 17.7 → E15 → 2.4 + 12.4 (plain text for static and dynamic) →
   9.7b → E16 → E10 → E11.
9. **Re-planned 2026-10-30 (requirement first, then E15 and E16):** 2.4 + 12.4 + 9.2 Requirement tab + 9.7b
   (plain text, `.md` or `.txt` for backend, static and dynamic) → 17.7 (fonts, variants, design checklist) → 12.6
   (design direction from UI UX Pro Max data) → E15 → E16 → 17.8 → E10 → E11.
10. **Planned 2026-11-02 (agreed):** E20 (design diversity: distinct directions, icons, motion) before
   E16; E16 is then revised to edit the new theme fields and to offer "try another direction" as a spec edit.
   Research: [docs/research/design-diversity.md](../docs/research/design-diversity.md).
11. **Agreed 2026-11-03 (re-planned the same day):** after Epic 20's Checkpoint D fixes,
   [18.10](epic18_generation_speed/story18.10_api_drafts.md) (drafts and repairs through the Gemini API, no agent loop)
   → [Epic 21](epic21_designed_pages/epic21_designed_pages.md) (pages as element trees for static and dynamic sites,
   aggregates without the engine; starts with 21.1, the measurement) → [18.11](epic18_generation_speed/story18.11_lean_validation.md)
   (lean validation) → 20.10 (Japanese fonts and typesetting) → 20.7 and Epic 20's final check.
   [20.11](epic20_design_diversity/story20.11_app_pages.md) is mostly superseded by Epic 21: its route-order fix (done
   with 18.10) and app theme limits stay.
12. **Re-planned 2026-11-04 (the user's two priorities first):**
   [18.12](epic18_generation_speed/story18.12_lane_previews_first.md) (each lane's preview starts the moment the lane
   passes, on any worker; the switch to live and the live checks run in the background; lanes no longer cancel each
   other) → [18.11](epic18_generation_speed/story18.11_lean_validation.md), re-scoped (no `generate_tests` node, only
   template tests; validation proves the app starts and its API works) →
   [18.13](epic18_generation_speed/story18.13_backend_context_pack.md) (the rest of the old 18.11: `complete_backend`
   context pack, parallel modules, frontend warnings) → 20.10 → 20.7 and Epic 20's final check.
13. **Re-planned 2026-11-04 (Epic 10 is the next phase):** 18.13 →
   [Epic 10](epic10_advanced_generation/epic10_advanced_generation.md), re-scoped around generation-time plugins, in
   four checkpoints with a review after each: **A** forms (10.0a form kit, 10.0b field sources and references; 10.0a
   can run alongside 18.13) → **B** plugin framework, JWT auth, roles and ownership, rules → **C** file storage (MinIO),
   background jobs and events, email → **D** webhooks, payments (fake provider first) → **E** capacity / no-overlap / unique-together rules, many-to-many and
   one-to-one relations. 20.10, 20.7 and Epic 20's final check move after Epic 10; Epic 11 stays last. Candidate epics
   after Epic 10: teams and organisations; backend revisions (schema change → clear the preview database and run the
   migrations again from empty, no data migrations).
14. **Re-planned 2026-11-05 (backend first, then a separate dynamic frontend):** Epic 10 becomes backend and contract
   only, in five checkpoints: **A** contract and framework (10.0b field sources and parent summaries, 10.1 plugin
   framework) → **B** JWT auth, roles and ownership, rules → **C** file storage, jobs and events, email → **D** webhooks,
   payments → **E** capacity / no-overlap / unique-together, many-to-many and one-to-one. Then
   [Epic 22](epic22_dynamic_app_frontend/epic22_dynamic_app_frontend.md): dynamic mode gets its own frontend flow (one
   draft call, screens built by code from the contract on one shadcn app kit, no page trees), with the form kit (was
   10.0a), the reference pickers (frontend half of 10.0b) and every plugin's frontend half (22.7); static mode is
   unchanged, guarded by a static golden test (22.1). Then 20.10, 20.7 and Epic 20's final check; Epic 11 stays last.
15. **Proposed 2026-11-08 (after Epics 24–27), for review:**
   [Epic 28](epic28_interactive_tour/epic28_interactive_tour.md) (the tour waits for the user's action, helps with
   forms, keeps a checklist; the walker plays it) → [Epic 29](epic29_media_fields/epic29_media_fields.md) (video, audio
   and subtitle fields, uploaded and played) → [Epic 30](epic30_design_plugins/epic30_design_plugins.md) (design plugins:
   one folder per layout or look, generated enums, prompt lists and kit dispatch; signed-in measurement first; media
   layouts after 29.3) → [Epic 31](epic31_sample_videos/epic31_sample_videos.md) (sample videos: YouTube embeds and Pixabay
   stock video files, credited; 31.3 for sites can start after the two providers). After Epic 30, design plugins are added one at a time
   with [the guide](../docs/development/design-plugins.md).
16. **Proposed 2026-11-09 (after Epics 28–31), for review:**
   [Epic 32](epic32_product_patterns/epic32_product_patterns.md) (product patterns: how each kind of product behaves,
   as a design plugin kind the screen planner reads; UX checks measured first; `back-office` is today's screens, `feed`
   and `storefront` the first new patterns). The other archetypes' patterns follow one at a time after the epic.

### Status (2026-10-30)

| Epic | State |
|---|---|
| 1, 2 (2.1–2.3, 2.5), 3, 4, 5, 6 (6.1–6.2) | done (merged to `main`); 6.3 repair loop works on real failures |
| 7 | done (merged to `main`) |
| 8 | done (draft jobs accounted since 2026-10-30) |
| 9 | 9.1–9.10 done (9.6 auth helper waits for Epic 10; 9.2's "Refine with AI" button open) |
| 12 | 12.1–12.6 done (12.6 design direction from UI UX Pro Max's data, 2026-10-30) |
| 13 | done |
| 14 | done (14.1 parallel lanes, 14.2 live-API switch + `/integration/{recheck,use-mocks}`, 14.3 live health check; contract probe and Playwright smoke removed 2026-11-06) |
| 17 | 17.5, 17.1, 17.2, 17.4, 17.3, 17.6 done (auto-fix, shared node_modules; typed content and layout nodes; static sites ~44 s and dynamic frontends rendered without the engine; parallel custom components & component cache; backend CRUD from templates, dynamic shop 59 s with 0 engine calls); 17.7 done 2026-10-30 (22 bundled fonts, section variants, design checklist); 17.8 (custom component layout, found on the first cached shop run) open |
| 2.4 | done 2026-10-30 (requirement drafting for backend, static and dynamic; with 12.4, 9.2 Requirement tab, 9.7b) |
| 15 | 15.1–15.4 done 2026-10-30 (drawn SVGs, asset checks with placeholder fallback, uploads and links); 15.5 only if asked |
| 20 | Checkpoints A, B and C done 2026-11-02 (diversity report and baseline; hero layouts, section forms, rhythm, tone tokens, 30 fonts, seven new sections; direction cards with the difference test, content-led home pages, stock-phrase checks, dynamic apps checked on the mock API); Checkpoint D done 2026-11-03 (icons in the site's set, motion presets with a signature moment); 20.10 Japanese fonts added 2026-11-03 (after spec-drafting speed); 20.7 next; real-engine numbers on the final check |
| 18.10, 21 | implemented 2026-11-04 (drafts through the Gemini API, one request per step; designed pages as element trees for static and dynamic sites, aggregates from templates); merged to `main`; 21.1's paid measurement open |
| 18.12, 18.11 | done 2026-11-04 (merged to `main`): each lane's preview starts when the lane passes, from any worker, integration in the background, lanes no longer cancel each other; no `generate_tests` step, validation blocks only on "starts" and "API works" (smoke call per custom operation), lint / conventions / migration details are warnings; plus Epic 21 fixes (old Lucide names, Metric `fn`, sites without trees). Real-run timings and 18.13 open |
| 18.13 | done 2026-11-04, merged to `main` 2026-11-05: `complete_backend@v5` carries a context pack per module (no file reads), modules run in parallel in scratch copies with a conflict rerun, frontend conventions and test-only type errors are warnings; the paid timing open |
| 10 | re-planned 2026-11-04, backend only since 2026-11-05: 12 stories in checkpoints A–E (contract and framework, core plugins, infrastructure, integrations, domain shapes); in progress on `feat/epic10-backend-plugins`: 10.0b, 10.1 (Checkpoint A), 10.2–10.4 (Checkpoint B: JWT auth, roles and ownership, business rules) committed; 10.5 (file storage), 10.6 (jobs and events), 10.7 (email) committed (Checkpoint C); 10.8 (webhooks), 10.9 (payments) committed (Checkpoint D); all 12 stories done 2026-11-05 (Checkpoints A–E); open items in the stories' deviations; branch under review |
| 22 | done 2026-11-06: 8 stories in checkpoints A–D (the flow, forms, plugin frontends, switch-over); the legacy dynamic flow is removed (22.8) |
| 23 | implemented 2026-11-06 on `feat/epic23-app-design` (gate 23.0 with 10 real Gemini drafts, then 23.1–23.12 on the fake engine, no paid call, per the user); the real tests (Gemini drafts, live backends, app walks) and the review are next |
| 24, 25, 26 | 24 done 2026-11-07 (`LLM_PROVIDER=antigravity`: one-turn `agy` JSON drafts, $0 on the account login); 25 done 2026-11-07 (access rules by default; its live re-check moves to 26.7); 26 in progress on `epic-24-25-26`. Proposed 2026-11-07 from the business-value lab (`lab/business-value/`: FixPoint, BuyRight, HomeFix). Order: 24 (draft provider, for cost), 25 (app correctness; 25.1 first), 26 (business workflows, tour, evaluation tab) |
| 27 | done 2026-11-08 (stock photos from Unsplash, hotlinked and credited) |
| 28, 29, 30, 31 | proposed 2026-11-08, for review (interactive tour, media fields, design plugins, sample videos) |
| 11, 16 | open (16 to be revised after Epic 20) |

### Next up (re-planned 2026-10-30)

Done since the last plan: Epic 17's main stories (17.5, 17.1, 17.2, 17.4, 17.3, 17.6): static sites ~44 s with no
engine call; the dynamic tracker and shop ~1 min with no engine call once custom components are cached (before:
25–40+ min).
Change on 2026-10-30: the **requirement comes first** (plain text, a `.md` or a `.txt` file, for backend, static and
dynamic), then Epics 15 and 16. Drafts should look designed, so the draft also gets a **design direction** from UI UX
Pro Max's data (12.6), and the section library gets fonts, variants and a design checklist from Taste Skill's rules
(17.7). Research: [docs/research/design-skills.md](../docs/research/design-skills.md).
Work in this order; start each item in a fresh session ("implement stories 2.4 and 12.4", …).

| # | Item | What the user gets | Why at this point |
|---|---|---|---|
| 1 | ~~**2.4 + 12.4, with the 9.2 Requirement tab and 9.7b**~~ done 2026-10-30 | A requirement typed or uploaded (`.md` / `.txt`) → draft BackendSpec (backend), FrontendSpec (static) or both (dynamic), with assumptions and unresolved items to acknowledge, editable before submit | Users no longer need to write JSON. Drafts aim at the typed section catalogue (17.1) and the CRUD templates (17.6), so they build with no engine call. Dynamic drafts must pass the pair consistency check |
| 2 | ~~**17.7**~~ done 2026-10-30 | Fonts that load, section variants, section library checked against the design checklist | 12.6 needs fonts that really load and variants to choose between |
| 3 | ~~**12.6**~~ done 2026-10-30 | Each draft gets a theme, font pairing and home page structure suited to its kind of site, with 2 alternatives to switch between | Colours and fonts come from curated, contrast-checked data instead of model-invented values |
| 4 | ~~**Epic 15** (15.1–15.4)~~ done 2026-10-30 | Real images: engine-drawn SVGs in theme colours, uploads, links (15.5 only if asked) | Replaces the placeholders; assets are section props on the renderer |
| 5 | **Epic 16** | Revisions: theme and content editors, click-to-comment, history and restore | Refines a first version: spec edits re-render without the engine |
| 6 | **17.8**, **Epic 10**, then **Epic 11** | Custom components that fit the page; auth, roles and business rules; hardening, benchmark, release | Epic 11 stays last |

Open decisions along the way:
- **Generation time leaves out the draft (noted 2026-11-02, not planned yet).** The user sees the time of a
  generation as `started_at` → `finished_at` (generations table, header timer, trace wall time), and `started_at` is
  set when the runner picks up the generation (`orchestrator/runner.py`), after the spec is drafted. With one click
  (19.10) the user waits for the draft too, so the shown time is shorter than the real wait. Wanted: the total time
  includes the draft spec time. Drafts already record `spec_drafts.started_at` / `finished_at` and `usage`, and a
  one-click draft is linked by `spec_drafts.generation_id` (reviewed drafts by `options.draftId`). Show draft,
  generation and total separately; the total is draft time + generation time, not counting time the draft waited for
  review (`NEEDS_REVIEW` or the user's review before Generate). Same for the trace summary and the Usage page
  (`avgWallMsPerCompleted`). Epic 20's diversity report needs the draft time as well.
- 17.8 (custom components that fit the page) moved after Epic 16 (2026-10-30). Dynamic drafts that need custom
  components (e.g. a shop's product grid) will show its layout faults until then. It can move up if they show up
  in the first drafted dynamic sites.
- 17.7 placed before 12.6 (2026-10-30): the design direction picks fonts and variants, which only show once 17.7
  loads the fonts and adds the variants.
- Faulty RAM is suspected on the dev machine (Docker Desktop crashes, single-bit corruptions in built images,
  2026-10-29): run a memory test before trusting further Docker results.
- One paid real-engine run (Claude Code) on `shop-dynamic` to confirm real engines handle the frontend lane and to
  record a timing baseline for Epic 17 (so far the frontend lane has real timings from Antigravity only). Only
  when the user asks.

## Decisions (2026-10-23 review)

| # | Decision | Impact |
|---|---|---|
| Q1 | Generated backends use **fastapi-skills**, the same foundation as the agent service | Epic 5 rewritten around template + overlay. Paths in 3.4, 6.x, 7.x and 10.x follow `src/modules/…`. A new `conventions` validation check enforces the skill's 6 pillars. |
| Q5 | The UI imports Frontend-Agent site JSON and generates an example BackendSpec from it | New Story 2.5 (converter), Import tab in 9.2, optional `seed[]` in BackendSpec (2.1) so previews serve the site's real records |
| Q8 | `git init` done at the repo root (branch `main`, `.gitignore` added) | – |
| PG | **PostgreSQL 18** everywhere (agent DB, sandbox DB, preview DBs) | Volumes mount at `/var/lib/postgresql` (PG 18 image layout) |
| FE (2026-10-26) | **Frontend generation is in scope**: modes `backend` / `static` / `dynamic`; dynamic generates frontend and backend in parallel from a contract, frontend on mocks until the backend is healthy (`MOCK_TEST_API` switch); the UI asks static vs dynamic first | New Epics 12–14, Stories 9.7–9.8; requirements v1.2 (FR-21…FR-27); §1.3 no longer excludes frontend generation |
| Q4 (2026-10-26) | Antigravity also supports the **`agy` account login** (`ANTIGRAVITY_AUTH=account`): works headless on the host (dev worker); in Docker it reports unavailable, use `GEMINI_API_KEY` or ADC there | Story 3.3 updated; account login verified; own turn/time limits (`ANTIGRAVITY_MAX_TURNS`, `ANTIGRAVITY_TIMEOUT_SECONDS`) |
| Q6 (2026-10-26) | Backend previews **start automatically** on COMPLETED; 2 h idle TTL, max 3 running, host ports 18000–18099 bound to `127.0.0.1` | Epic 7 (7.3, 7.4) defaults |
| Q12 (2026-10-26) | The frontend lane uses our own **FrontendSpec** (easier for the agent); the Frontend-Agent site JSON stays an *input* (2.5), no converter | Epic 12 as written |
| Q13 (2026-10-26) | **v0-style preview:** when a generation completes, the user sees the generated site running and can click through it inside the agent UI (App tab, real backend in dynamic mode). Dynamic: Node standalone server (runtime `MOCK_TEST_API` switch); static: nginx serving the export | 13.5, 9.9 (auto-opens the App tab on completion) |
| Q14 (2026-10-26) | Backend lane fails in dynamic mode → **`COMPLETED_WITH_WARNINGS`** (frontend usable on mocks) | 14.1, 14.2 |
| Q11 (2026-10-26) | Frontend base = **`pnpx create-next-app`** exactly as nextjs-skills prescribes (versions pinned by the lock file) + our overlay; no template repo | 13.2 |
| IMG (2026-10-27) | Site images: **SVG illustrations drawn by the code engine** in the theme's colour variables (no new provider or key); uploads and links for photos and logos; AI raster images only as an optional, opt-in provider; icons from `lucide-react` | New Epic 15; FrontendSpec `assets[]` gains sources `generate` / `upload:` / `lucide:` (additive, still 1.0) |
| REV (2026-10-27) | Feedback becomes **revisions**: small jobs on the finished frontend, one commit each, validated and redeployed; spec edits (theme, content, assets) need no engine call; frontend only; the contract stays fixed | New Epic 16; artifacts gain `frontend.bundle` and per-revision ZIPs |
| SPEED (2026-10-28) | Generation is made faster by **doing less with the engine**: catalogue sections are rendered from the FrontendSpec by a section library in the overlay, custom components are generated in parallel and cached by content once validated, backend CRUD comes from templates | New Epic 17; requirements v1.4 (FR-30) |
| Q18 (2026-10-28) | FrontendSpec nesting: **only layout nodes** (`Columns`, `Stack`, `Grid`, `Tabs`) hold sections as children, **depth ≤ 3**; no element trees. Sections lay out their own insides, so layout nodes only arrange sections | 17.1 |
| Q19 (2026-10-28) | **Keep the code engine** for custom components (one call each, in parallel, cached) | 17.3 |
| Q20 (2026-10-28) | Component cache is **shared by all users, exact key only**; no similarity matching | 17.3 |
| REQ (2026-10-30) | The requirement is **plain text or Markdown**, typed or uploaded as `.md` / `.txt` (UTF-8, ≤ 64 KB), for all three modes; one draft endpoint (`POST /spec-drafts`, `mode: backend\|static\|dynamic`). PDF / DOCX are not accepted | 2.4, 12.4, 9.2, 9.7b; requirements v1.5 (FR-01, FR-24) |
| DESIGN (2026-10-30) | Drafts take their design direction from **UI UX Pro Max's data** (MIT; CSVs vendored at a pinned commit; our own ranker, their scripts not run): product type → palette, font pairing, section order, anti-patterns. **Taste Skill** is used only as rules (17.7 checklist, drafter copy rules), not as a step: its random art direction, browser critique loop (30–45 min a build) and photo fetching do not fit a no-engine renderer | New Story 12.6; 17.7 font set and checklist; `theme.direction` in FrontendSpec (additive, still 1.0) |
| LANES (2026-11-04, default, please confirm) | In dynamic mode each lane delivers on its own: its preview starts when it passes, integration runs in the background. A **failed frontend lane no longer cancels or fails the backend**: the backend finishes and previews, overall `COMPLETED_WITH_WARNINGS` (mirror of Q14). The integration-wait watchdog that cancelled a slow backend is removed | 18.12; FR-21, FR-27 (requirements v1.7) |
| TESTS (2026-11-04) | The backend lane has **no `generate_tests` step**: only template tests, written with the code; validation blocks only on "starts" (deps, syntax, migration upgrade, startup) and "API works" (OpenAPI, template tests, one smoke call per custom operation); lint, conventions and migration details are warnings | 18.11; FR-09, FR-11 (requirements v1.7) |
| PLUGINS (2026-11-04) | Backend features are **generation-time plugins**: plain fastapi-skills source copied into the project (owned, versioned in the manifest) through six named codegen hooks, with their frontend half in dynamic mode; the engine writes only custom operations, rules and job bodies, calling the plugins' APIs. Audit log, soft delete and SSE are out of scope | Epic 10 re-scoped (10.1); FR-34 (requirements v1.8) |
| FIELDS (2026-11-04) | Every request field has a **source** in the contract (`x-bga.source`: server, currentUser, route, reference, upload, input); foreign keys are picked by label or taken from the route; the pair check rejects forms with a field they cannot fill. Forms use a kit on the base's shadcn components (Calendar, Combobox, Switch, …) with Zod schemas for every form | 10.0b, 22.5, 22.6; FR-35 (requirements v1.8) |
| QUEUE (2026-11-04) | Generated backends run jobs on a **Postgres-backed queue** with a transactional outbox, not Redis + `arq` | 10.6 |
| PAY (2026-11-04) | Payments start with a **fake provider** behind a port; a developer adds Stripe as an adapter later | 10.9 |
| FILES (2026-11-04) | Files go to **MinIO** through signed URLs on the S3 API, so S3 is an env change | 10.5 |
| FE-TESTS (2026-11-05) | Generated frontend unit tests, Playwright and journeys **stay off** in validation (off since `95b547b`, 2026-11-01): they made the frontend lane too slow. Frontend criteria are proven by agent tests on the generated code, build and typecheck, and the preview | Epics 10, 22 |
| SWITCH-OVER (2026-11-06) | The app flow is the only dynamic flow: `DYNAMIC_FRONTEND` and the legacy dynamic path (designed pages, direction cards, Manage area, journeys, pair fixes, the golden dynamic frontend) are removed; a dynamic FrontendSpec that is not an app is `FE_APP_FLOW`. Measured on the fake engine only (the user: no side-by-side, no paid comparison) | 22.8; requirements v1.10 |
| MODES (2026-11-05) | **Static and dynamic are separate frontend flows.** Dynamic mode drafts an app outline next to the BackendSpec in one call; code builds every screen from the contract on one shadcn app kit (no page trees, no direction cards; the direction sets theme tokens only; every operation on a screen, no Manage area; no engine call in the frontend lane). Static keeps Epics 20–21 unchanged; a static golden test fails on any change to static output | Epic 22; FR-36 (requirements v1.9) |
| INTEGRATION (2026-11-05) | **The backend decides; a frontend only reads.** The contract carries each field's source, each operation's errors (`x-bga.errors`, custom rules included) and scenarios (`x-bga.scenarios`); every record response carries `allowedActions`. Each rule has one definition in the plan, from which codegen writes the backend check, the MSW behaviour and the scenarios; the scenarios run against the backend (smoke), MSW and the live switch. The draft names no operations: code writes every binding | 10.0b, 10.3, 10.4, 10.9, 10.10, 22.2–22.4, 22.7 |
| BACKEND-FIRST (2026-11-05) | Epic 10 is built backend and contract first; its frontend halves are written once, on Epic 22's app kit (22.5–22.7). Until then dynamic examples keep auth and roles off, and checkpoints are verified through template tests, smoke checks and the try-it explorer | Epics 10, 22 |
| TOKEN (2026-11-04) | Generated frontends store the auth token by a **runtime flag**, `AUTH_TOKEN_STORAGE=local` (default, `localStorage` + bearer) or `cookie` (httpOnly cookie, same-origin proxy adds the bearer); a developer switches it in the downloaded project with an env change. Both modes are checked (agent tests and the preview); the backend stays bearer-only. Agreed exception to nextjs-skills' "never `localStorage`" rule | 22.7 |
| Q15 (2026-10-26) | Product renamed **Fullstack Generation Agent** (docs, UI, `APP_NAME`, LangSmith project). Internal identifiers stay: `bga-runner`, `.bga/`, compose project `bga`, schema `$id`s, repo folder | – |

## Changes from requirements v1.0 (accepted via Q1; now part of v1.1)

| Requirement | Was | Now |
|---|---|---|
| §6 generated project structure | `app/{core,api,models,schemas,services,repositories}` | fastapi-skills `src/{configs,libs,modules/<module>/{ports,usecases,infrastructure,presenter}}` |
| §2 generated ORM "SQLAlchemy 2.x" | SQLAlchemy declarative models | SQLModel (built on SQLAlchemy 2.x) |
| FR-16 `.env.example` | `.env.example` | `.env.ex` (template name) |
| FR-16 "dependency manifest (`pyproject.toml`)" | `pyproject.toml` | `requirements.txt` (+ `requirements-dev.txt`) as in the template. `pyproject.toml` holds only ruff and pytest config. |
| FR-17 manifest | – | Manifest adds `architecture: "fastapi-skills-hexagonal"` and `templateRef: <commit sha>` so the Integration Agent knows the layout |

## Open questions (please answer during review)

| # | Question | My default if unanswered |
|---|---|---|
| Q3 | *(default applied in Epic 3)* Claude Code auth: `ANTHROPIC_API_KEY`, or a read-only subscription credentials file (`CLAUDE_CREDENTIALS_HOST_FILE`) | Keep? |
| Q2 | Agent API auth: seeded local users + JWT (meets FR-14 ownership), or a single static API key for local use? | Seeded users + JWT (Story 1.4) |
| Q7 | Do you have a LangSmith API key and project? Tracing is a no-op without one. | Optional. Works without it, and the local trace store (8.3) still feeds the UI. |
| Q9 | Template fixes such as tests, ruff, `ConflictException` and the migrate-on-start entrypoint live in our overlay. Should they go upstream into `longtk26/template-frameworks@feat/fastapi` instead, so the overlay shrinks? | Overlay now; upstream later as a separate PR to your template repo |
| Q16 | Which raster image provider for 15.5, if any? | Build 15.5 only when asked; Gemini image model first (key already used by Antigravity), behind a port |
| Q17 | Should revisions also cover the backend (and contract changes in dynamic mode)? | Not in Epic 16; a later epic once frontend revisions prove out. **Database policy agreed 2026-11-04:** a schema change clears the preview database and runs the migrations again from empty (then the seed); no data migrations |
| Q21 | Design direction (12.6): apply the top match automatically and offer 2 alternatives, or ask the user to pick one of 3 before the draft is written? | Top match applied, 2 alternatives switchable in the review |
| Q10 | The template registers routers inside `lifespan`, so `app.openapi()` is empty unless the app has started. Should the overlay move router registration to module level? | No. Keep the template as-is and export OpenAPI inside a started app (6.2). |
