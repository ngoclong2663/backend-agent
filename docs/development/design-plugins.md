# Adding design plugins

How to add a new layout or look to the dynamic app kit, one at a time, so generated apps keep getting more varied.
Backlog: [Epic 30](../../pdm/epic30_design_plugins/epic30_design_plugins.md). Background: [Epic 23](../../pdm/epic23_app_design/epic23_app_design.md)
(the design space) and [design-checks.md](design-checks.md) (the measuring tools).

> **Status (2026-11-09):** the registry (`agent-api/src/modules/shared/domain/frontend_spec/design_registry.py`),
> the starters (`agent-api/templates/design/_starter/<kind>/`) and the `make design-plugin-new` /
> `make design-plugin-check` commands are in (Stories 30.2, 30.3). Every value of the design space is a folder under
> `agent-api/templates/design/<kind>/<name>/`.

## What a design plugin is

A design plugin is **one prepared option** the drafter can choose for an app: a shell, a list view, a record layout,
a home, a filter style, a card anatomy, a style recipe or a font pairing. It changes **how** the same screens are
presented, never **what** they do: bindings, operations, forms and permissions stay exactly as code planned them.

It is not a **feature plugin** (`agent-api/templates/plugins/`, Epic 10: auth, storage, payments, …). Feature
plugins add backend behaviour and its UI; design plugins only present.

The rule behind all of it (Epic 23's D1): **the model chooses from prepared options, code checks them, the kit builds
them.** No model-written layout or CSS ever reaches an app.

```
 requirement ─▶ draft_app (model picks plugin names per axis)
                   │
                   ▼
 complete_design (code): is it ready? are its `needs` met by the contract? else its `fallback` + a note
                   │
                   ▼
 app.json design ─▶ kit: design-registry.ts (generated) ─▶ the plugin's component / CSS
```

## Kinds

| Kind | What it decides | Props contract (kit) | Examples today |
|---|---|---|---|
| `shell` | the app's frame and navigation | `TShellProps` (nav, user menu, children) | `sidebar`, `topbar`, `topbar-tabs`, `rail` |
| `list-view` | how a list of records is shown | `TViewProps` (section, entity, records, design) | `table`, `cards`, `media-grid`, `feed`, `board`, `calendar` |
| `detail-view` | how one record's page is arranged | `TDetailProps` (section, entity, record, design) | `record`, `media`, `profile` |
| `home` | the first screen after sign-in | `THomeProps` | `dashboard`, `feed`, `catalogue`, `agenda`, `bento` |
| `filters` | how list filters are offered | `TFiltersProps` | `toolbar`, `chips`, `facets`, `search-first` |
| `card` | the anatomy of one record in grid views (30.4) | `TCardProps` (record, roles, size) | `stacked` (today's) |
| `recipe` | surfaces, borders, shadows, radius, headings, motion (CSS only) | none: CSS over `data-slot` | the 12 of Story 23.7 |
| `font-pairing` | heading / body / mono fonts and the type scale (30.6) | none: the theme writes it | |
| `pattern` | how an area's screens behave for its people: menu, where children go, public children, home, what they never get (Epic 32) | none: the screen planner reads it | |

Pick the smallest kind that does the job. A new card anatomy is a `card`, not a new `list-view`; a new shadow style
is a `recipe`, not a new card.

## The folder

```
agent-api/templates/design/<kind>/<name>/
  plugin.json        descriptor (below)
  <Name>.tsx         the component (not for recipe / font-pairing; today's values are `builtin` in the kit's own files)
  recipe.css         a recipe's CSS (`@root` → `:root`, `@dark` → `:root.dark`); a card may name a `css` file too
  fixture.json       the example app and the design values that select this plugin on it (the gates build it)
  preview.png        written by `make design-plugin-check`; served to the review's Design panel
```

### `plugin.json`

```json
{
  "kind": "list-view",
  "name": "shelves",
  "status": "draft",
  "label": "Shelves",
  "choose": "Media records browsed in rows by group (a category or a parent), each a horizontal strip to scroll.",
  "archetypes": ["catalogue", "storefront", "learning"],
  "needs": ["mediaField", "groupField"],
  "fallback": "media-grid",
  "exports": ["Shelves"],
  "files": ["Shelves.tsx"],
  "marker": "shelves",
  "tags": ["cards"]
}
```

| Field | Rule |
|---|---|
| `kind`, `name` | the folder's; `name` kebab-case, describes the pattern (`shelves`, `split-panel`), never a product or brand |
| `status` | `draft` until `make design-plugin-check` passes; only `ready` plugins are offered (`BGA_DESIGN_INCLUDE_DRAFTS=1` lets the check build a draft) |
| `label`, `choose` | the label the UI shows; one or two sentences for the model: **when** this fits, in terms of the data and the people using it. `choose` goes into the prompt as is, so keep it short and domain-neutral |
| `archetypes` | where it is a candidate; the prompt shows only the candidates of the ranked archetypes (empty: everywhere) |
| `needs` | what the contract must have, a list of keys (`imageField`, `mediaField`, `playableField`, `dateField`, `dateSort`, `statusFlow`, `groupField`, `enumOrReferenceFilter`, `search`, `mainList`, `parentOrChildren`, `longTextField`, `featured`). Each has one check in `frontend/app/design.py` (`_Data.lacks`); add a new key there and in `design_registry.NEEDS`, with a test |
| `fallback` | a `ready` plugin of the same kind used when `needs` are not met; the chain must end in a plugin without needs |
| `exports`, `files` | the component the kit dispatches to and the files copied into an app that uses the plugin (`src/components/design/<kind>/<name>/`, D4). `builtin: true` + `module` (`./views`, `./shells`, `./details`) for the kit's own components instead |
| `dispatch: false` | the kit renders it without a component lookup (the filter styles inside `AppList`'s controls, the dashboard and bento homes in `AppPage`, the calendar's own data loading); the registry still offers and checks it |
| `marker` | the `data-bga-*` value the component puts on its root (`data-bga-view`, `-detail`, `-card`, `-shell`), so the report can fingerprint it |
| `order`, `tags` | the position in the literal and the prompt; free words other code selects by (`cards`: a list view of cards, for Story 23.11's slots) |
| `css`, `family`, `guards`, `prefers` | recipes: the CSS file; `quiet` / `soft` / `bold`; words of products it must never be used for (health, finance, …); the card and density it looks best with (a tie-breaker, Story 30.7) |
| `heading`, `body`, `mono`, `headingWeight`, `headingCase`, `tracking`, `ratio`, `scripts`, `recipes` | font pairings (Story 30.6): bundled fonts only (`frontend_spec/fonts.py`), the scripts it covers, the recipes it suits |
| `menu`, `children`, `public`, `home`, `never`, `checks` | product patterns (Epic 32): the menu entries (`every`, `main`, `mine`, `cart`); a placement (`inline`, `sheet`, `tab`, `page`) for each child shape (`interaction`, `contribution`, `part`, `frontend/app/patterns.child_shapes`); the shapes public on their record; the home flow; what the area's people never get (`dashboard`, `edit-others`, `own-interaction-tables`); the UX checks it must pass (`frontend/app/ux_checks.py`). Named after its one archetype; `back-office` is the planner as it always was. A pattern's `needs` are `signIn` and `purchase`, checked by `frontend/app/patterns.pattern_fits` (not the design checks): an area whose archetype's pattern needs what the contract lacks plans as `back-office` |

### `fixture.json`

`{"app": "media-library", "design": {"entities": {"Lesson": {"view": "shelves"}}}}`: an example app
(`examples/specs/<app>.json` + `examples/app-outlines/<app>.json`) and the design values merged over its outline's
design. The media library (Epic 29: video, audio, images, a topic, dates, captions as children) meets every `needs`
key but `statusFlow`; a board's fixture names `agency-projects`. The check fails when `complete_design` replaces the
plugin on its own fixture (its `needs` are not met there).

## What the registry generates

| From the descriptors | Where |
|---|---|
| the literals `Shell`, `HomeView`, `ListView`, `DetailView`, `FiltersStyle`, `Recipe` (and the answer schema, the JSON schema snapshot) | `frontend_spec/app.py` (`Literal[plugin_names(kind)]`) |
| the prompt's choice lists, only the candidates of the ranked archetypes | `frontend/app/design.design_choices` → `draft_app@v8` `{{ design_choices.<kind> }}` |
| the checks: a choice whose `needs` the contract lacks falls back along the chain, one note | `frontend/app/design._Completion.choose` |
| the recipes' families, guards and CSS | `frontend/app/recipes.py` |
| the kit's dispatch table, importing only what the app uses | `frontend/app/files.design_registry_ts` → `src/components/app/design-registry.ts` |
| the folder plugins copied into an app | `plan["app"]["designPlugins"]`, `scaffold_frontend` |
| the UI's Design panel choices | `GET /api/v1/design-plugins` (`registry_digest`) |

`tests/test_design_registry.py` fails when a kind's names appear as a hand-written list anywhere in `src/`, the kit
or the UI's specs feature, and runs the fast checks (descriptor, files, exports, marker, fixture) for every plugin.

## Add a plugin, step by step

1. **Pick a gap.** Run `make app-design-report` and read its "similar pairs" and "unused" lists, or take the top
   entry of the plugin backlog (Story 30.8's Status). Write down in one sentence what it adds that no plugin has.
2. **Start it.** `make design-plugin-new KIND=<kind> NAME=<name>` copies the kind's starter (`templates/design/_starter/`).
3. **Write the descriptor**: `choose`, `archetypes`, `needs`, `fallback`. If you need a new `needs` key, add its check
   in the registry first, with a test.
4. **Build the component** against the kind's props contract:
   - shadcn components from the kit and theme tokens only (`bg-card`, `text-muted-foreground`, `--radius`, …); no
     hard-coded colours, fonts or sizes in px for text;
   - every state: loading (the kit's skeletons), empty, error, one record, many records, long text;
   - 375 px first, then wide screens; no horizontal page scroll (an intentional scroll strip is fine, with keyboard
     access);
   - keyboard and focus: every interactive element reachable, a visible focus ring, a logical order;
   - motion only through the kit's motion presets, off under `prefers-reduced-motion`;
   - the `marker` on the root element; the existing `data-bga-section` / `data-bga-action` markers kept (the tour and
     the evaluation use them).
5. **Fixture.** Set the design values that select the plugin in `fixture.json`; make sure the fixture app meets the
   `needs` (and add a second fixture that does not, to see the fallback).
6. **Check.** `make design-plugin-check NAME=<name>`: the fixture built once, signed in per area, 375 / 1440 px,
   light / dark, in every ready recipe (`DESIGN_CHECK_RECIPES`); the contrast of every text element against its
   backdrop (text over images is skipped: look at those yourself); the keyboard pass (a focus ring on every focused
   element); the mock API's empty, error and loading states (`bga-mock-state`); pages load with reduced motion. Fix
   until the table is all pass; look at the screenshots (`.data/shots/design-plugin/<name>/`) yourself as well.
   `ARGS="--fast"` runs the descriptor part alone.
7. **Promote.** Set `"status": "ready"`. `make test` runs the registry checks (descriptor, fallback, exports, marker,
   fixture) for every plugin.
8. **Measure.** `make app-design-report`: the fingerprint count should go up, or the plugin should show up where the
   gap was.
9. **Record it.** One line in the plugin backlog (what, why, the report's number before and after), then commit:
   `feat(design): <kind> <name>`.

A plugin a day is the right size. If it takes longer, it is probably two plugins, or it needs a new `needs` key or a
contract feature first; split that out.

## Never

- Copy a specific product's look, name, logo, icons or screens. Plugins are patterns many products share.
- Add CSS or layout the model writes, or a plugin whose output depends on the model's free text.
- Filter or hide records in a plugin; visibility is the backend's (Epic 23's D7).
- Change bindings, forms or actions from a plugin; it only arranges what the section already has.
- Remove or rename a `data-bga-*` marker the tour, the evaluation or the report reads.
- Mark a plugin `ready` without a clean `make design-plugin-check`.
- Add a font that is not bundled (`frontend_spec/fonts.py`; a new font is `make frontend-base` + `make runner-node`).
- Write a plugin around one sample app's domain; describe `choose` by the data's shape and who uses it.

## Kit contracts

| Kind | Props (`components/app/design-types.ts`) | Building blocks to reuse |
|---|---|---|
| `shell` | `TShellProps` (children, design, nav) | `shells.tsx`: `Brand`, `NavLinks`, `BottomTabs`, `TopSearch`, `AreaSwitch`, `useNav` |
| `list-view`, `home` | `TViewProps`, `THomeProps` (+ `listHref`) | `views.tsx`: `Media`, `Meta`, `Title`, `Figure`, `Avatar`, `CardBody`, `viewHref`, `durationText`; `RowActions` |
| `detail-view` | `TDetailProps` (record, design, fields, title, actions) | `details.tsx`: `DetailHeading`, `FieldGrid`, `audioFieldOf` |
| `card` | `TCardProps` (record, roles, title, href, actions, boxed, size) | the same `views.tsx` helpers |

Tests to extend: `agent-api/tests/test_design_registry.py` (the registry), `test_app_design.py` (choices and
fallbacks), `test_app_recipes.py` (recipes), plus the kit's `tsc` and vitest files (`make kit-test`). A change to
shared frontend code must keep `tests/test_static_golden.py` passing.

## Plugin backlog

What to add next, from the signed-in report and the first real drafts (Story 30.8). One line per entry: what, why,
the report's number before and after when it lands.

- **Chips with counts** (filters): the `chips` style showing how many records each value has (needs the list's
  aggregate per filter). Story 30.5 step 4, not done.
- **Dashboard charts at 375 px**: four golden screens scroll sideways on phones (learning-platform home, event-tickets
  organizers, plant-shop management, agency-projects courses); a kit defect in the chart tiles, not a plugin.
- **Thumbnails in the Design panel**: `preview.png` is written per plugin and served through the registry digest's
  `preview` path; the review panel still shows labels and `choose` texts only (Story 30.7 step 4).
- **Children in the split panel**: `split-panel` shows the parents and facts; the record's children stay in the
  page's tabs (AppPage) — a detail plugin that takes the child sections over would need the page to hand them in.
- **Reduced transparency**: no browser switch to emulate it in the gates; `glass` and `cinema` are checked by eye.
- **A `people` card and a `portrait` detail**: round avatars with a name and a role, for members, staff and guests
  (the reports' person entities still render as stacked cards).
- **An `inbox` home** for workspaces: the records assigned to the signed-in user first (the tour's "mine" lists).
- **Font pairings in the review**: the panel switches the look; switching the type alone (a pairing per look is set
  by code) needs a second control.
- **Where an interaction belongs** (a placement input): the draft says what the app is, code decides where every
  operation appears (a form page per create, a tab per child), so a like landed on a tab with a form page instead
  of on the video being watched (Story 28.7, finding 8). Code now makes a create with nothing to fill in a button on
  the record; the model still cannot say "on the parent record, as a button" or "when the record opens" (a view
  counted on open). Proposed: a per-operation `placement` (`where`: record / list / page; `trigger`: button / open)
  in the outline, written by the draft from the business workflows, validated and rendered by code. Now [Epic 32](../../pdm/epic32_product_patterns/epic32_product_patterns.md)
  (product patterns; placement is Story 32.7).
- **Plugin drafting** (the model writes code, gated): when the kit cannot express a screen, a drafting step could
  author a plugin folder (`make design-plugin-new`, then the gates) instead of per-generation code, so the result
  is reviewed once and reused by every later app. The gates are the safety net the engine-written frontends of
  Epic 13 lacked; keep per-generation handwritten frontends out.
