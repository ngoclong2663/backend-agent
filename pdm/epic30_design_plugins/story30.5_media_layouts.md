# Story 30.5 — Media layouts: shelves, a featured home, a watch page

**Epic:** [30 — Design plugins](epic30_design_plugins.md) · **Requirements:** FR-44, FR-43 · **Depends on:** 30.4, 29.3

## User story

As a user of an app built around media records, I want to browse them in rows I can scroll, see one featured record
when I arrive, and watch or listen on a page that shows what comes next, so that the app feels like a media product.

## Context

- `CatalogueRows` groups the home into rows of a 4-card grid by the badge field (23.5).
- Epic 29 adds video and audio players, posters and durations.

## Steps

1. **`shelves` list view:** rows grouped by a `groupField` (an enum or a reference), each a horizontal scroll strip with
   snap points, arrow buttons on wide screens, keyboard scrolling, "See all" to the filtered list; cards from the
   entity's card plugin. Needs: `groupField`, `mediaField`.
2. **`featured` home:** one record across the top (its media large, title, subtitle, the main action), then shelves.
   The featured record is the newest by the feed's date sort, or the first of a `featured` boolean field when the
   entity has one. Needs: `mediaField`, `dateSort` or a boolean field.
3. **`watch` detail view:** the player (video or audio) at the top or the left, title, meta and actions under it, and
   a side list "Up next": records of the same group (the shelves' `groupField`), else the same parent, else the newest;
   one column on phones with the list below. Needs: `mediaField` of kind `video` or `audio`.
4. **`chips` filters with counts** for media lists (the existing `chips` plugin gains an optional count per value when
   the list's aggregate can give it, otherwise unchanged).
5. **List features (code):** the `groupField` and the newest-first sort are added to the list operation before the
   contract is built (Epic 23's D6, `list_features`).
6. Tests: `needs` and fallbacks (no group field → `media-grid`; image but no video → `media` detail); vitest: shelves
   keyboard scrolling; plugin checks (30.3) clean.

## Acceptance criteria

- [x] Media apps can be drafted with shelves, a featured home and a watch page, and pass their gates.
- [x] Without the data a plugin needs, the app falls back with one note and still renders.

## Verify

`make design-plugin-check` for each plugin, `make app-design-report`, `make test`.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** `shelves` (list view; needs `mediaField`, `groupField`: rows by the group (`groupBy`: the
badge's enum, else the first enum without a flow, else a parent), a snap-scrolling strip with arrow buttons on wide
screens and arrow-key scrolling, "See all" to the list filtered to the group, cards from the entity's card plugin;
tagged `whole` so the list loads at once like a board), `featured` (home; needs `mainList`, `mediaField`, `featured`:
the first record flagged `featured`, else the newest (the list sorts newest first: `list_features` adds the date sort
for a featured home as for a feed), across the top with its title, subtitle, meta and the main action, then shelves
or the grid), `watch` (detail; needs `playableField`: the player left, title, meta and actions under it, an "Up next"
list of the same group, else the same parent, else the newest, from the entity's list operation; a video record now
opens on it by default when the entity has a list, else on `media`). Fallbacks with one note each (no group →
media-grid; no media or date → catalogue; image only → media). Tests in `test_app_design.py` (30.5 block);
`make kit-test` clean on an outline using all three.

Deviations: chips with counts (step 4) are not done: the list aggregate the counts would need is not planned for
every filter, and the chips stay as they were (plugin backlog). The shelves group client-side over the loaded list
(up to the list's `maxLimit`), as the catalogue home does, rather than adding a group feature to the API.
