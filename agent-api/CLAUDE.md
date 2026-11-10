# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This is the **Fullstack Generation Agent** API + worker, built on the `feat/fastapi` template
(see `templates/template.lock`). From the repo root, prefer `make dev`, `make dev-api`, `make dev-worker`,
`make migrate`, `make test` — they point at the dev Postgres 18 / Redis ports from `.env`.

```bash
make run                        # Start FastAPI dev server (fastapi dev src/main.py)
make worker                     # Start the job worker (python -m src.worker)
make newmg name="<description>" # Auto-generate Alembic migration from model changes
make mghead                     # Apply all pending migrations
make mgdown                     # Rollback last migration
make test                       # pytest (creates and migrates the <db>_test database)
make lint                       # ruff check + format check
```

Agent-specific notes:
- `ports/output/__init__.py` re-exports `I<Name>RepoDep` lazily (module `__getattr__`) so import order cannot cycle.
- Errors render as `{"error": {"code", "message", "details"}}` (`src/libs/exceptions/handlers.py`); pass an `ErrorCode`.
- Auth: `CurrentUserDep` / `AdminUserDep` from `src.modules.auth.presenter`; other users' resources → 404 via `ensure_owner`.
- PostgreSQL enums: add an explicit `sa.Enum(name=...).drop(...)` to migration downgrades.
- Only the worker talks to Docker (sandboxes `src/sandbox/`, previews `src/preview/`). The API reaches previews
  through `PreviewCommandBus` (Redis); artifacts are files under `ARTIFACT_ROOT`, resolved only from DB rows.
- Tracing (Epic 8): spans come from `src/orchestrator/tracing.py` (RunTree API; LangGraph's own tracer is off).
  Use `tracing.span(...)` / `tracing.current().child(...)`; record what the local trace needs in the DB too
  (`model_calls`, `sandbox_execs`), since `/trace` and `/usage` are built from records, not from LangSmith.
- Modes (Epic 12): `generations.mode` + `lanes`; graph per mode in `orchestrator/graph.py`; lane rules in
  `modules/shared/domain/generation_modes.py`. FrontendSpec lives in `modules/shared/domain/frontend_spec/`;
  the API contract (`orchestrator/integration/contract.py`) and its checks (`checks/conformance.py`, `checks/consistency.py`)
  are pure functions with snapshot tests (`UPDATE_SNAPSHOTS=1`).
- Frontend lane (Epic 13): `orchestrator/frontend_*.py` (planner, theme, codegen, scaffold, validation, nodes);
  base in `templates/nextjs_base` (regenerate with `make frontend-base`, never edit by hand), overlay in
  `templates/nextjs_overlay` (`overlay.json` = drift manifest). Frontend checks are stored as `frontend:<check>`;
  the frontend has its own git repo (`<workspace>/frontend`), sandbox kind (`for_job(..., "frontend")`) and
  preview kind (`previews.kind`).
- Stock photos (Epic 27): `IMAGE_PROVIDER=unsplash` (`UNSPLASH_ACCESS_KEY`) → `images/factory.get_stock_photos()`
  (`images/unsplash.py`: search by phrase and orientation, cached under `ARTIFACT_ROOT/asset-cache/stock/`, download
  tracking once, the hourly limit). Drafts hotlink and credit, never copy: a site's `photo` assets become the sized
  `images.unsplash.com` URL plus `credit` (`images/stock.stock_site_photos`), an app's seeded image fields get a photo
  per record's label (`stock_seed_photos`) and the FrontendSpec keeps their credited assets (`app.json`
  `photoCredits`, the kit's `PhotoCredit`). `Asset.credit` is code-only (left out of every drafting schema).
- Frontend preview images (2026-11-08): `packaging.write_frontend` writes `frontend.zip` and, when the validated
  build is current, `frontend-runtime.tar.gz` (kind `preview`); `DockerFrontendPreviewRuntime` builds the image from
  it (a copy, no install or `next build`) and falls back to the ZIP's Dockerfile. Write `frontend.zip` only through
  `write_frontend`.
- Before the checks (Story 17.5), `orchestrator/autofix.py` restores changed generator-owned files and runs
  `ruff --fix` / `eslint --fix`, committed as `node:autofix`. Frontend sandboxes mount a shared read-only
  node_modules per dependency set (`bga-fe-modules-<key>`, `FRONTEND_SHARED_MODULES`); only `.vite*` folders are
  writable inside it.
- Section renderer (Stories 17.1, 17.2, 17.4): built-in section content is typed (`frontend_spec/section_props.py`);
  a static site the library can render (`plan["rendering"] == "renderer"`, else `rendererGaps` says why) is built
  without the engine (dynamic apps render on the app kit, Epic 22): overlay part `templates/nextjs_overlay/files/renderer` (only the sections a site uses) plus
  `orchestrator/frontend/renderer.py` (site.json, registry, props types, thin route files). Sections can nest in
  layout nodes (`children`): walk them with `iter_sections` / `walk_sections`, never `page["sections"]` alone.
- Fonts and variants (Story 17.7): theme fonts in `frontend_spec/fonts.py` are `@fontsource` packages pinned in the
  base and imported by the generated `src/app/fonts.ts`; adding one means `make frontend-base` + `make runner-node`
  (the pnpm store volume is keyed on the base lock, `store_volume()`). Section variants (`background`, Hero
  `variant`, `cardStyle`) live in `section_props.py` and use theme tokens only; `background: "primary"` is the
  `.surface-inverse` token scope in `globals.css`. Library changes keep `templates/nextjs_overlay/DESIGN_CHECKLIST.md`
  (measure with `scripts/design-check.mjs`).
- Custom components (Story 17.3): a rendered site's custom components (with a `propsSchema`) are scaffolded as
  their library fallback (`plan["customComponents"]`), then `orchestrator/frontend/custom_components.py` generates each in a
  scratch copy and its own sandbox (`for_job(..., part=...)`), or copies it from the component cache
  (`component_cache` rows + `ARTIFACT_ROOT/cache/components/<key>/`, key in `frontend/component_cache.py`), and rewrites the
  owned registry. Admin purge: `DELETE /api/v1/cache/components`.
- Backend CRUD from templates (Story 17.6): `orchestrator/backend/codegen.py` writes models, entities, CRUD modules,
  `src/routers.py` and the API tests from the plan (no engine); the sandbox's ruff formats them and they are recorded
  as owned (`scaffold.add_owned`). The engine only completes what `codegen_gaps` / `database_gaps` name (custom
  operations, rules, auth; one-to-one / many-to-many models), with the `complete_backend` prompt.
  `options.crudFromTemplates=false` restores the engine path (tests of the engine plumbing use it).
- Backend completion (Story 18.13): `orchestrator/backend/completion.py`. `module_context` is the context pack the
  `complete_backend@v5` prompt inlines (custom operations with their spec entry and contract operation, schemas
  resolved; the module's generated files; its entity and model; related entities and their repository ports; the
  exception helpers), and the prompt says not to read other files. `complete_modules` runs the modules at once, each
  in a scratch copy (`<workspace>/scratch/module-<name>`), merges their changes in plan order, and reruns a module in
  the project when it changed a file an earlier module changed differently. One module, or `ENGINE_CONCURRENCY=1`,
  runs in the project directly. Frontend `conventions` findings and type errors only in test files are warnings.
- Backend plugins (Story 10.1): `orchestrator/plugins/` (registry, `base.py` contribution types, `app.py`) and
  `templates/plugins/<name>/` (`plugin.json`, `backend/files/**`). The planner records `plan["plugins"]` (dependencies
  first); `scaffold_project(..., plan=)` writes the plugins' files, renders `src/main.py` from the app-startup hook and
  fills the `# {{PLUGIN_SETTINGS}}` line of the overlay's `config.py`, `.env.ex` and `requirements.txt` (with no plan:
  the plugins every project has, i.e. the rate limiter). Codegen calls the module hooks (router params, use-case
  pre-checks and events, repository filters, response fields; 10.3: action checks, test preludes and test cases);
  none contributing leaves the code byte-identical, and a later plugin's route parameter of the same name replaces an
  earlier one's. Integrations without a plugin get a port and a stub adapter (`integration-stubs`). The runner image
  bakes every plugin's requirements, so a project uses the baked venv when it has each of its requirement lines.
- Auth and policies (Stories 10.2, 10.3): `auth-jwt` adds the user entity, demo users (`demo-<role>@example.com` /
  `demo12345`) and its own `auth` module; `policies` adds role checks on routes (`require_roles`), ownership in use
  cases and lists, the owner from the signed-in user (`x-bga.source: currentUser`) and `allowedActions` per user.
  Contract scenarios may name the demo user they run as (`scenario.user`); seeds go in parents-first.
- Business rules (Story 10.4): the `rules` plugin writes `transition`, `immutableAfter` and `sumEquals` from one plan
  definition per rule (`op.ruleChecks`; catalog in `src/libs/rules/catalog.py`); `ownerOnly` is the policies
  plugin's; `custom` rules are the engine's (`op.customRules`: the code it raises), ambiguous ones are skipped
  (`op.skippedRules`). `codegen.engine_rules(op)` is what is left for the engine.
- File storage (Story 10.5): `file` / `image` fields are string columns with `column.file`; the `storage` plugin adds
  `src/libs/storage`, `POST /files/presign`, upload checks and `<field>Url`. Sandboxes and previews of such projects
  share one local S3-compatible store (`src/sandbox/object_store.py`, RustFS `bga-storage` on 127.0.0.1:9100), one
  bucket each, joined to their network as `storage`.
- Jobs (Story 10.6): the `jobs` plugin's queue is PostgreSQL (`src/libs/jobs`, `python -m src.worker [--once]`); CRUD
  use cases emit subscribed events in the request's transaction; previews run `bga-preview-worker-<gen>`; the smoke
  check runs the worker once after its calls. Plugin tables: `plan.pluginModels` / `plan.pluginTables`.
- Email (Story 10.7): `emails[]` become jobs (`email<Name>`) rendering Jinja templates; `src/libs/email` (SMTP or
  console); account links (reset, verification) in the plugin's `account` module. Sandboxes and previews send to one
  shared Mailpit (`src/sandbox/mail_service.py`, UI 127.0.0.1:8125), tagged per generation.
- Webhooks (Story 10.8): outgoing events fan out to signed deliveries (jobs, SSRF guard); incoming
  `POST /webhooks/<source>` checks the signature and is idempotent by event id. Sandboxes and previews set
  `WEBHOOK_ALLOW_PRIVATE=true`; the smoke check delivers to a receiver inside the sandbox.
- Payments (Story 10.9): checkout from the record's amount; the fake provider's page posts signed events to the app's
  own `/webhooks/payments`; a job settles the payment and the record's status; `pay` in `allowedActions` until paid.
- Concurrency rules (Story 10.10, `plugins/concurrency.py`): capacity locks the parent row; noOverlap is an exclusion
  constraint (btree_gist from `env.py`); uniqueTogether a (partial) unique index. Models take `tableArgs` and
  `constraintErrors` (mapped by constraint name in the repository).
- Relations (Story 10.11): link models and one-to-one come from templates (`database_gaps` names neither); a one-to-one
  child is a summary in its parent's response (`model.children`); the `relations` plugin writes the many-to-many routes.
- The integration contract (Story 10.0b): the backend decides, a frontend only reads. Request properties carry
  `x-bga.source` (a foreign key: `reference` with `x-bga.ref`); record responses carry a `{id, label}` summary per
  parent and `allowedActions` (the planner's `label`, `references`, `recordActions`); operations list
  `x-bga.errors` and `x-bga.scenarios`; `x-bga.entities` tells the MSW handlers to present records the same way
  (`presented_record` does it from the contract). The frontend's `scenarios` check runs every scenario against the
  mocks, so a new rule or plugin adds its scenarios and its `allowedActions` entries in the same place as its backend
  code. The backend smoke check (2026-11-06) calls each endpoint once (its first success scenario, else a call built
  from the fixtures) and fails only on a 5xx or no answer; any 2xx / 4xx passes. The seed (the contract's fixtures)
  must insert: it is our data, so a seed error fails the check (`build_fixtures` maps a seeded foreign key no parent
  record has onto one).
- Requirement drafting (Stories 2.4, 12.4): `POST/GET /api/v1/spec-drafts` (`specs` module) stores a `spec_drafts` row
  and queues it on `bga:drafts:<engine>`; the worker's `_consume_drafts` (own slots, `DRAFT_CONCURRENCY`) runs
  `orchestrator/drafting/drafts.py` in `<WORKSPACE_ROOT>/drafts/<id>/` (inputs in `.bga/`: schemas, an example from
  `EXAMPLES_DIR`, the section catalogue), validates, repairs with `repair_spec`, and ends
  SUCCEEDED / NEEDS_REVIEW / FAILED. Usage is kept on the draft (`usage`), not in `model_calls` (those belong to a
  generation); `/usage` reports it as `drafts`. A generation created with `draftId` stores `options.draftId`, and
  packaging writes `requirement.md` / `.txt`. Requirement checks: `modules/shared/domain/requirement.py`.
- Draft engine (Story 18.10): `engines/gemini_api/` drafts specs with one `generateContent` request per step (no
  agent loop); it has `inline_inputs` (drafting renders the inline prompt versions `draft_frontend_spec@v10`,
  `draft_spec@v4`, `repair_spec@v3`, `repair_direction@v2`, inputs in the prompt) and `drafts_only` (refuses code
  purposes; the engine list marks it). Answers are one JSON envelope of `files` and RFC 6902 `patches`
  (`libs/jsonpatch.py`). `DRAFT_ENGINE` / `registry.draft_default` pick it for drafts; generation keeps the CLI
  engines. A repair round whose errors repeat the previous round's ends the loop. `docs/engines/gemini-api.md`.
  Story 22.8 / Epic 24: **drafting is one-turn only** (was "API-only"): an engine drafts only when it says so
  (`ICodeEngine.drafts`: the Gemini API engine, the one-turn JSON engines `antigravity_json` / `claude_code_json`
  (`engines/llm_engine.py` over `engines/json_cli.py`) and the fake); `EngineRegistry.check_draft_engine` refuses a CLI engine for `/spec-drafts` and a one-click
  `draftEngine` (422), and `draft_default` is never a CLI engine. An app draft asks for **structured output**
  (`EngineRequest.response_schema` → `responseJsonSchema`): `drafting/answer_schema.py` builds the answer's schema
  (the three files, rules typed per kind, only the keywords Gemini documents); a 400 for the schema retries without
  it. `drafting/app.fix_backend_defaults` fixes mechanical mistakes before any check (`now` defaults, a field list
  written as one string, a missing primary key); `repair_spec` is the last resort.
- LLM providers (Epic 24): every LLM-only step asks `LlmProvider.json(step, prompt, schema, images)` (`engines/llm.py`)
  once: `antigravity` (one `agy` stream-json turn with `--json-schema`, deny-all permissions, an empty scratch dir),
  `claude_code` (`claude -p --output-format json --json-schema --tools ""`) or `gemini_api`; tests pass their own
  (`tests/fake_llm.py`, never imported by `src/`). The answer is checked against the schema in code (`libs/json_schema_check.py`) and asked
  again once with its errors. `LLM_PROVIDER` picks it (`build_llm_provider` / `get_llm_provider`); `DRAFT_ENGINE`
  defaults to its draft engine (`antigravity` → `antigravity_json`). **One switch** (2026-11-09): with neither set,
  both follow `DEFAULT_ENGINE` (`claude_code` → `claude_code_json`, `antigravity` → `antigravity_json`), and
  `FAST_DRAFT_MODELS` has an entry per provider (`claude-haiku-5-5`, `gemini-3.8-flash-low`). The account / subscription logins cost $0
  (`costSource: account`). `antigravity_json` runs on the host worker with `ANTIGRAVITY_AUTH=account`.
  `claude_code` / `claude_code_json` log in with `ANTHROPIC_API_KEY`, else `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`:
  the subscription for headless runs; on macOS the desktop login is in the keychain, which a container and the
  engines' private `CLAUDE_CONFIG_DIR` cannot read), else `CLAUDE_CREDENTIALS_FILE`.
- Access rules (Epic 25): `orchestrator/drafting/access.py` runs on every valid app draft (`drafting/app.apply_access_rules`,
  kept only when the BackendSpec stays valid, each change a note): records tied to a person (an ownership owner field or
  a `<role>Id` field) are private with the staff's bypass; owner actions lose the bypass; an assigned worker's actions
  are theirs; a status with a flow changes only through its actions (no "Mark as" buttons then); an entity with a `visibility`
  policy keeps its reads as drafted (the policy says who sees which records; 2026-11-09); a person's record that
  only staff create (staff who also manage it; a role that only creates a record owns it) names its person (a staff-only `user.list` directory, the policies plugin's `owner_from_request`);
  the fixtures point person fields at demo users of their role, two per person role (`person_roles`).
- The requirement's look (Story 23.13): `draft_app@v5` writes what the requirement says about the look as values
  (`app.design.requested`: accent, background, text, scheme, heading kind, corners, photos); `complete_design` checks
  them and `frontend/app/requested.follow_requested` applies them over the design data's theme and views (contrast
  kept by `fix_contrast`, one note). The requirement comes before the design data.
- Business layer (Epic 26): `orchestrator/business/` (model, prompts' schemas, `flow.py`: discover → expect before
  `draft_app`, bind after; `binding.py`: the code check and `tour_workflows`) and `drafting/business.py` (on when
  `BUSINESS_WORKFLOWS` or the draft's `businessWorkflows`; stored in `spec_drafts.business`; the brief replaces the
  requirement in the draft prompt). The tour goes into the FrontendSpec's `app.workflows` → `app.json` → the kit's
  `components/app/tour/` (react-joyride 3.2.0, loaded only when there are workflows). The evaluation
  (`orchestrator/evaluation/`: the lab's checker, API caller and Playwright walker) runs after a completed generation
  (`bootstrap.on_completed` → `EvaluationService.request_auto` → `bga:evaluations:<provider>`, taken by a worker that
  serves the provider's draft engine), stores `evaluation_runs` and never touches the generation (D4). API:
  `GET/POST /api/v1/generations/{id}/evaluation[/run]` (GET 404: nothing to evaluate, no Business tab; `NONE`: no run
  yet), screenshots under `ARTIFACT_ROOT/<gen>/evaluation/<run>/shots`. `POST …/run {"expectationsFrom": <gen>}` checks an
  app against another generation's frozen expectations, bound to this app first (Story 26.7: the option-off comparison).
- Interactive tour (Epic 28): the kit sends one `bga:done` signal per event (`components/app/signals.ts`: an
  operation's success with its record id, a page render, a dialog opening, a field filled, a refused submit) from
  `AppForm`, `RecordActions`, `AppPage`, the payment and upload fields. `tour_workflows` gives each step a `kind`
  (`do` / `look` / `note`, `step_kind`) and record steps `needs` (the earlier step that makes a record ready); the
  tour (`tour/AppTour.tsx`, react-joyride in controlled mode) completes a `do` step on its operation's signal, walks a
  form's required fields, offers "Fill with an example" (`app.json` `forms[].example`, `files.form_example`: the
  contract's success scenario; the registry `form/registry.ts`), never submits (D3), opens a record whose
  `allowedActions` allow the step (`tour/records.ts`) and keeps progress per user and step (`tour/progress.ts`, the
  checklist `tour/Checklist.tsx`; "Continue as <role>" through the auth plugin's `signInDemo` slot). The evaluation
  plays each role's tour on the mocks (`evaluation/tour.py`, `walk.mjs` `tour`; the kit's `bga-mock-api` switch forces
  MSW in that browser) into `report.tour`. `make kit-test` type-checks the kit and runs its vitest files in the sandbox.
- Media fields (Epic 29): `video`, `audio` and `subtitles` are file fields (`backend_spec/media.py`: the playable
  types per kind (D2), the default sizes, the sample files; the validator refuses an `accept` outside the kind's set);
  the planner's `MEDIA_KINDS` table fills `column.file`, the storage plugin speaks each kind's type (scenarios, tests,
  `x-bga.storage.objects`) and writes the subtitle tracks (`media_tracks`: a same-record `subtitles` field, or a child
  entity with a language field) as `x-bga.storage.tracks`; read URLs carry `ResponseContentType`. Samples
  (`templates/samples/`, CC0, `make sample-media`): the fixtures' keys end in the kind's sample, a track entity gets one
  row per sample language, `orchestrator/samples.storage_objects` adds the bytes the smoke check and `seed.json`
  (`seed_artifact`: `{rows, objects}`, uploaded by the generated `scripts/seed.py`) put in the store, and the scaffold
  copies them to `public/samples/` for apps with media (`plan.app.media`; the mocks' `fileUrls` plays them). Kit: the
  storage plugin's `VideoPlayer` / `AudioPlayer` (native, tracks by language, SubRip converted in `subtitles.ts`, an
  expired URL refetched once and resumed), `UploadField` (XHR progress, cancel, preview, the duration field filled),
  `ListeningBar` (the `listening.ts` store; apps with `app.json` `media.audio`); `app.json` entities carry `tracks`
  and `media`; the design brief has a `duration` role and takes a video or audio field as `media` (a video record's
  detail defaults to `media`); `draft_app@v6` names the types and `drafting/app.fix_media_fields` turns a media-like
  `file` into its kind. `examples/specs/media-library.json` is the synthetic media app (also in the design report).
- Sample videos (Epic 31): `VIDEO_PROVIDERS` (`youtube`, `pixabay`; `YOUTUBE_API_KEY`, `PIXABAY_API_KEY`) →
  `videos/factory.providers_for(place)` in the place's order (`watch`: YouTube then Pixabay; `background`: Pixabay;
  `seed`: Pixabay then YouTube). `videos/youtube.py` (search.list with the epic's filters, videos.list for the
  duration and `embeddable`, a daily unit counter under a margin), `videos/pixabay.py` (film clips, the file chosen by
  width and byte budget per place, the descriptive `User-Agent`, `X-RateLimit-Remaining`, posters downloaded into the
  cache), both cached a day under `ARTIFACT_ROOT/asset-cache/video/`. A site drafts a `video` asset as
  `source: "search"` + `query` + `place` (`draft_frontend_spec@v11`, only with a provider on); `videos/stock.
  stock_site_videos` resolves it (`source` → `youtube` / `pixabay`, the code-only `video` and `credit`), the `Video`
  section and the hero's `backgroundVideo` render through `components/assets/VideoEmbed.tsx` (a facade: no YouTube
  request before play) and `BackgroundVideo.tsx` (muted, pausable, still under reduced motion); trees take them as data
  components. Apps: `stock_seed_videos` fills seeded `video` fields (a Pixabay file, else a YouTube watch link) with
  `app.json` `videoCredits`; the kit's `VideoPlayer` shows a YouTube link as the facade and the credit under the player.
  `make video-keys` checks the keys. `FRONTEND_MAX_PHOTOS` now caps paid photos only (`STOCK_PHOTO_LIMIT` for stock).
- Design plugins (Epic 30): every value of the app design space (shell, list view, detail view, home, filters, card,
  recipe, font pairing) is a folder `templates/design/<kind>/<name>/` (`plugin.json` + kit files), read once by
  `frontend_spec/design_registry.py`; the literals in `frontend_spec/app.py`, the `draft_app@v9` choice lists
  (`design.design_choices`, only the ranked archetypes' candidates), `complete_design`'s checks (`needs` → the
  descriptor's `fallback` chain, `_Data.lacks`), the recipes (`recipes.py`), the kit's generated
  `design-registry.ts` (the plugins the app uses; `AppShell`, `RecordsView`, `AppDetail` dispatch through it) and the
  UI's choices (`GET /api/v1/design-plugins`) all come from it. Builtin plugins live in `shells.tsx`, `views.tsx`,
  `details.tsx`; folder plugins are copied only when used (`plan.app.designPlugins`). `make design-plugin-new` /
  `make design-plugin-check` (the gates: recipes, states, keyboard, contrast; `docs/development/design-plugins.md`);
  `tests/test_design_registry.py` refuses a hand-written list of plugin names. The app design report signs in per
  area and fingerprints the screens (Story 30.1; baseline `tests/fixtures/app-golden/baseline.json`).
- Product patterns (Epic 32): how each area's screens behave, a design plugin kind `pattern`
  (`templates/design/pattern/<archetype>/plugin.json`: menu, child placement by shape, public children, home, what the
  area's people never get, its UX checks). `frontend/app/patterns.py`: the child shapes from the contract
  (`interaction` / `contribution` / `part`, `owned`), the area's kind (its archetype, or `back-office` when every role
  manages the main entity) and its pattern (`plan.app.patterns`; a draft pattern falls back to `back-office`, which is
  the planner as it always was; a mixed area, where some roles manage the main entity, stays `back-office`). The
  planner (`_Screens(pattern=, main=)`) reads it: a consumer pattern's menu is the main entity, the cart, the person's
  own top-level records and one Mine page (`pattern_menu`; `reach_every_page` is a back-office's); a child whose shape
  the pattern places on the record is an action there (one click, or its form in a dialog: `on_parent`); no edit page,
  delete or owner's action on records these people never create (`others`); no dashboard; tables become cards.
  `storefront` is ready (Story 32.6: Plants, Cart, My Orders; Add to cart on the product).
  `feed` is ready (Story 32.5): a view-like record action with nothing to fill in (or a view child) is the record
  page's `onOpen`, run once by `AppDetail` (`useOnOpen`), never a button. `ux-before.json` keeps the pre-pattern measure.
  The draft may say where an entity's records are made (`entities.<Entity>.create`: `onRecord`, `onOpen`, `page`;
  `draft_app@v9`); the planner reads it first, in any area (Story 32.7).
  The access rules take the patterns' public shapes (`secure_access(spec, public)`, `drafting/app.public_shapes`): a
  person's text on a record (a comment, a review) keeps the record's readers, writes stay the author's.
  `frontend/app/ux_checks.py` judges a planned app per area
  (`make app-design-report ARGS="--ux-only [--baseline]"`; `tests/fixtures/app-golden/ux-baseline.json`).
- Domain plugins (Epic 33): three kinds read by `modules/shared/domain/domains/registry.py`: a **domain**
  (`templates/domains/<d>/domain.json`: core entities by role, areas and their people, required and optional features),
  its **types** (`types/<t>/type.json`: an area's home slots) and shared **features** (`templates/features/<f>/feature.json`:
  a BackendSpec fragment with placeholders, computed fields, kit toggles). `make domain-check` / `domain-new` /
  `feature-new`. Drafting: `drafting/domains.rank_domains` offers domains to `draft_app@v10` (v9 plus the domain block,
  only when one is ranked); `apply_domain` checks the outline's `domain` (roles played by drafted entities, `{author}`,
  `{section}`, `{entity:x}`, `{role:x}`, `{state:x}`, `{time}` options resolved) and `drafting/features.attach` merges
  each feature as plain entries (the model's own `Comment`/`Like` dropped with a note), before the checks. The spec's
  `features` block (code-written, never in the drafting schema) carries **computed fields**: `count` or `mine` (the
  caller's own row), on the target or another entity (`target`), keyed by its id or a field (`match`), the caller's rows
  only (`owner` on a count). They are core: the planner's `model["computed"]`, `references(records, viewer)` in the
  generated repository, the response DTO, the policies plugin giving reads the caller, the contract (`readOnly`,
  `x-bga.computed`), the mocks' `present()` and `presented_record`. Self-relationships (a reply's parent) configure
  (`remoteSide`). The planner gives feature entities no screens; targets get the features' toggles (`kind: reaction`,
  `ReactionButton`) and sections (`CommentThread`, `AppTimeline`, `AppChart`), a type's home its slots (`AppResume`,
  `AppPresence`, `AppChart`); kit parts in `components/app/features/`. The UX tasks: `tests/fixtures/domains/` and
  `frontend/app/domain_tasks.py` (`make domain-report [ARGS=--baseline|--replan]`). Screen feedback:
  `orchestrator/feedback.py`, `POST /api/v1/generations/{id}/feedback`, `GET /api/v1/generations/plugin-requests`.
- Designed themes (Epic 34): `drafting/themes.py`. After `app_theme(chosen)` (the design data's theme), `draft_app`'s
  `designer` (built in `DraftRunner._designer` on the draft's LLM provider; `DESIGN_THEMES` / a request's
  `designThemes`; never for a fake-engine draft unless asked) renders `design_theme@v1` (the brief: requirement, name,
  domain or archetype, main entities, the requested look, the data's category as a hint; the pairings
  `pairing_candidates` offers) and answers six colours, a pairing, radius and density. `check_theme` gives the reasons
  (contrast, a readable primary, the pairing, the clichés in `CLICHES` — excused when the user named the accent — the
  requested accent, scheme and heading kind); one repair with them, then the data's theme. Passing: `designed` keeps
  the destructive colour, style and direction; `tint_neutrals` tints pure-grey surfaces; `apply_pairing` puts the
  pairing on the design and the leading look; `follow_requested` still runs after. `make theme-report` measures the
  reference apps (`tests/fixtures/themes/`) against the baseline; `--html OUT` writes the blind page. `keeps`: a hex
  the requirement gives is binding, a colour named only in words is followed by its family (hue within 25°, the page's
  lightness); code sets a requested accent the answer left (`with_requested_accent`); plain-sans pairings are never
  offered and the list follows the app's seed. `fix_seed_references` (drafting/app.py): a seed foreign key written as
  the parent's name points at that parent's seed row.
- Recipe palettes (2026-11-10): a recipe never sets colour tokens; one with its own colours names a `palette` mood
  (`plugin.json`) and `frontend/app/palettes.py` derives it from the app's built palette (`app_plan_theme` in
  `frontend/app/plan.py`: pairing, mood, `readable_muted`; a dark mood makes the app dark-scheme). A one-scheme app is
  drawn in its scheme (`siteConfig.colorScheme`, `forcedTheme` in the provider).
- Designed pages (Epic 21): a page may be an element **tree** (`FrontendSpec` `pages[].tree` + `css`, `layout.chrome`
  / `footerTree`; `TreeNode` in `schema_v1.py`), as Frontend-Agent's site JSON writes it. `frontend_spec/trees.py`
  classifies node types (elements, shadcn primitives, Lucide icons, library sections, data components), checks the
  rules (theme-token colours, no fixed, one h1, assets, links, node and depth limits) and repairs what it can
  (`fix_trees`, run by `autofix_frontend_spec`); `tree_bindings.py` binds data components to a content collection
  (trees are a static site's; apps have none). `frontend_renderer.tree_site` writes
  the classified tree into `site.json`; the overlay's `renderer/tree/` (copied only when `plan["trees"]`) renders it
  (`TreeRenderer.tsx`, data components in `tree-data.tsx`, `tree-metrics.tsx`, `tree-forms.tsx`). Drafting designs
  each page with `draft_tree@v1` after the spec is valid (`orchestrator/drafting/trees.py`; `FRONTEND_TREES`), in
  parallel on an API engine; a page whose tree fails keeps its sections. BackendSpec `type: "aggregate"` operations
  are templated like CRUD (`backend/planner.py`, `backend/codegen.py`, the contract and the mock compute them).
- Design direction (Stories 12.6, 20.4, 20.9): the drafting engine writes three direction cards in `notes.json`
  (`design.cards`: concept, tone, hero layout, fonts, colours, key visual, forms, rhythm, `home` section ids, fit);
  `orchestrator/drafting/design_cards.py` checks and fills them (bundled fonts, AA contrast, `design_tone` tokens), runs the
  difference test (`repair_direction` prompt, at most 2 rounds, then a code fix) and keeps the drafted home sections
  as `spec_drafts.design.pool`; drafting applies the best fit after the spec repairs (`finish_design`).
  `orchestrator/drafting/design_direction.py` (UI UX Pro Max's vendored data, `make design-data`) is the floor: the category
  default in the fact pack `.bga/design.md`, the palette for cards that miss contrast, the directions when the engine
  wrote no cards. `apply_direction` / `compose_home` are mirrored by the UI's `lib/design-direction.ts`
  (`tests/test_design_cards.py` runs both on the same cases with Node). Stock phrases in headings and buttons
  (`frontend_spec/copy_rules.py`) are `FE_DESIGN_RULE` warnings and get one repair round.
- Design diversity (Epic 20): hero `variant` has 8 layouts, list sections a `form`, pages a `rhythm`, and seven
  content sections joined the library (Steps, Timeline, Team, PriceList, Location, Comparison, Statement), all in
  `section_props.py` with theme tokens only. Optional theme tokens (`surface`, `colorArea`, `typography.headingWeight
  / headingCase / tracking / ratio`) are drawn by `frontend/theme.py` (`heading` utility, `--hero-<step>` sizes
  shrunk by `display_scale` for wide faces) and by `frontend/renderer.py` (`color_roles`, `alternate_backgrounds` in
  `site.json`); `orchestrator/drafting/design_tone.py` maps a five-scale tone to them. Without the new fields a spec plans
  exactly as before and renders the same sizes and weights (`globals.css` gains the variables at today's values).
  Icons (20.5): items take `icon` (`lucide:` / `phosphor:` reference or `intent:` words), resolved to `theme.icons.set`
  when the site is generated (`frontend_spec/icons.py`, index `templates/nextjs_base/icon-index.json` from
  `scripts/icon-index.mjs`); `frontend_renderer.icons_ts` imports only the used icons; the library draws them with
  `sections/Icon.tsx`. Motion (20.6): `theme.motion` (`feel`, `signature`) → `frontend/motion.py` (spring presets as
  CSS `linear()`, rules under `html[data-motion="on"]`), `site.json` `motion`, `PageRenderer`'s inline script and
  `MotionRoot.tsx` (reveals). Dev tools: `make design-check-fixture` (`--motion`), `make design-diversity`
  (`docs/development/design-checks.md`).
- Site images (Epic 15): asset sources and render modes in `frontend_spec/assets.py`; the registry
  `src/assets/index.ts` (`frontend/asset_registry.py`) and the overlay's `components/assets/AssetImage.tsx`. `generate_assets`
  (`frontend/assets.py`) draws all `source: "generate"` assets in one engine call in a scratch dir (cache in
  `ARTIFACT_ROOT/asset-cache/`), `frontend/svg_assets.py` checks SVGs (`frontend:assets`, before build) and converts them to
  components; failing drawings fall back to placeholders (`asset_fallbacks` → COMPLETED_WITH_WARNINGS). Uploads
  (`modules/uploads`) live under `UPLOAD_ROOT`, are copied to `public/assets/` by `scaffold_frontend`.
- Test doubles (fake engine, golden two-entity project, static validator, fake CLIs, opt-in test flags) are listed in
  `docs/development/test-doubles.md`; add any new fake there and mark it at its definition.
- Dynamic app flow (Epic 22): **static and dynamic are separate frontend flows**. Every dynamic draft goes to
  `drafting/app.py` (Story 22.8 removed the legacy dynamic flow: its designed pages, direction cards, Manage area,
  journeys and pair fixes; a dynamic FrontendSpec without `project.flow: "app"` is `FE_APP_FLOW`); the FrontendSpec it writes has `project.flow: "app"`, an `app` outline (`frontend_spec/app.py`) and pages of app
  sections (`APP_SECTIONS`, accepted only in that flow), all written by code. `plan_frontend` hands such specs to
  `frontend/app/` (`rendering: "app"`, no engine call), and the scaffold copies the app kit
  (`templates/nextjs_overlay/files/dynamic/app/`) only for them. Dynamic-only code goes in `orchestrator/frontend/app/`
  and `drafting/app.py`, prompts in `prompts/draft_app/`, overlay files in `files/dynamic/app/`. A change to shared code
  (renderer, `common` overlay, section components, drafting) must leave `tests/test_static_golden.py` passing; static
  drafts read the schema without the app fields (`frontend_spec_json_schema(app=False)`).
  The app draft is one `draft_app@v2` call (BackendSpec + `app-outline.json`); code fixes the outline
  (`complete_outline`, notes instead of repairs), adds the dashboard's aggregate operations (`ensure_aggregates`) and
  plans every screen (`app_frontend_spec`): one binding per section, so `check_spec_pair` and `uncovered_operations`
  see them all; a child is created from its parent's page (parent from the route); a create with nothing visible to
  fill in is a button (on its list page, or on the parent's cards, rows and page when it is a child: a like, a
  bookmark), never a form page.
  The kit (Story 22.4: `AppShell`, `AppPage` (figures in a grid, a parent's children in tabs), `AppList`, `AppDetail`,
  `AppForm`, `AppDashboard`, `AppActions`) reads `src/content/app.json` (`frontend/app/files.py`: pages, routes, forms,
  per-entity field types, references and list operations, the contract's errors) and calls the API through the
  generated `bindings.ts`; actions follow each record's `allowedActions`. Custom and aggregate GETs have their own
  React Query keys (`_Operation.query_key`). The frontend lane's `scenarios` check (apps only) runs the contract's
  scenarios against the MSW mocks (`src/mocks/scenarios.test.ts`, `scenarios.json`); the mocks refuse missing required
  fields (422) and unknown parents (400) as the API does. `make design-check-app` screenshots an app's screens.
  Form kit (Story 22.5, `components/app/form/`): the planner types each field (`screens.input_kind`: contract format,
  BackendSpec type, then the name for email / url / tel / password) and adds the outline's `help`, a currency (the
  paid amount) or a unit (`durationMinutes` → min); `FormField.help` / `currency` / `unit` are app-only schema fields
  (`site_schema` drops them). Dates are a calendar (`date-locale.ts`: only `project.locale`'s date-fns locale), enums
  a segmented control / radios / Select by count, and app forms' Zod checks `z.iso.date()` / `z.iso.datetime()`
  (`_zod(..., app=True)`; optional fields through `z.preprocess(blank, …)`: `""` / `null` are not given). Create forms
  start from the contract's defaults (`screens.prefill`); edits send changed fields, a cleared one as `null`. Server
  errors go to fields from 422 `loc` and 409 `details.fields`.
  Pickers (Story 22.6): no app form asks for an id. `currentUser` / `server` sources are not shown, a parent the page
  knows is a hidden `$route.id` field, any other reference is a `FormField.reference` (app-only: the parent's list,
  `get`, label field, `q` search, page size) rendered by `form/ReferenceField.tsx` (Popover + Command). `ensure_aggregates`
  first adds a paginated `list` for each referenced parent without one (`screens.parent_lists`). `FE_FIELD_SOURCE` is
  an error for app specs.
  Plugin frontends (Story 22.7): each plugin's app part lives in `templates/plugins/<name>/frontend/files/` (auth-jwt:
  sign-in / sign-up / user menu / session, the `cookie` mode routes `/api/auth/*`, `/api/backend/[...path]` and
  `src/proxy.ts`; storage: `UploadField`, `FileValue`; payments: `PayAction`, `AppPayment`; relations: `AppLinks`),
  copied only for apps whose contract has the plugin (`files.frontend_plugins`, `plan["app"]["plugins"]`); the kit reaches
  them through the generated `src/components/app/plugins.ts`, else `plugin-stubs.tsx`. `app.json` gains `auth` and
  `access` (operationId → secured, roles): the kit hides navigation, sections and "New" a user cannot use and guards
  pages; records' actions still follow `allowedActions` (transitions are `mutation` actions with a `body` and `allow`;
  `pay` is its own kind). Token storage: `AUTH_TOKEN_STORAGE` (`local` | `cookie`, decision P8; previews take
  `PREVIEW_AUTH_TOKEN_STORAGE`). The mocks emulate the plugins (`src/mocks/plugins.ts` from the generated
  `plugins.json` / `defaults.json`: sessions, policies, per-user `allowedActions`, rules, uploads, checkout, links), so
  signed-in scenarios run on MSW too (`scenarios.json` `login`).
- `BACKEND_TESTS` (`config.backend_tests`, default off): run_validation runs a generated backend's own pytest suite
  only when on; off, the `tests` check is the smoke calls alone (each endpoint once against the running app, no
  5xx), saving most of the check's time. The agent's tests turn it on (`tests/conftest.py`).

## Orchestrator layout

`src/orchestrator/` (the generation workflow) is split by lane:

| Folder | What |
|---|---|
| `orchestrator/` | workflow core: `graph.py`, `runner.py`, `state.py`, `context.py` (JobContext and the helpers nodes share), `store.py`, `tracing.py`, `workspace.py`, `worker_service.py`, `bootstrap.py`; `nodes.py` (the node table, `package_artifacts`), `autofix.py`, `packaging.py`, `previews.py`; `checks/` (pure checks both lanes use) |
| `backend/` | `nodes.py` (validate_spec … repair_code), `planner.py`, `scaffold.py`, `codegen.py` (CRUD from templates), `completion.py` (engine completion), `migrations.py`, `validation.py` |
| `frontend/app/` | Epic 22, dynamic apps only: `outline.py` (the drafted outline completed from the BackendSpec), `screens.py` (outline + contract → pages, forms and bindings; dashboard aggregates), `plan.py`, `files.py` (`app.json`, bindings, icons, route files) |
| `frontend/` | `nodes.py`, `planner.py`, `scaffold.py`, `codegen.py`, `renderer.py`, `theme.py`, `motion.py`, `assets.py`, `asset_registry.py`, `svg_assets.py`, `custom_components.py`, `component_cache.py`, `context_pack.py`, `validation.py` |
| `integration/` | `nodes.py` (validate_inputs, build_contract), `contract.py`, `integrate.py` (live switch and checks) |
| `drafting/` | `drafts.py` (spec drafts), `app.py` (the dynamic app flow, Epic 22), `trees.py` (designed pages), `design_cards.py`, `design_direction.py`, `design_diversity.py`, `design_tone.py` |

## Architecture

Module-based hexagonal (clean) architecture. Each module owns its own layers; shared domain and infrastructure live in `modules/shared/`.

```
src/
├── main.py              # App entry point; lifespan registers routers
├── routers.py           # Central router registry — add new module routers here
├── configs/
│   └── config.py        # Pydantic Settings singleton (reads .env)
│
├── modules/
│   ├── __init__.py      # Import all ORM models here for Alembic autogenerate
│   ├── shared/
│   │   ├── domain/
│   │   │   ├── entities/          # Pure Pydantic domain entities (no ORM)
│   │   │   │   └── user_entity.py
│   │   │   └── value-objects/
│   │   └── infrastructure/
│   │       └── models/            # SQLModel ORM classes (shared across modules)
│   │           └── user_model.py
│   │
│   ├── health/
│   │   ├── ports/input/           # Input port ABCs (use-case interfaces)
│   │   ├── usecases/
│   │   │   └── health_check_usecase.py  # Use-case class + Dep type alias
│   │   └── presenter/
│   │       ├── router.py          # FastAPI router; injects use-case deps
│   │       └── dtos/              # Request/response Pydantic models
│   │
│   └── users/
│       ├── ports/
│       │   ├── input/             # Input port ABCs
│       │   └── output/            # Output port ABCs (IUserRepository)
│       │       └── user_repository.py
│       ├── usecases/
│       │   ├── create_user_usecase.py   # Use-case class + Dep type alias
│       │   └── get_user_usecase.py
│       ├── infrastructure/
│       │   ├── persistence/
│       │   │   └── user_repository.py  # UserRepository + IUserRepoDep binding
│       │   └── adapters/
│       └── presenter/
│           ├── router.py
│           └── dtos/
│
└── libs/
    ├── database/session.py              # DBSessionManager, SessionDep
    ├── repository/base_repository.py    # Optional BaseRepository utility
    ├── exceptions/base_exception.py     # NotFoundException, BadRequestException, etc.
    └── decorators/transactional_decorator.py  # @Transactional decorator
```

## Key Concepts

- **Entity** (`shared/domain/entities/`): Pure Pydantic `BaseModel` — no ORM annotations. Shared across modules.
- **Input port** (`ports/input/`): ABC defining the use-case interface.
- **Output port** (`ports/output/`): ABC defining the repository interface that the use case depends on.
- **Use case** (`usecases/<action>_usecase.py`): Implements business logic. Depends on the output port interface only. Defines its own `<Name>Dep` type alias.
- **Model** (`shared/infrastructure/models/`): SQLModel ORM class. Only the repository touches this.
- **Repository** (`infrastructure/persistence/`): Implements the output port. Maps between ORM model and domain entity. Defines the `I<Name>RepoDep` binding (interface → concrete).
- **Presenter** (`presenter/`): FastAPI router + DTOs. Injects use-case deps and handles HTTP.

## Dependency Injection Pattern

Each layer defines its own `Dep` type alias; downstream layers import and use it:

```python
# infrastructure/persistence/user_repository.py
IUserRepoDep = Annotated[IUserRepository, Depends(UserRepository)]

# usecases/create_user_usecase.py
from src.modules.users.ports.output import IUserRepoDep


class CreateUserUsecase:
    def __init__(self, user_repo: IUserRepoDep): ...


CreateUserUsecaseDep = Annotated[CreateUserUsecase, Depends(CreateUserUsecase)]

# presenter/router.py
from src.modules.users.usecases import CreateUserUsecaseDep


@user_router.post("")
async def create_user(user: CreateUserRequestDto, usecase: CreateUserUsecaseDep): ...
```

For use cases with no repository (e.g. health), `Depends` directly on the concrete class:

```python
HealthCheckUsecaseDep = Annotated[HealthCheckUsecase, Depends(HealthCheckUsecase)]
```

## Adding a New Module

1. Add shared domain types (if cross-module):
   - `src/modules/shared/domain/entities/<name>_entity.py` — pure Pydantic `BaseModel`
   - `src/modules/shared/infrastructure/models/<name>_model.py` — SQLModel ORM class
2. Create `src/modules/<name>/` with:
   - `ports/input/` — input port ABCs *(optional)*
   - `ports/output/<name>_repository.py` — `I<Name>Repository` ABC *(skip if no DB)*
   - `infrastructure/persistence/<name>_repository.py` — concrete repo + `I<Name>RepoDep` *(skip if no DB)*
   - `usecases/<action>_usecase.py` — use-case class + `<Action>UsecaseDep`
   - `presenter/router.py` — FastAPI router
   - `presenter/dtos/<name>_dto.py` — request/response DTOs
3. Import the ORM model in `src/modules/__init__.py` (required for Alembic autogenerate)
4. Run `make newmg name="<description>"`, review, then `make mghead`
5. Register the router in `src/routers.py`

## Key Conventions

- **`@Transactional`**: Apply to use-case methods that write to the database; auto-commits on success, rolls back on exception.
- **Exceptions**: Use custom exceptions from `src/libs/exceptions/base_exception.py` rather than raw `HTTPException`.
- **ORM ↔ Entity mapping**: Repositories map between `<Name>Model` (ORM) and the domain entity. Use cases never import ORM classes.
- **Environment**: Copy `.env.ex` to `.env`. Required vars: `DB_URL`, `JWT_SECRET` (≥ 32 chars). See the root `.env.example`.

## Stack

- **FastAPI 0.124** with `fastapi[standard]` (includes Uvicorn)
- **SQLModel 0.0.27** — ORM models live in `modules/shared/infrastructure/models/` only
- **Alembic 1.17** for migrations
- **PostgreSQL 18** via psycopg 3 (`postgresql+psycopg://` URLs)
- **LangGraph / LangSmith / Redis / Docker SDK** for the generation workflow (later epics)
- **pydantic-settings** for config
