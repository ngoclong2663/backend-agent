# Story 30.2 — The design plugin registry

**Epic:** [30 — Design plugins](epic30_design_plugins.md) · **Requirements:** FR-44 · **Depends on:** 30.1

## User story

As the person adding a layout or a look, I want to add one folder and have the schema, the prompt, the checks and the
kit pick it up, so that a new option is a small, safe change.

## Context

- Today's values: `Archetype`, `Shell`, `ListView`, `DetailView`, `HomeView`, `FiltersStyle`, `Recipe`
  (`frontend_spec/app.py`); `ARCHETYPES`, `SHELLS`, `VIEWS`, the `needs` checks in `complete_design`
  (`frontend/app/design.py`); `RECIPES`, `FAMILIES`, `STYLE_RECIPES`, `STYLE_WORDS` (`frontend/app/recipes.py`) and
  the recipe blocks of `recipes.css`; the choice prose in `prompts/draft_app/v5.md`; `RecordsView` (`views.tsx`),
  `AppDetail.tsx`, `AppShell.tsx`, `AppPage.tsx` in the kit.
- Feature plugins already copy only what an app uses (`files.frontend_plugins`, `plugins_ts`).

## Steps

1. **Descriptor** (`plugin.json`, validated by a Pydantic model `DesignPluginDescriptor`):
   `kind`, `name`, `status` (`ready` / `draft`), `label`, `choose` (one or two sentences: when to choose it, shown to
   the model), `archetypes` (where it is a candidate), `needs` (typed: `imageField`, `dateField`, `statusFlow`,
   `dateSort`, `enumOrReferenceFilter`, `mediaField`, `groupField`, `minRecords`, …), `fallback` (a plugin of the same
   kind), `exports` (component names), `css` (recipe and card plugins), `guards` (recipes: products it must not be
   used for, from today's `neon` / `playful` rules), `family` (recipes), `marker` (its `data-bga-*` value).
2. **Loader** (`frontend/app/design_registry.py`): reads `templates/design/**/plugin.json` once, checks that every
   `fallback` exists and is `ready`, and exposes per kind the names, descriptors and `needs`.
3. **Generated from the registry:** the literals in `frontend_spec/app.py` (built from the ready names at import; the
   schema snapshot changes when a plugin is added); the answer schema's enums; the prompt's choice lists (a
   `{{DESIGN_CHOICES}}` block rendered from `choose`, new prompt version); `complete_design`'s checks (one function per
   `needs` key, shared); the kit's `src/components/app/design-registry.ts` (imports only the plugins the app uses, maps
   names to components; the kit's dispatchers read it).
4. **Move today's values in** (no visual change): 4 shells, 6 list views, 3 detail views, 5 homes, 4 filter styles,
   12 recipes become plugins; their components move from `views.tsx`, `AppDetail.tsx`, `AppShell.tsx` into their
   folders; `recipes.css` blocks into their recipe folders. Archetype defaults stay in `design.py`, naming plugins.
5. **Guard:** a registry test fails when a plugin's name appears in a hand-written list in `src/` or the kit.
6. Tests: the loader (missing fallback, unknown `needs`, draft plugins not offered); the generated literals and
   prompt block; every golden app's `app.json` and screenshots unchanged (`make design-check-app`, the report's
   fingerprints equal the baseline); static golden test unchanged.

## Acceptance criteria

- [x] Every value of today's design space is a plugin folder; no hand-kept list of them remains.
- [x] The golden apps render the same before and after (fingerprints equal, design check clean).
- [x] An app's bundle contains only the plugins it uses.

## Verify

`make lint`, `pnpm exec tsc --noEmit` (kit), `make test`, `make design-check-app`, `make app-design-report`.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** `frontend_spec/design_registry.py` (`DesignPluginDescriptor`, `DesignRegistry`: loads
`templates/design/<kind>/<name>/plugin.json` once, checks fallbacks (exist, ready, a chain ends without needs), known
`needs`, files; a broken folder is left out with a warning, `strict=True` raises). Generated from it: the literals in
`frontend_spec/app.py` (`Literal[plugin_names(kind)]`; the answer schema and JSON schema follow), the prompt's choice
lists (`design.design_choices` → `draft_app@v7` `{{ design_choices.<kind> }}`, only the candidates of the ranked
archetypes), `complete_design`'s checks (`_Completion.choose`: the drafted plugin if ready, else the default, then down
the fallback chain while a `needs` key is lacking, one note; `_Data.lacks` is the one check per key), the recipes'
families, guards and CSS (`recipes.py` reads the descriptors; `recipes.css` split into `templates/design/recipe/<name>/
recipe.css`), the kit's `design-registry.ts` (`files.design_registry_ts`: imports only the plugins the app's layouts
name; `AppShell`, `RecordsView`, `AppDetail` and `AppList` dispatch through it), the folder plugins copied by the
scaffold (`plan["app"]["designPlugins"]`, D4) and the UI's choices (`GET /api/v1/design-plugins`, `useDesignPlugins`;
`app-design.ts` keeps no list). Today's 4 shells, 6 list views, 3 detail views, 5 homes, 4 filter styles and 12
recipes are folders (`builtin: true` + `module` for the kit's own components, moved into `shells.tsx`, `views.tsx`
(`TableRows`, `PlainCards` from `AppList`) and `details.tsx`). Guard: `test_no_hand_written_list_of_plugin_names_remains`
scans `src/`, the kit and the UI's specs feature (`slots.CARD_VIEWS` and `recipes.DEFAULT_BOLD` now derive from the
registry: `tags: ["cards"]`, the bold family).

Verified: `make kit-test ARGS="--app plant-shop:plant-shop"` (type-check + vitest) clean; the plant shop's generated
registry imports `SidebarShell, TopBarShell`, `CatalogueRows, MediaGrid, RoleCards, TableRows` and nothing else;
`make test`; the signed-in report's fingerprints equal the baseline (see the Status of 30.8 for the run).

Deviations: today's components stay in the kit's core modules (`builtin`) rather than moving each into its folder —
they share helpers and are in every app; folder plugins (30.4 on) are copied only when used, which is what D4 is for.
Filter styles, the dashboard / bento homes and the calendar's data loading are `dispatch: false` plugins (offered,
checked and dispatched by name inside `AppList` / `AppPage`, no component lookup). The literal order changed in one
place (aurora before glass, so the bold defaults keep today's order): schema snapshots regenerated.
