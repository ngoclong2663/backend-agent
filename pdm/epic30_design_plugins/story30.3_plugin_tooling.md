# Story 30.3 — Tooling to add a plugin in a day

**Epic:** [30 — Design plugins](epic30_design_plugins.md) · **Requirements:** FR-44 · **Depends on:** 30.2

## User story

As the person adding design plugins day by day, I want a command that starts a plugin from its kind's template and a
command that checks it the way the gates require, so that each new plugin is quick to make and safe to offer.

## Steps

1. **`make design-plugin-new KIND=<kind> NAME=<name>`**: copies `templates/design/_starter/<kind>/` (a descriptor
   with `status: "draft"`, a component implementing the kind's props contract, a fixture) into the new folder.
2. **Fixtures:** each kind has a synthetic fixture app (BackendSpec + outline) that meets every `needs` key of the
   kind; a plugin's fixture is a small override of it (the design values that select the plugin).
3. **`make design-plugin-check NAME=<name>`**: builds the fixture on mocks in the Node runner and runs the gates (D6):
   375 / 1440 px, light / dark, in every `ready` recipe (or, for a recipe, on every kind's fixture); keyboard and
   focus order; AA contrast on the composite; reduced motion and reduced transparency; loading, empty and error states
   (the mocks' switches); a screenshot `preview.png` written into the folder. Prints a pass / fail table.
4. **Promotion:** a plugin becomes `ready` only by editing its descriptor after a clean check; CI's registry test runs
   the check's fast part (descriptor, fallback, exports exist, fixture builds) for every plugin.
5. **The guide** (`docs/development/design-plugins.md`): kinds, descriptor fields, props contracts, steps, gates,
   naming, what never to do; kept in sync with the starter templates.
6. Tests: the starter of each kind passes the fast checks as generated; the check's result parsing.

## Acceptance criteria

- [x] A new plugin of any kind can be started, built, checked and promoted with the two commands and the guide.
- [x] A plugin with a failing gate cannot be `ready` (the registry test refuses it).

## Verify

`make design-plugin-new KIND=card NAME=try`, `make design-plugin-check NAME=try`, `make test`.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** `scripts/design_plugin.py` (`make design-plugin-new KIND= NAME=`: copies
`templates/design/_starter/<kind>/` with the placeholders filled; `make design-plugin-check NAME= [KIND=] [ARGS=--fast]`:
the fast part (descriptor loads strictly, files, exports, marker, `fixture.json`), then the fixture app built once on
the mocks with every ready recipe scoped under `:root[data-recipe=…]` (`recipe_css(..., scope=)`), signed in per area,
375 / 1440 px, light / dark, `DESIGN_CHECK_RECIPES`, the mock API's `empty` / `error` / `loading` states
(`bga-mock-state`, `DESIGN_CHECK_STATES`), the keyboard pass and the contrast of every text element against its backdrop
(`DESIGN_CHECK_A11Y`; text over images is skipped); a pass / fail table, `check.json`, `preview.png` in the folder).
Starters for all eight kinds; a `fixture.json` for every existing plugin (the media library meets every `needs` key
but `statusFlow`, the board's fixture is agency-projects). Promotion is by hand (`status: "ready"`);
`test_every_plugin_passes_the_fast_checks` runs the fast part for every plugin in `make test`. The guide
(`docs/development/design-plugins.md`) describes the folder, the descriptor, the fixture, what the registry generates
and the kit contracts.

Deviations: reduced transparency is not emulated (Playwright has no switch for it; the recipes use tokens, not
transparency, except glass, which is checked by eye); the "fixture builds" part is not in CI's fast checks (it needs
Docker) — the full check does it. `make design-plugin-check` was run on the Story 30.4 and 30.5 plugins (their
Status notes).
