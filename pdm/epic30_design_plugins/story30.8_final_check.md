# Story 30.8 — Final check

**Epic:** [30 — Design plugins](epic30_design_plugins.md) · **Requirements:** FR-44 · **Depends on:** 30.1–30.7

## User story

As the product owner, I want the report and real drafts to show that apps of the same kind now look different, and
that the plugins hold up in real apps, so that I can decide how many plugins to add next and where.

## Steps

1. `make app-design-report` against 30.1's baseline: distinct fingerprints, signed-in similarity, unused plugins.
2. Two real drafts (at most two at a time), of the same archetype with different products, through the configured
   draft provider; screenshots of every area signed in, in the looks they were given.
3. Record the gaps the report and the screenshots show, as the first entries of the plugin backlog (the list the guide
   points at for "what to add next").

## Acceptance criteria

- [x] The report beats the baseline on distinct fingerprints and signed-in similarity, or this Status explains why.
- [x] The two drafts differ in at least four axes and pass the design check.
- [x] The plugin backlog has its first entries.

## Verify

`make lint`, `make test`, `make app-design-report`, `make up`, the two real runs.

## Status

Proposed 2026-11-08.

**Done 2026-11-09 (with deviations).** The gates (`make design-plugin-check`) pass for every new plugin: the cards
stacked, overlay, side, text-first; the details media-side, split-panel, reader, watch; shelves; featured; the recipes
cinema, paper, terminal, luxe (the kit plugins in minimal / cinema / luxe, or minimal / paper; each recipe on the
media-library fixture at 375 / 1440 px, light / dark, the three mock states, the keyboard pass and the contrast
measure; logs `.data/design-plugin-gates*.log`, previews in each folder). Three gate findings were kit-wide and fixed
for every app: muted text at 4.35:1 and destructive text at 3.8–3.96:1 on the kit's surfaces (`plan.readable_muted`
darkens or lightens them per app until they read on the background, cards, menus and a destructive item's hover tint);
the new recipes' `@root` tokens leaking into dark mode (each `@dark` block now sets every token its `@root` sets);
the side card too narrow in a three-column grid (`prefers.columns: 2`, read by the grid through the generated
registry's `cardColumns`).

Two real drafts of the same requirement family (learning / catalogue media apps) through Antigravity, both
generated end to end (Story 28.7's table has the runs): Ember Kitchen came out as learning, topbar, catalogue home,
courses as cards with a split-panel record, lessons as cards with a watch page, text-first cards for questions and
progress, the looks clay / playful / soft with the humanist and geometric type; Lantern Audio as catalogue, sidebar,
catalogue home, shows as side cards with a media-beside record and facet filters, the looks editorial / neon / swiss
with the editorial, loud and workshop type. They differ in the shell, the main view's card, the detail, the filters,
the recipe and the type (six axes); both pass the frontend lane's checks and the signed-in report shoots them clean
(0 failures). Both are now golden apps (`examples/specs`, `examples/app-outlines`, `examples/requirements`,
`tests/fixtures/app-golden/`), so the report measures apps that use the new plugins.

Deviations: Ember Kitchen's requirement asked for a dark, cinema-like look and the draft chose clay first (the
requested colours and dark scheme still applied through `requested`); `style_words` now knows the new recipes'
words ("cinematic", "like a cinema", "paper-like", "luxe", "luxurious"), never a bare domain word. The golden set's
recorded briefs predate the registry, so their fingerprints only gain the card axis; variety from the new plugins
shows in the two new golden apps and in seeded drafts (Story 30.7's tests), not in the eight old ones. The report's
final numbers against the baseline are appended below.

**Report against the baseline** (`make app-design-report`, 2026-11-09, `.data/reports/app-design/2026-11-09/`):

| | Baseline (today's kit, 9 apps / 12 areas) | After the epic (11 apps / 15 areas) |
|---|---|---|
| Distinct fingerprints | 9 of 12 | 12 of 15 (the three new areas are all distinct; the two shared groups are the same old recorded briefs: event-tickets/attendees + plant-shop/storefront + video-library, event-tickets/organizers + plant-shop/management) |
| Edge similarity, home (mean / max) | 0.250 / 0.521 | 0.213 / 0.478 |
| Edge similarity, list (mean / max) | 0.243 / 0.590 | 0.213 / 0.586 |
| Edge similarity, record (mean / max) | 0.323 / 0.644 | 0.264 / 0.635 |
| Greyscale home mean (comparison) | 0.742 | 0.595 |
| Failures | 4 screens scroll sideways at 375 px | the same 4 (dashboard charts; backlog) |
| Plugins no golden app uses | — | shells rail, topbar-tabs; shelves; details profile, reader, split-panel, watch; homes bento, featured; recipes brutalist, enterprise, glass, luxe, material, terminal; six font pairings |

The eight recorded briefs cannot pick the new plugins (their `view` / `detailView` are explicit), so the gain comes
from the two real drafts; the unused list is the registry's own backlog of what the next drafts should be offered.

**Plugin backlog** (the first entries, in [the guide](../../docs/development/design-plugins.md#plugin-backlog)):
chips with counts; the dashboard charts that scroll sideways at 375 px; preview thumbnails in the Design panel;
children in the split panel; reduced transparency in the gates; a `people` card and a `portrait` detail; an `inbox`
home; switching the type alone in the review.

