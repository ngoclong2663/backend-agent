# Story 18.1 — Fail-fast component checks; keep interrupted work

**Epic:** [18 — Generation speed](epic18_generation_speed.md) · **Requirements:** FR-30 · **Depends on:** 17.3

## User story

As a user, I want a custom component that breaks a lint rule to go straight to repair, and a repair that finished
its edit to count even when the engine's stream drops, so that one component does not cost 18 minutes and then
fall back anyway.

## Evidence (`gen_01M66QJWJGAZ7WMHZFR6TJ6KMR`)

- `sandbox_execs`: `eslint` failed (5 s), then `vitest run tests/unit/custom-component.test.tsx` → **timeout after
  302 s**. The ESLint errors were `react-hooks/set-state-in-effect` at
  `useEffect(() => { setQueue(records.map((_, i) => i)); ... }, [records])`: `records` is a new array on every
  render, so the effect re-renders forever and the test never ends.
- `agent-api/src/orchestrator/custom_components.py:319`: the render test runs when `typecheck.ok`, whatever
  ESLint said.
- `repair_custom_component` wrote the fix, then agy ended with
  `{"status": "ERROR", "error": "The stream was interrupted. Please continue the task you were working on."}`
  → `cli_error` → `EngineFailure` → fallback (`custom_components.py:204-205`) without re-running the checks.

## Steps

1. **Skip the render test when lint fails.** In `CustomComponents._checks`, run the render test only when both
   `typecheck.ok` and `lint.ok`. When it is skipped, add nothing for it (the lint failure is the reason).
2. **Shorter render-test timeout.** New setting `frontend_component_test_timeout_seconds: int = 60` (the whole
   site's unit tests take ~5 s). Use it for the `vitest` exec instead of `300`. Also pass
   `--testTimeout=20000` to vitest.
3. **Render-loop guard in the generated test** (`render_test()` in the same file). The test must fail within
   seconds, with a message the repair prompt can act on ("render loop: the component re-rendered more than N
   times; do not set state from an effect on every render"), when the component re-renders without end. Choose
   the mechanism and **prove it on the real failure** (step 6). Candidates, in order:
   - make the `console.error` spy throw on React's "Maximum update depth exceeded" message;
   - a `<Profiler onRender>` wrapper that counts commits and fails the test after N (e.g. 50) commits.
   If neither stops a passive-effect loop, keep the 60 s exec timeout as the guard and append a fixed hint to the
   failure text: "render test timed out: most likely an endless render loop (state set in an effect on every
   render)".
4. **Keep work after an interrupted engine run.** In `_generate`, when `_engine(...)` raises `EngineFailure` for
   `generate_custom_component` or `repair_custom_component`, and the component file exists and changed during
   the call (compare a sha256 taken before the call), run `_checks` anyway:
   - checks pass → keep the component (status `generated`, cached as usual); record the engine failure in the
     `component.generated` event as `engineError`;
   - checks fail → continue the repair loop if attempts are left, else fall back as today.
   Engine failures where the file did not change still fall back immediately.
5. Bump nothing in the prompts here (18.2 does that).
6. **Test fixture from the real run.** Add a test component with exactly the loop above
   (`useEffect(() => setQueue(records.map(...)), [records])` with `records` rebuilt per render), and a sandbox test
   (`BGA_SANDBOX_TESTS=1`) that runs `_checks` on it: it must report the lint failure and must finish in under
   30 s (no render test run). Add a second sandbox test that runs only the render test on the same component
   (lint skipped) and asserts it fails in under 60 s with the render-loop message.

## Acceptance criteria

- [x] With an ESLint failure, the isolated checks do not run the render test.
- [x] The render test's exec timeout comes from `FRONTEND_COMPONENT_TEST_TIMEOUT_SECONDS` (default 60).
- [x] A component with an endless render loop fails the render test within 60 s with a message naming the loop.
- [x] An engine call that fails after changing the component file is followed by the isolated checks; passing
      checks keep the component.
- [x] Unit tests (fake engine, fake sandbox) for: lint failure skips the render test; interrupted engine + changed
      file + passing checks → `generated`; interrupted engine + unchanged file → `fallback`.
- [x] Sandbox tests from step 6 pass.
- [x] `docs/development/test-doubles.md` lists any new fake.

## Status

Implemented (2026-10-30):
- `CustomComponents._checks` skips the render test whenever ESLint fails (`typecheck.ok and lint.ok`).
- Added setting `frontend_component_test_timeout_seconds: int = 60` in `config.py` and `.env.example`; vitest runs with `--testTimeout=20000` and the configured timeout.
- Render-loop guard in `render_test()`: `<Profiler id="loop-guard">` throws if commits exceed 50, and `console.error` spy throws if "Maximum update depth exceeded" is logged.
- `_generate` compares component file sha256 across `_engine` calls; on `EngineFailure` with a changed file, checks run anyway and valid components are kept (status `generated`) with `engineError` on the event.
- Loop component fixture added in `agent-api/tests/fixtures/components/loop_component.tsx`.
- Sandbox tests verify: `_checks` finishes in ~1.2 s reporting lint failure with no render test run (< 30 s); direct render test fails in ~4.3 s with render loop error (< 60 s, down from 302 s hang).

## Verify

`make lint`, `make test`, `BGA_SANDBOX_TESTS=1 make test`. Record in the Status note how long the loop fixture
takes now (before: 302 s).
