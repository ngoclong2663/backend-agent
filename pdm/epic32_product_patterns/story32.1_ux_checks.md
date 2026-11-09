# Story 32.1 — UX checks per archetype, measured first

**Epic:** [32 — Product patterns](epic32_product_patterns.md) · **Requirements:** FR-46 · **Depends on:** —

## User story

As the maintainer, I want each kind of product checked by the tasks its people do, before the planner changes, so
that every pattern is judged by how the app behaves and the gain can be shown in numbers.

## Context

- The app design report (`scripts/app_design_report.py`, Story 30.1) signs in per area and fingerprints the look
  (shell, home, view, detail, card, filters). Nothing measures behaviour.
- The evaluation's walker (`orchestrator/evaluation/`, `walk.mjs`, Epic 26 / 28.6) plays each role's tour on the
  mocks; it checks that a workflow can be done, not how many steps or detours it takes.
- Real evidence: the TikTok-like drafts recorded on 2026-11-09 (`tests/fixtures/drafts/tiktok-*`,
  `tests/fixtures/specs/tiktok-*.json`, Story 28.7 findings 4 to 9). Golden apps with consumer areas: `news-feed`
  (feed), `plant-shop`'s shopper area (storefront), `video-library` and `lantern-audio` (catalogue).

## Steps

1. **Structural checks** (`orchestrator/frontend/app/ux_checks.py`, pure, no browser): over a planned app
   (FrontendSpec + contract + access), per area and its archetype. Shared ones: no page a role cannot use (a route
   whose operation the area's roles may not call); no menu item for a role's own interaction records in a consumer
   area. Per archetype, from the pattern descriptor once 32.2 exists, until then a table in the module:
   - `feed`: the home is the main entity's feed; no `table` view; a one-field interaction (like, bookmark) is an
     action on the post; a comment is written from the post; others' comments are readable; no dashboard.
   - `storefront`: add to cart from the product; a cart page and a checkout; orders read-only for the shopper; no
     dashboard and no edit pages for the shopper.
   - `back-office`: every entity in the menu has a list; every create has a form (today's shape is right here).
   Each check returns pass / fail with the page and the section that fail it.
2. **Task checks in the browser** (the report's signed-in pass): for each consumer area, the clicks from the home to
   the area's main task (feed: like the first post; storefront: put the first product in the cart), counted on the
   mocks with the kit's `bga:done` signals (Story 28.1). A task over three clicks fails.
3. **The report** gains a UX block: per area, the archetype, the checks failed, the task clicks; `--ux-only` skips the
   screenshots. The baseline is written now (`tests/fixtures/app-golden/ux-baseline.json`), with the recorded
   TikTok-like drafts planned from their fixtures.
4. Tests: each check on a synthetic spec that passes and one that fails it; the baseline file is the report's output.

## Acceptance criteria

- [ ] The structural checks run on every golden app and the recorded drafts; the baseline is committed.
- [ ] The baseline shows today's failures on the consumer areas (expected: tables, dashboards and form pages in
      `news-feed` and the TikTok-like drafts) and none on the back-office areas.

## Verify

`make app-design-report ARGS=--ux-only`, `make test`.

## Status

Proposed 2026-11-09.
