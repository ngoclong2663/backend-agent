# Story 32.7 — Placement in the draft, where the pattern's default is wrong

**Epic:** [32 — Product patterns](epic32_product_patterns.md) · **Requirements:** FR-46 · **Depends on:** 32.3

## User story

As a user describing an app, I want what my requirement says about where things happen ("viewers react while
watching", "a review is written after the delivery") to reach the screens, so that the generated app follows my
product, not only its kind.

## Context

- The model writes the BackendSpec, the outline (areas with their archetype, menu, home, each entity's design) and,
  with the business layer (Epic 26), the core workflows; code places every operation (32.3).
- The tour's binding (`business/binding.py`) finds the screen of each workflow step after the screens are planned.

## Steps

1. **`placement` in the outline** (app-only, optional), per operation: `{"operationId", "where": "record" | "list" |
   "home" | "page", "trigger": "button" | "open", "area"}`, written only when the pattern's default would be wrong.
   Code validates each against the contract and the area's roles (an operation the area cannot call, a `record`
   placement for an operation with no record): dropped with a note.
2. **`draft_app@v9`**: v8 plus a short rule (the pattern's defaults named in one line per archetype, from the
   registry; "write a placement only where the requirement says otherwise"); the prompt stays within 10% of v8.
3. **The business workflows** (Epic 26) propose placements: a step done while looking at a record is `where: record`.
4. **The tour follows**: a step bound to a placed action targets that action (`target.action`), so the tour's "do"
   steps point at the like on the video, not at a form page.
5. Tests: on synthetic outlines, a valid placement moves the action and an invalid one is dropped with a note; the
   v9 prompt snapshot; a tour on a placed action.

## Acceptance criteria

- [ ] A placement in the draft changes where an operation appears, within what the contract and roles allow.
- [ ] The tour's steps point at placed actions.

## Verify

`make test`; one real draft whose requirement states a placement (32.8).

## Status

Proposed 2026-11-09.
