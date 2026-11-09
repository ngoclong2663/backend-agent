# Story 30.1 — Measure apps signed in

**Epic:** [30 — Design plugins](epic30_design_plugins.md) · **Requirements:** FR-44, FR-37 · **Depends on:** 23.12

## User story

As the person adding design plugins, I want a report that compares apps as their users see them, signed in, by
structure and by screen, so that I can tell which plugins make apps more different and which gaps remain.

## Context

- `make app-design-report` (23.1, `scripts/app_design_report`): golden apps, 64×40 greyscale first screens, distinct
  frames; Story 23.12 found the greyscale score measures white space and that secured apps were shot on the sign-in
  page.
- The prototype harness (23.0) already signs in as each demo user.

## Steps

1. **Signed in, per area:** the report signs in as one demo user per area (the auth plugin's demo accounts, on mocks)
   and shoots home, the main list and one record, at 1440 and 375 px, light.
2. **Structural fingerprint** per screen, read from `app.json` and the DOM markers (`data-bga-view`, the shell, the
   detail view, the card anatomy once 30.4 adds its marker): distinct fingerprints across the golden set, and the pairs
   that share one.
3. **Screen similarity** on edge maps (layout lines, not colour masses) of the signed-in screens; the greyscale score
   stays in the report for comparison.
4. **Coverage:** which registry values (shells, views, details, homes, cards, recipes) the golden set uses, so unused
   plugins show.
5. **Baseline** on today's kit, stored in this Status and in `.data/reports/app-design/<date>/`.
6. Tests: the fingerprint and the edge similarity on recorded screenshots.

## Acceptance criteria

- [x] The report shoots signed-in screens for every area of every golden app.
- [x] It lists structural fingerprints, similar pairs and unused values.
- [x] The baseline is recorded here.

## Verify

`make app-design-report`, `make test`.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** `scripts/app_design_report.py` signs in per area (one demo user of the area's roles, on the
mocks: `design-check.mjs` `DESIGN_CHECK_LOGIN`, `check_site(passes=…)` runs every area on one build) and shoots home,
the main list and one record at 1440 / 375 px, light. Structural fingerprints (shell, home, view, detail, card,
filters) from `app.json` and the DOM markers (`measure()` records every `data-bga-*` value), edge-map similarity
(`design_diversity.edge_signature` / `edge_similarity`, Jaccard of layout lines; the greyscale squint kept for
comparison), coverage against the registry (used and unused plugins per kind). Tests: `tests/test_design_registry.py`
(the registry) and the report's helpers run in `test_app_design_report.py`.

Baseline (today's kit, before any new plugin; `tests/fixtures/app-golden/baseline.json`,
`.data/reports/app-design/2026-11-09-baseline/`): 9 apps, 12 areas, **9 distinct fingerprints of 12** (frames 6 of
9); shared: event-tickets/attendees + plant-shop/storefront + video-library (topbar, catalogue, media-grid, record,
toolbar) and event-tickets/organizers + plant-shop/management (sidebar, dashboard, table, record, toolbar). Edge
similarity (1440, signed in): home mean 0.25 / max 0.52, list mean 0.24 / max 0.59, record mean 0.32 / max 0.64.
Greyscale (comparison): home mean 0.74. Unused: shells rail and topbar-tabs, detail profile, home bento, filters facets
and search-first, six recipes. Four screens scroll sideways at 375 px (dashboards with charts: learning-platform
home, event-tickets organizers, plant-shop management, agency-projects courses) — a kit defect to fix, recorded in the
plugin backlog (30.8).

Deviation: the signed-in screenshots use the design check (not the prototype harness); the fingerprint's `card` axis
is `-` until Story 30.4 adds the card kind and its marker. Also fixed on the way (seen in the baseline's screenshots):
every item of an area's sidebar showed the same icon, because the icon lookup used the un-prefixed page id
(`plan.app_nav` now strips the area's id and falls back to an icon from the entity's words, never the same icon twice).
