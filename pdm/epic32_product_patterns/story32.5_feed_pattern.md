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

- [x] `feed` is `ready` and passes its gates; `news-feed` and the recorded drafts pass the feed checks.
- [x] The report's UX block shows the feed areas' failures of the baseline gone.

## Verify

`make design-plugin-check KIND=pattern NAME=feed`, `make app-design-report`, `make test`.

## Status

Proposed 2026-11-09.

**Done 2026-11-09 (with deviations).** `templates/design/pattern/feed` is `ready`. On top of 32.3 and 32.4 it adds the
**view counted on open** (step 4): in a consumer area, a record action named like a view (`view`, `watch`, `play`,
`open`, `read`, `visit`) with nothing to fill in, or a child view created with nothing to fill in (`VideoView`), is the
record page's `onOpen` (`screens.on_open`), never a button; the kit's `AppDetail` calls it once per record when the
record has loaded (`useOnOpen`; a failure is silent), and coverage counts it (`frontend_spec/coverage.py`). The
recorded TikTok-like viewers now pass every feed check: Feed + Mine in the menu, a like with one click on the cards and
the video, a comment in a dialog on the video and readable by everyone (for drafts secured since 32.4), the view
counted when the video opens, no dashboard, no table, no edit route or creator's action. `make kit-test` passes
(typecheck, build, scenarios, the kit's tests). The UX baseline went from 41 failures to 29
(`tests/fixtures/app-golden/ux-before.json` keeps the measure before the patterns for 32.8).

Deviations: `news-feed` stays `back-office` (a mixed area: its editors manage posts; the area split is the finding of
32.3), so no golden app plans as a feed yet; the recorded drafts are the evidence. The comment sheet is the kit's
action dialog (step 2: no `AppSheet` yet); the profile page per creator (step 3) needs the main entity's list filtered
by its owner field, which the contract does not always offer, so it is not planned; counts on the cards (32.4 step 3)
are the record's own counter fields when the draft has them (shown by the design's `stat` role), not computed per
parent. The pattern has no `design-plugin-check` gate of its own (no kit files): its gate is its UX checks and
`make kit-test` for the kit parts it uses.
