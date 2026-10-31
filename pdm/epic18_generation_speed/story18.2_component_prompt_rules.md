# Story 18.2 — React rules in the component prompts

**Epic:** [18 — Generation speed](epic18_generation_speed.md) · **Requirements:** FR-30 · **Depends on:** 17.3

## User story

As a user, I want the engine told the React rules our checks enforce before it writes a custom component, so
that the first attempt passes and no repair (440 s in the measured run) is needed.

## Evidence

The first attempt of `FlashcardStudy` failed ESLint on two rules the prompt never mentions:

- `react-hooks/set-state-in-effect`: "Calling setState synchronously within an effect can trigger cascading
  renders" (the `setQueue(records.map(...))` effect);
- React Compiler: "Compilation Skipped: Existing memoization could not be preserved" (a `useCallback` whose
  dependency list did not match what the compiler inferred).

The prompt (`agent-api/prompts/generate_custom_component/v1.md`, section "Conventions") lists only naming, types,
colours, network and logic length.

## Steps

1. Add `agent-api/prompts/generate_custom_component/v2.md` (copy of v1) with these rules added to
   "Conventions", in the same terse style:
   - Never call `setState` synchronously in a `useEffect` body. Compute derived values during render,
     initialise state lazily (`useState(() => ...)`), or reset state by giving a child component a `key`.
   - Do not write `useMemo`, `useCallback` or `React.memo`: the React Compiler memoises. If you do write one, its
     dependency list must list every value the callback reads.
   - Data from `useSectionRecords` is a new array on every render: never use it as an effect dependency to copy
     it into state.
2. Add `agent-api/prompts/repair_custom_component/v2.md` (copy of v1) with the same three rules under a short
   "Common failures" heading, plus: "If the render test timed out, look for an endless render loop first."
3. Switch both prompts to `v2`: `component_cache.PROMPT_VERSION` (it versions both prompts and is part of the
   cache key; check `component_cache.py` and `custom_components.py` for every use).
4. Check `prompts/frontend_conventions.md` (shared conventions installed into the engine's workspace): if it
   has a React section, add the same two rules there too, so `repair_frontend` and the page engine path follow
   them. Keep wording identical across files.
5. Update any snapshot test of the rendered prompts (`UPDATE_SNAPSHOTS=1 make test`, then review the diff).

## Acceptance criteria

- [x] `generate_custom_component@v2` and `repair_custom_component@v2` exist and are used; v1 files are unchanged.
- [x] The new rules cover: setState in effects, manual memoisation, `useSectionRecords` data as a dependency.
- [x] The component cache key changes with the prompt version (existing test or a new one shows it).
- [x] Prompt snapshot tests updated and reviewed.

## Status

Implemented (2026-10-30):
- Added `agent-api/prompts/generate_custom_component/v2.md` and `agent-api/prompts/repair_custom_component/v2.md` with explicit React rules: no synchronous setState in useEffect, no manual memoisation (React Compiler memoises), and useSectionRecords returns a new array reference per render that must not be used as an effect dependency.
- In `repair_custom_component/v2.md`, added Common failures guidance highlighting endless render loop detection on test timeout.
- Bumped `PROMPT_VERSION = "v2"` in `src/orchestrator/component_cache.py`.
- Added React rules to `agent-api/prompts/frontend_conventions.md`.
- Added unit test in `test_component_cache.py` proving component cache key changes with prompt version.

## Verify

`make lint`, `make test`. No paid engine run in this story; the final measurement (epic) shows whether the
repair disappears.
