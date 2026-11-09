# Epic 30 — Design plugins: a registry of layouts and looks that grows every day

## Overview

Proposed 2026-11-08 for the user's review. Epic 23 gave dynamic apps a **design space**: the model picks an
archetype, a shell, a view per entity, field roles, a home, a filter style and three looks (style recipes), and code
checks each choice against the contract and builds it from kit variants. The principle holds (Epic 23's D1: choose
from prepared options, never draw a layout). Two things now limit how varied apps can be:

1. **The space is shallow inside each archetype.** Two media catalogues get the same top bar, the same grid of
   16:9 cards and the same record page. What makes products of the same kind look different is missing: horizontal
   shelves, a featured record across the top of the home, a watch page with the player beside a list of what comes
   next, cards with the title over the image or beside it, portrait posters, square covers.
2. **Adding an option is expensive.** One new list view touches the Pydantic literal (`frontend_spec/app.py`), the
   tuple in `frontend/app/design.py`, the prompt's prose (`prompts/draft_app/v5.md`), the kit's TypeScript type
   (`app.ts`), the dispatch in `views.tsx`, the prototype harness and the tests. So options are added rarely, and in
   batches.

This epic turns each option into a **design plugin**: one folder with a descriptor (what it is, when to choose it,
what it needs from the contract, what it falls back to) and its kit files. Code builds the enums, the prompt's
choice lists, the checks and the kit's dispatch from the registry. Adding a layout or a look becomes one folder plus
its checks, small enough to add one a day. The epic then adds the first new plugins: card anatomies, positions,
media layouts, font pairings and recipes.

"Design plugin" is a separate idea from the **feature plugins** of Epic 10 (`templates/plugins/`: auth, storage,
payments, …), which add backend behaviour and its frontend half. Design plugins only change how the same screens are
presented.

| Finding (code, 2026-11-08) | Effect |
|---|---|
| Design values are listed by hand in at least six places (literal, tuple, prompt, TypeScript type, dispatch, prototype) | Adding one option is a cross-cutting change; the lists can drift |
| `RecordsView` dispatches four views; `AppDetail` three; `AppShell` four shells, all `if` chains | No plugin can be added without editing the kit's core files |
| Cards have one anatomy per view (media on top, 16:9) | Posters, square covers, text over the image, media beside the text are not possible |
| `CatalogueRows` groups the home into rows of a 4-card grid | No horizontal shelves, no featured record |
| Story 23.12: frames went from 3 to 6 of 8 distinct, but home and list similarity stayed above target; the greyscale squint measures white space on signed-out screens | Variety cannot be measured well enough to guide new plugins |
| 30 bundled fonts, paired by the design data or the model; 12 recipes | Type and look are wide but not tied to archetypes or recipes as named pairings |

**Requirements:** FR-44 (new, proposed: design plugins), extends FR-37 and FR-33.

## Decisions (proposed 2026-11-08)

| # | Decision | Instead of |
|---|---|---|
| D1 | **A design plugin is one folder** under `agent-api/templates/design/<kind>/<name>/`: `plugin.json` (descriptor), its kit files (`.tsx`, `.css`), a fixture and a preview screenshot | Values spread over the literal, the tuple, the prompt, the type and the dispatch |
| D2 | **Kinds**: `shell`, `list-view`, `detail-view`, `home`, `filters`, `card`, `recipe`, `font-pairing`. Each kind has one props contract in the kit (`TViewProps`, `TDetailProps`, …) that every plugin of the kind implements | A free-form component per plugin |
| D3 | **The registry is the single source**: the Pydantic literals, the answer schema, the prompt's choice lists (from each descriptor's `choose` text), the checks (`needs`) and the kit's generated `design-registry.ts` come from it | Hand-kept lists |
| D4 | **Only the plugins an app uses are copied** into it, as the feature plugins are (22.7) | Every plugin in every bundle |
| D5 | **Code checks, the model chooses** (Epic 23's D1 stays): a choice whose `needs` the contract does not meet falls back to the descriptor's `fallback`, with one note | Trusting the model |
| D6 | **Every plugin passes the same gates** before it can be chosen: design check at 375 / 1440 px, light / dark, in every recipe; keyboard and focus; AA contrast on the real composite; reduced motion and transparency; loading, empty and error states. A plugin that fails is `status: "draft"` and never offered | Merging a variant checked by eye |
| D7 | **Measure first, signed in**: the app design report signs in per area and compares structure (shell, home, view, detail, card) and screenshots of the signed-in screens; the baseline is taken before any new plugin | The signed-out greyscale squint |
| D8 | **Genre patterns, not copies.** A plugin is a pattern many products share (shelves, a featured record, a watch page, a board); never a recreation of one product's look, name or assets | Matching a product's screens |
| D9 | **Same input, same design**: when several plugins fit equally, the draft's seed picks; the review can switch to any plugin that fits, as a spec edit with no engine call | Random choices that cannot be repeated |

```
 templates/design/<kind>/<name>/plugin.json  ──▶  registry (Python)
          │                                         │
          │ kit files (.tsx/.css)                   ├─▶ literals + answer schema (draft_app)
          │                                         ├─▶ prompt choice lists ("choose when …")
          ▼                                         ├─▶ complete_design: needs → fallback + note
 app's frontend: copied only when used  ◀──────────┤
 src/components/app/design-registry.ts (generated)  └─▶ design gates: fixture × recipes × widths × schemes
```

## Stories

| Story | What |
|---|---|
| [30.1](story30.1_signed_in_measurement.md) | The app design report signs in, compares structure and signed-in screens; new baseline |
| [30.2](story30.2_registry.md) | The registry: descriptors, generated enums, prompt lists and kit dispatch; today's values moved in, no visual change |
| [30.3](story30.3_plugin_tooling.md) | Tooling: `make design-plugin-new`, `make design-plugin-check`, registry tests, the guide |
| [30.4](story30.4_cards_and_positions.md) | Card anatomies and positions: media top, side or behind; aspect ratios; record layouts with a side panel |
| [30.5](story30.5_media_layouts.md) | Media layouts: shelves, a featured home, a watch page (with Epic 29's players) |
| [30.6](story30.6_type_and_looks.md) | Font pairings as plugins, new recipes with their guards |
| [30.7](story30.7_choosing_plugins.md) | Choosing among more plugins: archetype candidates, the seed, switching in the review |
| [30.8](story30.8_final_check.md) | Final check: the report against the baseline, real drafts |

Order: 30.1 → 30.2 → 30.3 → 30.4 → 30.5 (after 29.3) → 30.6 → 30.7 → 30.8. After the epic, new plugins are added one
at a time with the guide ([docs/development/design-plugins.md](../../docs/development/design-plugins.md)), each with
its gates, outside any epic.

## Expected output

- Two apps of the same archetype can differ in shell, home, list view, card anatomy, record layout, type and look,
  and the report shows it on signed-in screens.
- Adding a plugin is one folder, one fixture and `make design-plugin-check`; the drafter offers it the same day.
- Media apps (Epic 29) get shelves, a featured home and a watch page.

Not in this epic: model-drawn layouts, per-app CSS written by the model, engine-written view slots by default (23.11
stays an opt-in experiment), static sites (their section library has its own variants, Epic 20), a marketplace or
third-party plugins.

## Status

Proposed 2026-11-08, for review.

**Done 2026-11-09** (branch `feat/epic30-design-plugins`): Stories 30.1–30.8. The registry
(`frontend_spec/design_registry.py`, `templates/design/<kind>/<name>/`) is the single source of the design space;
today's values are plugin folders; 4 cards, 4 detail layouts, shelves, a featured home, a watch page, 4 recipes and 9
font pairings were added and pass the gates; the seed and the candidates pick among them; the signed-in report
measures the golden set (two real Antigravity drafts added). Deviations per story in their Status notes; the plugin
backlog in the guide.
