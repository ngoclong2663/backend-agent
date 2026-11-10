# Story 34.5 — Final check

**Epic:** [34 — Designed themes](epic34_designed_themes.md) · **Requirements:** FR-48

## User story

As the user, I want to see the designed themes on real drafts against today's, so that I can judge them.

## Steps

1. The reference requirements drafted again (one at a time); the measures against the baseline.
2. A blind page: for each requirement, the old and the new theme as swatches and a type specimen, in random order; the user picks.

## Acceptance criteria

- [x] The measures and the blind page are recorded in this Status.

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (with deviations).** Real drafts through the API as `admin@bga.local` (dynamic mode, Antigravity,
`LLM_PROVIDER=antigravity`), one at a time, saved as `tests/fixtures/drafts/theme-<name>/`. Final round:

| App | Draft | Time | Concept (the design turn's) | Pairing |
|---|---|---|---|---|
| Yarn shop | `52c9b6f7` | 90 s | Nordic Atelier: crisp bleached linen, soft mist grey, quiet botanical moss | geometric |
| News | `65f27ef2` | 120 s | Morning press broadsheet, deep maritime navy ink on warm rag newsprint | editorial |
| Learning | `0b32cfce` | 90 s | Reading room quiet: oiled timber desks, archival paper, deep sea-teal ink | humanist |
| Drivers | `b1ebcdf1` | 75 s | High-visibility courier dispatch | geometric |
| IoT | `a324f3e6` | 75 s | Sunlit Glasshouse & Living Canopy | geometric |
| Socials | `6f76a16c` | 196 s | Electric night club screen, deep tinted obsidian stage with hot pink pulse | loud |

Every theme was designed in one turn (no repair, no fallback). Measures against the baseline (`make theme-report`):
clichés 1 → 0, grey surfaces 2 → 0, readable 6/6 → 6/6, mean hue gap 101° → 103°, apps sharing faces 2 → 3.

Findings across four rounds, each fixed as a general rule with a regression test:
1. The yarn shop: `follow_requested` repainted the designed surfaces grey from the requested white (34.4).
2. Drivers: a multi-area app crashed the plan (`KeyError: 'delivery.driverEarningsWeek'`): an operation only a later
   area may call and no screen covers was looked up among the first area's operations
   (`tests/test_generation_fixes.py`).
3. Drivers: the turn moved off the requested orange twice and was offered the plain-sans pairing the cliché check
   refuses: the data's theme was kept. Code sets the requested accent; that pairing is not offered.
4. Three of six took the first-listed pairing: the list follows the app's seed (still three `geometric` after it).
5. IoT and news: the draft turned "leaf green" and "navy" into stock hexes the turn had to keep: a colour named only in
   words is followed by its family.
6. IoT: the draft seeded foreign keys with the parent's name (`zoneId: "Zone A - Tomato Benches"`), the repair didn't
   fix it and the draft needed review: `fix_seed_references` points such a key at the parent's seed row.

The blind page: `make theme-report ARGS="--html .data/theme-blind-test.html"` (each app's baseline and designed
theme as swatches and a specimen, in random order, the key folded away). The user's picks: not yet recorded.

Deviations: no app was generated with a designed theme (drafts only; the theme reaches the kit through the same
FrontendSpec `theme` as before); the pairing choice still leans `geometric` (3 of 6); the colours the user asked for
keep several primaries close to the baseline's, so most of the change is in the surfaces and the type.

**Follow-up 2026-11-10 (the user: "the color is too ugly and hard to read", the socials app on Claude Code).** Measured
in a browser (each text against the pixels behind it): 30 of 54 texts below AA on the public pages, the page headings
and filters below AA signed in, at about 1:1. Two kit bugs, not the designed colours:
1. A one-scheme app was drawn in the other scheme: `next-themes` defaulted to light when the app has no toggle, so a
   dark-only app's page took the light rules (the recipe's pale gradient) under its near-white text. The site config
   carries `colorScheme`; the provider forces it (`forcedTheme`). The static goldens were updated for it
   (`UPDATE_SNAPSHOTS=1`: `providers.tsx`, `site.ts`, `.bga/owned.json`; a light-only site renders as before).
2. Recipes painted their own hues: playful's sky-to-mint page and blue shadows, aurora's and glass's violet and cyan
   glows. They mix from the theme's primary and accent now; a test refuses hard-coded hues in a recipe that keeps the
   palette (neon, cinema, luxe, terminal and paper set their own palette: open, the user's decision).
Also: Claude Code's `error_max_structured_output_retries` (a Haiku draft) stopped the draft; the JSON CLI now asks once
without the schema for it, as for a refused schema. Rerun `gen_01M72CCANHBBF2FBCKJ37679PQ` **COMPLETED**: 0 of 54
public and 0 of 55 signed-in texts below AA (the first run's app: 30 and 6).

**Recipe palettes from the app's colours, 2026-11-10 (the user's decision).** The five recipes that set every colour
token themselves (neon: a cyan primary on violet whatever the app's theme) name a palette mood now (`plugin.json`
`palette`); `frontend/app/palettes.py` derives the mood from the app's built palette (neon `tinted-dark`, cinema
`quiet-dark`, luxe `contrast`, terminal `neutral`, paper `paper`), keeps the app's hue and makes the text readable; a
dark mood makes the app a dark-scheme app (`plan.app_plan_theme`). Their CSS keeps the style only. On the socials app
in the browser (each look applied over the built app): every look 0 texts below AA, in the app's pink
(`.data/recipe-looks.html`, before and after). Tests: `tests/test_recipe_palettes.py` (each mood on four real themes:
text 7:1, muted text and the primary's label 4.5:1, the hue within 20°, the mood's character).

