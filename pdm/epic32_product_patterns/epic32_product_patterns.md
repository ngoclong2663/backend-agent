# Epic 32 — Product patterns: screens that behave like the product

## Overview

Proposed 2026-11-09 for the user's review. Epic 30 made the **look** of an app varied: shells, cards, record layouts,
type and recipes are design plugins the model picks from. The **behaviour** of the screens did not change: what each
person sees, where they act, in what order. The screen planner (`orchestrator/frontend/app/screens.py`) has one
recipe for every product, and it is a back-office's: a menu item and a table per entity, a form page per create, an
edit page per update, a tab per child, a dashboard of figures. That fits staff managing records. It is wrong for a
viewer scrolling a feed, a customer buying, a patient booking.

The user's TikTok-like runs on 2026-11-09 (Story 28.7, findings 4 to 9) show it. Signed in as a viewer: menu items
for "Comments", "Interactions" and "Dashboard", each a table; a like on a tab of the video with a form page of one
button; an edit route for videos; comments that no other viewer can read. Each was patched as a general rule, but the
cause is one: **the model already says what kind of product it is (the archetype of each area), and nothing but the
look reads it.**

This epic adds **product patterns**: a new design plugin kind, one folder per archetype, saying how that kind of
product behaves. The screen planner reads the pattern of each area. `back-office` is today's output, byte for byte;
`feed` and `storefront` are the first new ones. The model keeps choosing (the archetype, and where an action belongs
when the pattern's default is wrong); code builds the screens. No per-generation frontend code is written by a model.

| Finding (code and real runs, 2026-11-09) | Effect |
|---|---|
| `_Screens.build` plans pages for every entity an area's roles may call; `reach_every_page` puts any page nothing links to in the menu | Viewers get menu items and tables for comments, likes and views |
| `uncovered_operations` requires every operation on a screen; aggregates go to a dashboard page | Consumer areas get a page of counts no viewer asked for |
| The archetype (`app.areas[].design.archetype`) drives `design.ARCHETYPES` (shell, frame, density, home view, list view) only; `screens.py` never reads it | A feed and a back-office get the same screens in different clothes |
| A child's create is a form page plus a tab on its parent (a create with nothing to fill in became a button on 2026-11-09) | A comment is written on a page of its own, away from the video being watched |
| The access rules make a person's records private by default (Epic 25) | Comments on a post are readable by their author alone |
| An edit page is planned for every area whose roles may call `update` on their own records | A viewer's area has a video edit route (its link hidden by `allowedActions`) |
| The outline says `nav`, `home` and each entity's design; nothing about placement or flow | The model cannot say "on the video, while watching" |

**Requirements:** FR-46 (new, proposed: product patterns), extends FR-44, FR-37 and FR-39.

## Decisions (proposed 2026-11-09)

| # | Decision | Instead of |
|---|---|---|
| D1 | **A pattern is a design plugin** of kind `pattern`, one per archetype (`templates/design/pattern/<archetype>/plugin.json`), read by the same registry (Epic 30's D1, D3); the area's archetype picks it | Rules spread through `screens.py` as `if archetype == …` |
| D2 | **`back-office` is today's planner**: every golden app's screens snapshot stays byte-identical under it, and an area without an archetype gets it | A rewrite of the planner |
| D3 | **A pattern says, for its areas' roles**: which entities are in the menu (the main entity, the role's own records), where a child goes (`inline` on the parent, a `sheet` from it, a `tab`, a `page`), which children are public on their parent, what the home flow is, and what these roles never get (a dashboard, edit pages for others' records, tables of their own interactions) | A pattern that is only a look |
| D4 | **Coverage counts actions and counts**: an operation is on a screen when it is a section, an action on a record or a collection, an inline count, or an automatic call (a view counted when a record opens); a page exists only for what a role can do there | One page per operation |
| D5 | **The model chooses, code checks** (Epic 23's D1): the pattern from the area's archetype; a `placement` per operation only where the pattern's default is wrong (32.7), validated against the contract | The model laying out screens, or writing frontend code per generation |
| D6 | **Measure first**: per archetype, UX checks as tasks the walker plays on the mocks ("a viewer likes the video being watched in one click"; "a viewer never meets a table"), the baseline taken before any pattern changes the planner | Judging by screenshots |
| D7 | **Genre patterns, not copies** (Epic 30's D8): a feed is a pattern many products share; never one product's look, name or assets, whatever the requirement names | Recreating a brand |
| D8 | **The requirement wins**: what it states about placement or audience ("comments are private", "staff only") overrides the pattern, with a note, as `requested` does for the look (Story 23.13) | A pattern that ignores the requirement |

```
 draft_app: archetype per area (exists) ──▶ pattern plugin (templates/design/pattern/<archetype>/)
   + placement where the default is wrong     │ menu · children: inline / sheet / tab / page · public children
     (32.7)                                   │ home flow · what these roles never get
                                              ▼
 BackendSpec + contract + outline ──▶ screen planner (screens.py): pages, sections, actions per area
                                              │ coverage: sections, actions, inline counts, automatic calls
 access rules (drafting/access.py) ◀──────────┘ the pattern's public children (comments readable by the post's readers)
```

## Stories

| Story | What |
|---|---|
| [32.1](story32.1_ux_checks.md) | UX checks per archetype, played by the walker on the mocks; the baseline before any change |
| [32.2](story32.2_pattern_kind.md) | The `pattern` kind in the registry; `back-office` is today's planner, byte for byte |
| [32.3](story32.3_planner_reads_the_pattern.md) | The planner reads the area's pattern: menu, child placement, coverage by actions, no pages a role cannot use |
| [32.4](story32.4_public_children.md) | Public children: comments, reviews and replies readable by the parent's readers; the access rules read the pattern |
| [32.5](story32.5_feed_pattern.md) | The `feed` pattern: a vertical feed home, like and comment on the record, the creator's profile, "mine" |
| [32.6](story32.6_storefront_pattern.md) | The `storefront` pattern: add to cart on the product, a cart and checkout flow, my orders read-only |
| [32.7](story32.7_placement_in_the_draft.md) | `draft_app@v9`: a placement per operation where the pattern's default is wrong; the tour follows it |
| [32.8](story32.8_final_check.md) | Final check: real drafts of a social app, a shop and one more archetype, in the UI, against the baseline |

Order: 32.1 → 32.2 → 32.3 → 32.4 → 32.5 → 32.6 → 32.7 → 32.8. After the epic, the other archetypes' patterns
(`booking`, `learning`, `catalogue`, `workspace`) are added one at a time with the design plugin guide, each with its
UX checks, outside any epic.

## Expected output

- Signed in as a viewer of a feed app: a feed to scroll, like and comment on the post being read, other people's
  comments readable, the creator's profile, the viewer's own likes and comments under "mine"; no tables, no dashboard,
  no edit routes for other people's records.
- Signed in as a customer of a shop: products, add to cart from the product, a cart and a checkout, the customer's
  orders; staff keep their back-office in their own area.
- Every golden back-office app plans exactly as before.

Not in this epic: frontend code written by a model per generation; plugin folders drafted by a model (the plugin
backlog's "plugin drafting" entry); static sites (their section library, Epic 20); patterns for the four other
archetypes (after the epic); native-app gestures (swipe to the next video is a scroll, not a gesture library).

## Status

Proposed 2026-11-09, for review.
