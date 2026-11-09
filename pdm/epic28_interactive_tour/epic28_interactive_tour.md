# Epic 28 — A tour you do: steps that wait for the action, help with forms, a checklist

## Overview

Proposed 2026-11-08 for the user's review. Story 26.4 gave every app with business workflows a guided tour
(react-joyride): one tour per core workflow, steps across pages, another role's step as a note. The tour opens pages
and records by itself and points at the real control. **But it is a slideshow**: the user presses Next until the end,
and nothing they learn is tried. A form step points at the form and moves on; a step whose control needs a record in
a certain status opens the first record it finds, where the action may not be allowed.

This epic turns the tour into something the user **does**: each step that performs an operation waits until the
user has performed it, forms get field-by-field help and an example to fill in, steps pick a record where the action
is allowed (or say which earlier step makes one), and progress is a checklist the user can leave and come back to.
Because the tour then completes only when the workflow really works on the screens, the evaluation's walker can play
it as a check.

| Finding (code, 2026-11-08) | Effect |
|---|---|
| `AppTour.tsx` runs joyride `continuous` with Back / Skip / Next; no step waits for anything | The user reads the steps but never performs one |
| `tour_workflows` (`business/binding.py`) gives each step its `operationId`, page and target, but the kit sends no signal when an operation succeeds | The tour cannot know that a step is done |
| A form step targets the form's submit button only | Nothing helps with what to type; required fields, pickers and uploads are left to the user |
| `openRoute` opens "the record the user is on, else the first record linked from the list" | The action may not be in that record's `allowedActions` (wrong status, someone else's), so the target is missing |
| The tour is stored as `done` / not done per user, role and version | Leaving halfway starts it over; there is no view of what is left |
| Another role's step is a centred note | In a demo the next step can't be followed without signing out and in as the other demo user |
| The evaluation walks screens (26.5) but never plays the tour | A tour can point at controls that exist but do not complete the workflow |

**Requirements:** FR-42 (new, proposed: an interactive tour), extends FR-40.

## Decisions (proposed 2026-11-08)

| # | Decision | Instead of |
|---|---|---|
| D1 | **Steps complete on signals, not on Next.** The kit sends one event when something happens (`bga:done`: an operation succeeded, a page opened, a dialog opened, a field was filled), with the operation id. A step that performs an operation completes on its operation's success | Pressing Next; watching the DOM for changes |
| D2 | **Three kinds of step**: *do* (waits for its operation), *look* (a section that shows data: Next, as today), *note* (another role, or done by the app). The kind comes from the binding, by code | One kind for all |
| D3 | **Never perform for the user.** The tour may fill a form with an example on request, but the user presses the submit button. On the live API this creates real records, and the tour says so once | An auto-play mode that submits |
| D4 | **Examples come from code**: each form's example is the contract's first success scenario body for its operation (the same bodies the mocks and the smoke check use), with references and files picked from what exists on the screen | Values written by the model at draft time |
| D5 | **The record comes from `allowedActions`.** A step on a record page opens a record whose `allowedActions` include the step's action; with none, the step says which earlier step leads there and offers to go to it | The first record in the list |
| D6 | **Progress is per user, per step.** A checklist panel shows each tour's steps done, current, waiting for another role; leaving and coming back continues where the user stopped | One `done` flag per tour |
| D7 | **A "do" step can always be skipped** (a link on the step), and a step that cannot find its target after the timeout falls back to a centred note with the reason; the app is never blocked (26.4's D6 stays) | Trapping the user in a step |
| D8 | **The walker plays the tour.** On mocks, the evaluation's browser plays every role's tour with the examples and records per step: completed, skipped (why), stuck (why). Information only, as Epic 26's D4 | Checking only that targets exist |
| D9 | **General rules only.** The tour's behaviour depends on step kinds, operations, `allowedActions` and forms, never on a product or a workflow name | Rules written for one sample app |

```
 binding (26.3) ──▶ tour_workflows ──▶ app.json workflows
                    + step kind (do / look / note)
                    + form example (contract scenario body)
                    + what makes the record ready (earlier step, status)
                                   │
                                   ▼
 kit: AppForm / AppActions / pages ──bga:done {operationId, page, record}──▶ AppTour
                                                                             │
          spotlight ◀── waits for the signal / field by field on forms ◀─────┤
          checklist ◀── progress per user, step                     ◀─────────┘
          walker (evaluation) plays it on mocks per role → completed / skipped / stuck
```

## Stories

| Story | What |
|---|---|
| [28.1](story28.1_action_signals.md) | The kit sends `bga:done` for operations, pages, dialogs and fields; step kinds in the tour data |
| [28.2](story28.2_do_steps.md) | "Do" steps: the spotlight lets the target through and waits for its operation |
| [28.3](story28.3_form_help.md) | Form help: required fields one by one, "Fill with an example" from the contract, never submitting |
| [28.4](story28.4_ready_records.md) | Steps open a record where the action is allowed, or lead to the step that makes one |
| [28.5](story28.5_checklist_and_roles.md) | A checklist with progress per user; "Continue as <role>" with the demo accounts |
| [28.6](story28.6_walker_plays_the_tour.md) | The evaluation's walker plays each role's tour on mocks and reports per step |
| [28.7](story28.7_final_check.md) | Final check on real drafts |

Order: 28.1 → 28.2 → 28.3 and 28.4 (independent) → 28.5 → 28.6 → 28.7.

## Expected output

- A first-time user signs in, sees the checklist of their role's workflow, and performs each step on the real
  screens: the tour highlights the control, waits until they use it, helps them through the form, and moves on when
  the API says the operation succeeded.
- A step never lands on a record where its button is missing; when no such record exists the tour says which step
  makes one.
- In a demo, a step another role takes offers "Continue as <role>" and the tour goes on in that account.
- The evaluation's Business tab shows, per role, whether its tour can be played to the end on mocks.

Not in this epic: a tour written by the model, tours for apps without workflows, voice or video help, analytics of
where real users drop out.

## Status

Proposed 2026-11-08, for review.

**Done 2026-11-09** (branch `feat/epic28-interactive-tour`, commit e3cdd2d; final check in Story 28.7 on the
Epic 30 branch): the kit's signals, do-steps, form help, ready records, the checklist and the walker's tour play are
in; the two real runs of the final check (Ember Kitchen, Lantern Audio) generated end to end after three rounds of
fixes to the contract's scenarios, the fixtures and the planner (Story 28.7's Status).
