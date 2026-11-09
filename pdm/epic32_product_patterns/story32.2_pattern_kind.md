# Story 32.2 — The `pattern` kind; `back-office` is today's planner

**Epic:** [32 — Product patterns](epic32_product_patterns.md) · **Requirements:** FR-46, FR-44 · **Depends on:** 32.1

## User story

As the maintainer, I want each kind of product's behaviour in one descriptor read by the registry, so that a new
pattern is a folder, not edits across the planner, and today's apps stay exactly as they are.

## Context

- The registry (`frontend_spec/design_registry.py`, Epic 30) reads `templates/design/<kind>/<name>/plugin.json` for
  eight kinds; descriptors carry `archetypes`, `needs`, `fallback`, `choose`.
- The archetype of each area is drafted today (`app.areas[].design.archetype`, `design.ARCHETYPES`) and completed by
  code (`complete_design`); an app without areas has one design.

## Steps

1. **Kind `pattern`**, one plugin per archetype; the descriptor (validated like the other kinds; lenient loading,
   `strict=True` in tests):
   - `menu`: which entities an area's menu lists: `main` (the area's main entity), `mine` (the role's own records,
     one "mine" entry grouping them), `every` (today's: every entity with a list);
   - `children`: the default placement of a child under its parent, `inline` (actions and a short list on the
     parent's record), `sheet` (a side or bottom sheet opened from it), `tab` (today's), `page`; per child shape:
     `interaction` (a person's one-row reaction: like, bookmark, follow), `contribution` (a person's text on the parent:
     comment, review, reply), `part` (a line of the parent: an order's items, a lesson of a course);
   - `public`: the child shapes readable by every reader of the parent (32.4);
   - `home`: the home flow (`dashboard`, `feed`, `catalogue`, `cart-first`, …: a `home` plugin name or a flow);
   - `never`: what these areas' roles never get (`dashboard`, `edit-others`, `own-interaction-tables`);
   - `checks`: the UX checks of 32.1 that apply to this pattern.
2. **Child shapes from the contract** (code, `screens`): `interaction` is a child whose create has nothing visible to
   fill in (Story 28.7, finding 8: `quick_create`); `contribution` a child whose create is one long-text field plus
   the parent and the owner; `part` a child created with its parent or by staff. Each with a test on a synthetic spec.
3. **`back-office`** (`menu: every`, `children: tab` for every shape, `public: []`, `home: dashboard`, `never: []`)
   is the default, and every area without an archetype gets it. The screens snapshots of the golden apps
   (`tests/fixtures/app-screens/`) stay byte-identical: this story moves no behaviour.
4. The generated plan records each area's pattern (`plan.app.patterns`); the report's fingerprint gains `pattern`.
5. Tests: the registry refuses a hand-written list of pattern names (`tests/test_design_registry.py`); the descriptor's
   schema; every golden snapshot unchanged.

## Acceptance criteria

- [x] `pattern` is a registry kind; `back-office`, `feed` and `storefront` descriptors exist (`feed` and `storefront`
      as `draft` until 32.5 and 32.6).
- [x] Every golden app's screens are unchanged.

## Verify

`make test` (snapshots), `make design-plugin-check KIND=pattern NAME=back-office` once the gates know the kind.

## Status

Proposed 2026-11-09.

**Done 2026-11-09 (with deviations).** The registry's ninth kind, `pattern` (`design_registry.py`: `MENU_ENTRIES`,
`SHAPES`, `PLACEMENTS`, `NEVER`, `UX_CHECKS`, the descriptor's `menu` / `children` / `public` / `home` / `never` /
`checks`, validated: every shape placed, one archetype named after the pattern, the fields refused on other kinds);
`templates/design/pattern/back-office` (ready), `feed` and `storefront` (drafts). `frontend/app/patterns.py`: the child
shapes from the contract alone (the parents from `x-bga.entities[].references`, the user entity left out; a child can
have several parents), `manages`, `area_kind`, `area_pattern`, `area_patterns`; `plan.app.patterns` records each
area's kind and pattern. The UX checks now judge each area by its kind. Every screens snapshot is unchanged; tests in
`tests/test_product_patterns.py`.

Story 32.1's finding (1) is fixed here: an area whose every role manages the main entity's records (a role policy on
its update or delete, or a bypass that reads every record) is `back-office`. Two areas changed: the clinic's front
desk, and Lantern Audio's only signed-in area (its one role is the producer; listeners use it signed out). The UX
baseline went from 49 failures to 41 (`ux-baseline.json` rewritten; each area records its `kind`).

Deviations: the report's fingerprint does not gain `pattern` (every area plans as `back-office` until 32.5, and the
Epic 30 baseline's fingerprints stay comparable); the UX report shows the kind instead. `make design-plugin-check` does
not know the `pattern` kind (a pattern has no kit file to render; its gate is the UX checks it names, run by the
report). The child shapes live in `patterns.py`, not in `screens.py`, so the UX checks and the planner share them
without a cycle.
