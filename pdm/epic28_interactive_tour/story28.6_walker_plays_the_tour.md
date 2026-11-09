# Story 28.6 — The walker plays the tour

**Epic:** [28 — A tour you do](epic28_interactive_tour.md) · **Requirements:** FR-42, FR-40 · **Depends on:** 28.3, 28.4, 28.5

## User story

As the person reviewing a generated app, I want to know that each role's tour can be played to its end on the real
screens, so that the tour is proof the workflow works in the UI, not only that its buttons exist.

## Context

- The evaluation (26.5, `orchestrator/evaluation/`) walks the app with Playwright (`templates/evaluation/walk.mjs`)
  and switches the automatic tour off (`bga-tour-off`).
- The evaluation is information only (Epic 26's D4).

## Steps

1. **Play mode** in the walker: per role, sign in as its demo user, start the tour from the checklist, and for each
   step: a `look` or `note` step presses Next; a `do` step clicks the spotlighted control, uses "Fill with an
   example", uploads the kit's sample file when a required upload is left (Epic 29's samples; a placeholder file
   until then), presses the submit button, and waits for the step to complete.
2. **Result per step:** `completed`, `skipped` (the tour's own reason), `stuck` (the target, the last signal, a
   screenshot), with the time per step. "Continue as <role>" is followed, so a workflow is played across roles.
3. **Where it runs:** on mocks, in the evaluation run after the screen walk; never on the live API (D3 keeps real
   records out). A failing play never changes the generation.
4. **Business tab:** a "Tour" block per workflow: the steps with their result and the screenshot of a stuck step.
5. Tests: the walker's step logic on a recorded `app.json` (unit, no browser); one browser run in the slow suite only
   (`BGA_SANDBOX_TESTS=1`).

## Acceptance criteria

- [ ] The Business tab shows each core workflow's tour result per step and role.
- [ ] A stuck step has a screenshot and the reason.
- [x] The play never runs against the live API and never changes the generation's status.

## Verify

`make test`, `make up`: a workflow app's evaluation shows the Tour block.

## Status

Proposed 2026-11-08.

**Done 2026-11-09 (unit part).** `walk.mjs` gains the `tour` command: a fresh context per role with the kit's
`bga-mock-api` switch (the runtime config then reports the mock API whatever the server runs, so MSW answers and no
real record is made) and the tour on; it signs in as the role's demo user, waits for the tour (else opens the
checklist's Continue), and per step: `look` / `note` → Next; a `note` with "Continue as <role>" → followed; `do` →
clicks the control the tour marks (`data-bga-tour-current`), "Fill with an example", a sample file for each file
input (`templates/samples/`, copied next to `walk.mjs`; the media samples arrive with Epic 29), the form's submit, then
waits up to 20 s for the step to move on; a step that does not is `stuck` (a screenshot, the failing API calls as the
reason) and the tour's own skip moves past it. `evaluation/tour.py`: `tour_plan` (one demo user per role, each step's
kind for that role, as the kit decides) and `merge_play` (the browser's results on the planned steps; `not reached`
for the rest), `play_tours` drives the walker; the service plays the tours before the checks (progress "playing the
guided tour") and stores them as `report.tour`. The Business tab shows "The guided tour, played": per role and tour,
each step's result, reason, time and the stuck step's screenshot. Tests: `test_interactive_tour.py` (the plan per role,
the merge). Deviation: the slow-suite browser run (`BGA_SANDBOX_TESTS=1`) is not added; the browser play is checked on
the real previews in 28.7.
