# Story 30.6 — Font pairings and more looks

**Epic:** [30 — Design plugins](epic30_design_plugins.md) · **Requirements:** FR-44, FR-33 · **Depends on:** 30.3

## User story

As a user drafting an app, I want type and surfaces that give my product its own voice (a reading app set like a
book, a dense tool set like a terminal, a media app dark and quiet), so that the look fits the product and not only
its colours.

## Context

- Fonts: `@fontsource` packages pinned in the base (`frontend_spec/fonts.py`, `make frontend-base`, `make runner-node`);
  app typesetting per script (23.8). Recipes: 12, with families and guards (`recipes.py`).

## Steps

1. **`font-pairing` kind:** a descriptor names a heading and a body font (bundled), an optional mono font, the heading
   weight, case and tracking, the type scale ratio, the scripts it supports (Latin, Japanese, …) and its `choose` text;
   no kit file (the theme writes it). Start with eight pairings drawn from today's bundled fonts, each tagged with the
   archetypes and recipes it suits.
2. **Pairing rules (code):** a pairing that does not cover the app's script is never offered; the requested look's
   heading kind (23.13) filters pairings; the three looks of a draft use at least two pairings.
3. **New recipes** (each a `recipe` plugin with its guards and gates):
   - `cinema` (dark first, quiet surfaces, media-first; not for products that need print-like reading),
   - `paper` (warm off-white, ruled lines, reading-first),
   - `terminal` (mono headings, hairline borders, dense; for developer and data tools only),
   - `luxe` (high contrast type, generous space, thin rules; not for dense back offices).
4. **Density personalities:** recipes may set the default density and the card plugin they look best with
   (`prefers` in the descriptor), used by 30.7 as a tie-breaker, never as a rule.
5. Tests: pairing filters by script and requested heading kind; recipe guards; plugin checks clean.

## Acceptance criteria

- [x] Eight font pairings and four new recipes are `ready` and pass their gates in every kind's fixture.
- [x] A Japanese app is never offered a pairing without Japanese coverage.

## Verify

`make design-plugin-check` for each plugin, `make test`, `make app-design-report`.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** The `font-pairing` kind (nine descriptors, no kit file: `neutral`, `geometric`, `editorial`,
`bookish`, `workshop`, `loud`, `humanist`, `japanese-gothic`, `japanese-mincho`; heading and body from the bundled
faces, weight, case, tracking, the type-scale ratio, the scripts, the recipes each suits). `design.pairing_candidates`
keeps only the pairings that set the app's script (a Japanese app never gets a Latin-only pairing) and the requested
heading kind (23.13); `assign_pairings` gives each look a pairing suited to its recipe, the three looks using at
least two, and the app its first look's (the brief's `fontPairing` when it fits). `plan.pairing_theme` writes the
current look's pairing into the theme's typography (`headingFont`, `bodyFont`, `headingWeight`, `headingCase`,
`tracking`, `ratio`), so `fonts.ts` and `globals.css` follow the look. New recipes: `cinema` (dark, quiet, media
first; prefers the overlay card), `paper` (warm off-white, rules, reading first; prefers side cards), `terminal`
(mono headings, hairlines, dense; back offices and workspaces only; prefers table and compact), `luxe` (high
contrast type, generous space, thin rules; not for back offices; prefers spacious). Tests in `test_app_design.py`
(30.6 block), `test_app_recipes.py`.

Deviation: the prompt does not list the pairings (Story 30.7's size rule); code picks the type for each look, and
the review can switch it. The recipes' gates ran in the Story 30.8 log.
