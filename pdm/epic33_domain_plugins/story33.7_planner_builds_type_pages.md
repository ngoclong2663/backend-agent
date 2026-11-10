# Story 33.7 — The planner builds a type's pages

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47, FR-46 · **Depends on:** 33.2, 33.6

## User story

As a person using a generated app, I want its pages to be the ones products of its kind have (a course page with its
curriculum, a driver's active job with its steps), so that I know my way around without learning a new layout.

## Context

- `screens.py` plans pages per entity and operation; patterns (Epic 32) set the menu, child placement and what roles
  never get.
- A type (33.3) lists each area's pages and their slots, from 33.2's inventories.

## Steps

1. **Type pages**: for an area whose type is set, the planner builds the type's pages: each page's route, its sections
   in order and each section's slot (`media`, `curriculum`, `comment-thread`, `reaction-button`, `job-steps`,
   `chart`, `kpi-row`…) bound to the core entity's fields by role or to a feature's component.
2. **Coverage**: an operation that no type page holds still gets today's generic screen in that area (D6), so nothing
   the contract offers becomes unreachable; the UX checks flag it.
3. **Patterns stay** for the menu and placement inside a type (D6); the type may name its menu explicitly.
4. **New kit sections** for slots the generic kit lacks, each a design-plugin-gated component (states, keyboard,
   contrast, widths): `AppTimeline` (a status history), `AppSteps` (a guided flow), `AppChart` (time series),
   `AppKpis` (figures with trends), `AppMediaFeed` (one record per screen).
5. **The tour** binds to type pages as before (Epic 28): a workflow step finds its page and action.
6. Tests: a synthetic type with three pages planned and covered; an uncovered operation kept on a generic screen with
   a UX-check failure; the golden apps unchanged.

## Acceptance criteria

- [ ] An area with a type gets the type's pages, every slot bound, and every operation reachable.
- [ ] Areas without a type plan exactly as before.

## Verify

`make test`, `make kit-test`, `make app-design-report`.

## Status

Proposed 2026-11-10.
