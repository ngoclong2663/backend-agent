# Story 32.3 — The planner reads the area's pattern

**Epic:** [32 — Product patterns](epic32_product_patterns.md) · **Requirements:** FR-46 · **Depends on:** 32.2

## User story

As a person using a generated app, I want my area to show what I came for and let me act where I am, so that I do
not wander through tables and form pages meant for staff.

## Context

- `_Screens.build` (`frontend/app/screens.py`) plans pages for every entity an area's roles may call (`_area_screens`,
  Story 23.10), then `reach_every_page` puts any page nothing links to in the menu.
- `uncovered_operations` (`frontend_spec`) fails a spec with an operation on no screen; it counts sections and record
  actions, so aggregates get a dashboard page and every create a form page.
- One-click creates are record actions since 2026-11-09 (`quick_create`, Story 28.7 finding 8).

## Steps

1. **Menu by the pattern**: `main` and `mine` areas list the main entity and one "mine" entry (the role's own records
   of every shape, as tabs of one page); `reach_every_page` does not add menu items in such areas (a page reachable
   only from a record is fine).
2. **Children by placement**: `inline` puts the child's create as an action on the parent's record and its recent
   rows in a short list on the record page; `sheet` opens the child's create form and list in a sheet from the
   record (a new kit section, `AppSheet`, keyboard and focus as Epic 30's gates ask); `tab` and `page` are today's.
3. **Coverage by actions**: an operation is covered when it is a section, an action, an inline count (an aggregate
   shown on a record or a card: likes on a post) or an automatic call (32.5's view counted when the record opens).
   `uncovered_operations` learns these; the pair check (`check_spec_pair`) and the scenarios check are unchanged.
4. **No pages a role cannot use**: an area gets an edit or create page only when its roles may call the operation on
   records they reach; `never: edit-others` drops edit pages for records the role does not own; `never: dashboard`
   puts the figures as inline counts or leaves them to the staff area.
5. Tests: on the recorded TikTok-like drafts under `feed` (from their fixtures): no tables in the viewers' area, no
   comment page, no viewer edit route; the 32.1 structural checks pass for those areas and still pass for every
   back-office area; the golden snapshots of back-office apps unchanged.

## Acceptance criteria

- [ ] Under a consumer pattern, an area's menu is the main entity and "mine"; children follow the placement; no page
      a role cannot use.
- [ ] `uncovered_operations` is empty for every golden app and the recorded drafts.

## Verify

`make test`, `make app-design-report ARGS=--ux-only` against the 32.1 baseline, `make kit-test`.

## Status

Proposed 2026-11-09.
