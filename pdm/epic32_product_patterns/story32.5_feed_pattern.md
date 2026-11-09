# Story 32.5 — The `feed` pattern

**Epic:** [32 — Product patterns](epic32_product_patterns.md) · **Requirements:** FR-46 · **Depends on:** 32.3, 32.4

## User story

As a viewer of a social, news or short-video app, I want to scroll a feed, react and comment on what I am looking at,
open the person who posted it and find my own activity in one place, so that the app works the way such apps do.

## Context

- Archetype `feed` today: top bar, narrow frame, `feed` home and list view (`design.ARCHETYPES`), the `watch` detail
  for video records (Epic 30, Story 30.5), the players of Epic 29.
- Golden: `news-feed` (posts, sources, bookmarks, upvotes); recorded drafts: the TikTok-like apps of 2026-11-09.

## Steps

1. **Descriptor** `templates/design/pattern/feed/plugin.json`: `menu: [main, mine]`; `children`: `interaction` →
   `inline`, `contribution` → `sheet`, `part` → `tab`; `public: [contribution]`; `home: feed`; `never: [dashboard,
   edit-others, own-interaction-tables]`; the 32.1 feed checks.
2. **Home**: the main entity's feed (newest first; a media record as a full-width player card, one per screen on
   phones, the next one by scrolling); each card carries its interactions as buttons with their counts and opens its
   comments in the sheet.
3. **The person who posted**: a profile page per creator (their records as a grid, their counts), reached from the
   card's byline. Needs the contract to list the main entity by its owner field (a filter), else no profile and a note.
4. **A view counted on open** (when the contract has one: a custom `view` / `watch` action, or a view entity created
   with nothing to fill in): called once when the record opens or a media card plays for two seconds, never a
   button; covered as an automatic call (32.3).
5. **"Mine"**: one page with tabs for the role's own interactions and contributions, read-only lists that open the
   record they belong to.
6. Plugin gates (Epic 30's D6) for the new kit parts (feed cards with actions, the sheet, the profile): widths,
   schemes, recipes, keyboard, contrast, states.
7. Tests: the recorded TikTok-like drafts and `news-feed` plan under `feed`; the 32.1 feed checks pass; the task
   "like the first post" takes one click from the home.

## Acceptance criteria

- [ ] `feed` is `ready` and passes its gates; `news-feed` and the recorded drafts pass the feed checks.
- [ ] The report's UX block shows the feed areas' failures of the baseline gone.

## Verify

`make design-plugin-check KIND=pattern NAME=feed`, `make app-design-report`, `make test`.

## Status

Proposed 2026-11-09.
