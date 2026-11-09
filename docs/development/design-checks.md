# Design checks (Stories 17.7, 20.1–20.3)

Two dev tools measure how generated sites look. Neither is part of the generation pipeline. Both build sites with
the section renderer in the Node sandbox, so they need Docker and the `bga-runner-node` image (`make runner-node`),
plus the dev database (`make dev`). Generated drawings and photos are shown as placeholders; nothing calls an engine
or the image API unless you pass a real engine to the report.

## Section library: `make design-check-fixture`

Builds `agent-api/tests/fixtures/frontend-specs/section-library.json` (every section, layout, form and rhythm) and
runs `scripts/design-check.mjs` on every page at 390 / 768 / 1440 px, light and dark, then checks the measured rules
of `agent-api/templates/nextjs_overlay/DESIGN_CHECKLIST.md`: headline lines, nav height, CTA above the fold, type
sizes, font families and loading, line length.

```bash
make design-check-fixture                                   # every theme preset → .data/shots/design-check/<preset>/
make design-check-fixture ARGS="--combos"                   # six tone, font and preset combinations (Story 20.3)
make design-check-fixture ARGS="--presets minimal --out $PWD/.data/shots/try"
make design-check-fixture ARGS="--recheck --out $PWD/.data/shots/try"   # re-read saved reports, build nothing
make design-check-fixture ARGS="--combos --motion"          # + motion on and JavaScript off (Story 20.6)
```

`--combos` gives each combination the icons and motion its tone maps to (Stories 20.5, 20.6) and another signature
moment. `--motion` adds two passes per page at 1440 px: motion on (time until the hero's call to action is fully
visible, at most 1 s; after scrolling to the end nothing may stay transparent or displaced) and JavaScript off
(nothing hidden).

Dynamic apps are checked with `make design-check-app` (below): since Story 22.8 every dynamic frontend is an app of
the app flow, with no hero or designed home page.

The checks' sandboxes carry their own instance label (`DEV_INSTANCE` in `agent-api/scripts/site_check.py`), so a
running stack's worker does not remove them as orphans mid-build.

Each output folder holds the screenshots and `report.json`; `summary.json` lists the failures per preset. Run it
after changing a section, a variant or the theme CSS.

## Diversity report: `make design-diversity`

Drafts the golden requirements in `examples/requirements/diversity/` (static mode; dynamic apps have no direction
cards since Story 22.8; through the worker's `DraftRunner`, rows deleted afterwards; AI photos off, LangSmith off) and
measures how different the designs are
(`agent-api/src/orchestrator/drafting/design_diversity.py`): the four visual fields of each direction (hero layout, heading
font, hue family, key visual), the difference test, distinct combinations across five drafts of one brief, the
distance between similar businesses, the category's default home order, section frequency, home-composition
similarity, repeated headings and CTA labels, stock phrases left (Story 20.9), and draft time. Since Story 20.4 the
directions are the engine's direction cards; the fake engine draws them from `agent-api/design_data/concepts.json`
with the draft's seed.

```bash
make design-diversity                                      # fake engine, field measures (~10 s)
make design-diversity ARGS="--screenshots"                 # + build each direction, compare first screens (~5 min)
make design-diversity ARGS="--seed 100"                    # repeatable: seeds 100, 101, … per draft
make design-diversity ARGS="--engine claude-code"          # a real engine: costs money, only with the user's yes
```

With `--screenshots`, the first screens are built and compared; the screenshots stay in `shots/<name>-<n>-shots/`.

Output: `.data/reports/design-diversity/<timestamp>/report.md` and `report.json` (+ `shots/`). The epic's targets
(`pdm/epic20_design_diversity/epic20_design_diversity.md`) are written against these measures. With the fake engine
the drafted content is the same example spec for every requirement, so section and copy measures only mean
something with a real engine.

## App kit (Story 22.4)

`make design-check-app` plans an app of the dynamic app flow from an example BackendSpec and outline (no engine),
builds it in the Node runner and screenshots every screen at 375 and 1440 px, light and dark, on the mock API;
parameterised routes take the first fixture record. `ARGS="--app two-entity:project-tracker"` picks another app;
screenshots and `report.json` land in `.data/shots/design-check-app/<app>/`. The rules it measures are in
`templates/nextjs_overlay/DESIGN_CHECKLIST.md` ("App kit").

`agent-api/scripts/app-walk.mjs` walks a running app through every screen and action in a browser (open every page,
open a record from each list, edit and save, add a child from its parent, create, delete from the row menu, record
actions), driven by the app's own `src/content/app.json`, and fails on any failed API call, error state or page error.
Run it in `bga-runner-node` with a project's `node_modules` (the shared `bga-fe-modules-*` volume) mounted next to it:
`node app-walk.mjs <url> <app.json> [shots dir]`; `WALK_HOST=host.docker.internal` when the app runs on the host.

## App design report: `make app-design-report` (Story 23.1; signed in since Story 30.1)

Builds every golden app (`examples/specs/<name>.json` + `examples/app-outlines/<name>.json`, planned without an
engine) on the app kit in the Node sandbox and shoots it on its mock API, **signed in as one demo user per area**
(the auth plugin's demo accounts): home, the main list and one record, at 1440 and 375 px, light. It writes
`.data/reports/app-design/<date>/report.md` (+ `report.json`, a contact sheet of the homes) with:

- the **structural fingerprint** of each area (shell, home, main view, detail, card, filters: from `app.json` and the
  kit's `data-bga-*` markers that the check records), the distinct fingerprints and the areas that share one;
- the **edge similarity** of the signed-in screens (edge maps of layout lines, Jaccard; `design_diversity.edge_signature`),
  per screen, plus the greyscale squint of Epic 20 for comparison;
- the **coverage**: which registry values the golden set uses and which ready plugins none of them uses;
- the design-check failures, the brief's choices code replaced, each draft's recorded time, calls and cost.

`--baseline` also writes `agent-api/tests/fixtures/app-golden/baseline.json` (Story 30.1's baseline was taken on
2026-11-09 before any new plugin: 9 distinct fingerprints of 12 areas, home edge similarity mean 0.25 / max 0.52).

## UX checks: `make app-design-report ARGS=--ux-only` (Story 32.1)

How a planned app behaves for each area's people, judged by the area's archetype; no build, no browser
(`orchestrator/frontend/app/ux_checks.py`). Runs on the golden apps and the recorded real drafts
(`tests/fixtures/drafts/tiktok-*`); writes `ux.json` / `ux.md` next to the report. `--baseline` writes
`tests/fixtures/app-golden/ux-baseline.json`, which `tests/test_ux_checks.py` holds the planner to: a change in how an
area behaves updates it on purpose.

| Check | Areas | Fails when |
|---|---|---|
| `no-unusable-page` | every | a page's operation is not for the area's roles |
| `no-dashboard`, `no-table` | consumer (feed, storefront, catalogue, booking, learning) | a page of figures; a list as a table |
| `no-own-interaction-menu` | consumer | a menu item lists a person's own reactions (likes, progress), not a storefront's cart |
| `no-edit-others` | consumer | an edit page of an entity these roles never create |
| `home-is-feed`, `interaction-on-record`, `contribution-on-record`, `contributions-readable` | feed | the home lists no main entity; a like is not on the record; a comment is a page of its own; each person reads only their own comments |
| `add-to-cart-on-product`, `cart-in-menu` | storefront | adding to the cart is not on the product; no cart in the menu |
| `every-create-reachable` | back-office | a create the roles may call has no form or action |

A record's children are classified by their create request (`child_shapes`): `interaction` (nothing required to fill
in), `contribution` (a person's text), `part` (the rest); `owned` when the owner comes from the session. The main task
(a feed's first interaction, a shop's add to cart) is counted in clicks on the planned screens: 1 on the home's cards,
2 on another page, 3 through a form page.

## Design plugins: `make design-plugin-check` (Story 30.3)

The gates a design plugin passes before it may be `ready` (Epic 30, D6): see
[design-plugins.md](design-plugins.md). It builds the plugin's fixture app once with every ready recipe's CSS scoped
under `:root[data-recipe=…]` and runs `design-check.mjs` with `DESIGN_CHECK_RECIPES`, `DESIGN_CHECK_STATES`
(`bga-mock-state`) and `DESIGN_CHECK_A11Y`, then prints a pass / fail table and writes `preview.png` into the plugin's
folder.
