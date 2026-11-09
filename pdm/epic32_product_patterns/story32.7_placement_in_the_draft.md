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

- [x] A placement in the draft changes where an operation appears, within what the contract and roles allow.
- [x] The tour's steps point at placed actions.

## Verify

`make test`; one real draft whose requirement states a placement (32.8).

## Status

Proposed 2026-11-09.

**Done 2026-11-09 (with deviations).** The placement is the outline entity's **`create`** (`AppEntity.create`:
`onRecord`, `onOpen`, `page`), not an operation-level `placement`: the outline names entities, never operations (Epic
22's rule), and where a record is made is the question the requirement answers ("comments are written on the post",
"a view is counted when the video opens"). `complete_outline` drops `onRecord` / `onOpen` for an entity without a parent
record (the signed-in user's entity left out), with a note. The planner reads it first, in any area (D8: the
requirement wins): `page` keeps a form page of its own, `onRecord` puts the create on the parent's record (one click
or its dialog), `onOpen` makes it when the parent opens when nothing is left to fill in (`screens.drafted_create`,
`on_parent`, `on_open`). `draft_app@v9` is v8 plus one rule in the outline's entities paragraph (the defaults by kind
in a line; `create` only when the requirement says otherwise); the older versions' snapshots gain the schema's one
line, as Epic 30's did. The tour finds a placed action by its operation as before, and a step done by opening a record
(`onOpen`) is a look at that record's page (`binding.action_targets`). Tests: `test_planner_patterns.py` (each
placement, a dropped one, the tour's target), `test_app_drafting.py` (the v9 prompt).

Deviations: no `where: home | list` (a collection action stays where the contract places it); step 3 (the business
workflows proposing placements) is left to the model reading its own brief, since the brief replaces the requirement
in the draft prompt.
