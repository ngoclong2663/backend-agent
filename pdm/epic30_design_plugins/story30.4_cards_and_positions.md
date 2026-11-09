# Story 30.4 — Card anatomies and positions

**Epic:** [30 — Design plugins](epic30_design_plugins.md) · **Requirements:** FR-44, FR-37 · **Depends on:** 30.3

## User story

As a user of a generated app, I want records presented in a shape that fits them (a portrait poster, a square
cover, a wide still with the title over it, a picture beside the text) and record pages arranged around what matters,
so that apps of the same kind do not all look alike.

## Context

- Cards today: media on top at 16:9, then title, subtitle, meta, badge (`RoleCards`, `MediaGrid` in `views.tsx`).
- Record pages: `record`, `media` (a 21:9 image on top), `profile` (`AppDetail.tsx`).

## Steps

1. **`card` kind** (new): the anatomy of one record in grid views; props: the record, its field roles, the view's
   size. First plugins:
   - `stacked` (today's: media on top),
   - `overlay` (media fills the card, title and meta over a scrim that keeps AA contrast on the worst pixel),
   - `side` (media left, text right; one column on phones),
   - `text-first` (no media, a large title, meta in a row; for records without images).
2. **Aspect per card:** `aspect` in the entity design: `wide` (16:9), `portrait` (2:3), `square` (1:1), `auto`; code
   picks from the field's name and the archetype when the model gives none (a `poster` → portrait, a `cover` / `album`
   → square).
3. **Record layouts** as `detail-view` plugins: `media-side` (media left, fields right on wide screens), `split-panel`
   (fields left, a side panel with the parent summary and the record's children or related records of the same
   group), `reader` (narrow column for long text fields). Each declares its `needs`.
4. **Grid density** for card views: `columns` (`2`–`6` on wide screens) in the entity design, checked against the card
   anatomy (an `overlay` card at 6 columns keeps its text size).
5. Markers (`data-bga-card`, `data-bga-detail`) for the report's fingerprints.
6. Tests: `complete_design` picks and fallbacks on synthetic specs (no image → `text-first`; a `poster` field →
   portrait); the plugins' checks (30.3) clean.

## Acceptance criteria

- [x] The four card plugins and three detail plugins are `ready` and pass their gates.
- [x] The report (30.1) shows more distinct fingerprints than the baseline on the golden set.

## Verify

`make design-plugin-check` for each new plugin, `make app-design-report`, `make test`.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** The `card` kind (`TCardProps`: record, roles, design, title, href, actions, `boxed`, `size`):
`stacked` (today's two anatomies: boxed in the `cards` view, free-standing in `media-grid`), `overlay` (the media
fills the card, the title over a black 85 % scrim: AA on the worst pixel), `side` (media left, text right, one
column on phones) and `text-first` (no media); all folder plugins under `templates/design/card/`, copied only when
used, drawn by `MediaGrid` / `RoleCards` through `CardOf` (`design-registry.ts` `cards`), each with its
`data-bga-card` marker. `AppEntityDesign.card` / `aspect` (`wide`, `portrait`, `square`, `auto`; code reads the media
field's name: a poster is portrait, a cover or an album square) / `columns` (2–6, clamped): `complete_design` picks
`text-first` for a record without media, `stacked` otherwise, and the card's `needs` fall back like any plugin.
Detail layouts: `media-side` (needs `mediaField`), `split-panel` (`parentOrChildren`: the parents linked and the
status, dates and figures in a side panel; the record's children stay in the page's tabs), `reader`
(`longTextField`: the text first as prose in a reading column). Tests: `test_app_design.py` (30.4 block),
`test_design_registry.py`; `make kit-test` on a media library outline that uses every new plugin (type-check +
vitest clean); the gates (`make design-plugin-check` in minimal / cinema / luxe, see the gates log in the Status of
30.8).

Deviation: `split-panel` shows the parents and facts beside the fields; the record's children are the page's own
tab sections (AppPage), which a detail plugin does not move.
