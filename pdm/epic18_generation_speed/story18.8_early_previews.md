# Story 18.8 — Previews start when their lane is done

**Epic:** [18 — Generation speed](epic18_generation_speed.md) · **Requirements:** FR-30, FR-14, Epic 14 · **Depends on:** 18.6, 14.2

## User story

As a user of a dynamic app, I want the backend preview built and started as soon as the backend lane passes, and
the frontend preview to start straight on the live API, so that both are running moments after the generation
completes and the integration step actually runs.

## Evidence (`gen_01M66QJWJGAZ7WMHZFR6TJ6KMR`)

- The backend lane finished at 15:43:01; the generation at 16:06:16. The backend preview was only requested at
  16:06:17 (`runner.py` → `on_completed` → `PreviewService.request_start`).
- `integrate` ran at 16:06:15, found no backend preview and was SKIPPED ("backend preview is not running"); the
  generation was COMPLETED_WITH_WARNINGS (`LANES_INCOMPLETE`) until a later `recheck` (API, 16:10:58) switched the
  frontend to live, which **recreated** the frontend container and restarted the backend.

## Steps

1. **Package the backend early.** When the backend lane completes in dynamic mode and `deployPreview` is on,
   write `backend.zip` (and `seed.json`) with the same code `package_artifacts` uses, as artifact rows (previews
   resolve files only from DB rows). `package_artifacts` must reuse them when the backend repo's HEAD is
   unchanged (store the commit sha on the artifact or in its metadata) and rewrite them otherwise.
2. **Start the backend preview then.** Send the preview `start` for kind `backend` right after step 1. Its CORS
   needs the frontend's origin: reserve the frontend preview's host port at this point (preview row in
   STARTING-free "reserved" form, or a port stored on the generation) so `_options` can include it. Respect
   `_make_room` (preview limit) as today.
3. **Integrate waits briefly.** `integrate` (`orchestrator/integration.py`) waits for the backend preview to be
   RUNNING, up to a bounded time (new setting, e.g. `integration_wait_seconds: int = 180`), before deciding; if the
   backend preview failed or the wait ends, behave as today (keep mocks, SKIPPED).
4. **Frontend starts live.** When the frontend preview starts and the integration switched to live, create it
   directly with `mockApi=False` and the backend URL (`_options`), so no recreate and no backend restart are
   needed. `request_start` must not start the backend a second time.
5. **Failure rules unchanged:** if the frontend lane later fails, the backend preview follows today's
   `startable` rule (`backend_ready`); if the generation is cancelled, stop the early preview.
6. Backend-only and static modes keep today's flow.
7. Tests with the fake engine and fake preview runtime: dynamic run → backend preview requested before the
   frontend lane ends; integrate switches to live; the frontend preview is created once, live; a changed backend
   repo after early packaging rewrites the ZIP; cancellation stops the early preview.

## Acceptance criteria

- [x] In dynamic mode the backend preview starts when the backend lane completes.
- [x] `integrate` finds the backend running and switches to live during the generation; the generation ends
      COMPLETED (not `LANES_INCOMPLETE`) when both lanes pass.
- [x] The frontend preview is created once, already on the live API; no backend restart after completion.
- [x] Early `backend.zip` is reused or rewritten correctly; cancellation stops the early preview.
- [x] Status note: seconds from generation COMPLETED to both previews RUNNING, before (~285 s) and after.

**Status (2026-10-30):**
- In dynamic mode, `package_lane_preview` creates `backend.zip`, `plan.json`, `seed.json`, and records `backend-packaged-head` when the backend lane completes, then immediately triggers backend preview start with early frontend port reservation for CORS.
- `package_artifacts` detects matching commit HEAD and reuses early artifacts without rebuilding; rewrites if backend HEAD changed.
- `integrate` checks backend readiness up to `integration_wait_seconds` (180s) and switches frontend preview to live directly (`mockApi=False`, `apiBaseUrl=backend_url`) without recreate and without restarting the backend container.
- Cancellation cleans up early preview containers.
- Delay from generation COMPLETED to both previews RUNNING reduced from ~285 s to ~0 s (both previews already RUNNING upon job completion). Verified across unit tests and full fake engine runs.

## Verify

`make lint`, `make test`, `BGA_SANDBOX_TESTS=1 make test`, `make up` with the fake engine: dynamic
`project-tracker-dynamic` + `two-entity`; check the `preview.status` and `integration.*` events order.
