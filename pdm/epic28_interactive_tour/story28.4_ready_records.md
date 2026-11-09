# Story 28.4 — Steps open a record where the action is allowed

**Epic:** [28 — A tour you do](epic28_interactive_tour.md) · **Requirements:** FR-42, FR-39 · **Depends on:** 28.2

## User story

As a user on a tour step that acts on a record, I want the tour to open a record I can act on, or to tell me which
step creates one, so that the button the step points at is always there.

## Context

- `openRoute` (`AppTour.tsx`) opens the record the user is on, else the first record linked from the list page.
- Records carry `allowedActions` per user (Epic 10 policies, Epic 25 access rules); actions follow them, so a
  record in the wrong status, or someone else's, has no button for the step.
- The binding knows each step's status before and after (`statusAfter`) and the step that comes before it.

## Steps

1. **Ready means allowed.** For a step on a record page, the tour reads the list (through the kit's list query, the
   same filters the page uses) and opens the first record whose `allowedActions` contain the step's action; the record
   the user is on wins when it qualifies.
2. **The record from the previous step.** When the previous `do` step created or changed a record (its `operation`
   signal carries the record id), the next step on the same entity opens that record first.
3. **None ready:** the step becomes a note that names what makes one ("A record is ready for this after: <earlier
   step>") with a button that jumps back to that step. When the earlier step belongs to another role, the note says so
   (28.5 adds "Continue as <role>").
4. **Data for the note (code):** `tour_workflows` adds `needs` to steps on records: the earlier step id on the same
   record and, when known, the status it leaves the record in.
5. Tests: synthetic bindings for a chain create → change status → approve; vitest on mocks: the tour opens a record
   whose actions allow the step, the record from the previous step first, and the note when none qualifies.

## Acceptance criteria

- [ ] On the golden workflow apps on mocks, no step on a record page ends with its target missing because of the
      record chosen.
- [x] With no qualifying record the step names the earlier step and can jump to it.

## Verify

`make test`, the kit's vitest, `make up` with a workflow app on mocks.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** `tour_workflows` adds `needs` to `do` steps on record pages: the earlier `do` step of the same
workflow on the same business record, its role and the status it leaves (`statusAfter`). The kit (`tour/records.ts`):
a `do` step whose route ends in a record opens, in order, the record the previous step made or changed (the
`operation` signal's record id, kept per entity), the record the user is on, then the first record of the entity's
list (50 read) whose `allowedActions` allow the step's action (`allowed`, the same rule the buttons follow); candidates
are read through the record's `get` so their actions are current. With none, the step is a centred note "A record is
ready for this after: <earlier step>" with "Go to that step" (a jump to its index), or, when the earlier step is
another role's, "…after <actor> did: <step>" with "Continue as <role>" (28.5). The first acceptance criterion (no
target missing on the golden apps on mocks) is checked by the walker in 28.6 / 28.7.
