# Story 33.9 — News

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** 33.5, 33.7

## User story

As a reader I want a front page by section, a clean article page, bookmarks and topics to follow; as a newsroom I
want drafts to be reviewed before they're published, so that the app works like a real news product.

## Context

- Reuses comments and reactions (as bookmarks and, for the aggregator, upvotes).

## Steps

1. **Domain** `templates/domains/news/`: roles `article` (headline, standfirst, body, hero image, section, author,
   published time, reading time), `section`, `author`; areas Readers (pattern `feed` or `catalogue` by type) and
   Newsroom (`back-office`); required features editorial workflow, reactions (`save`); optional comments, follow
   topics.
2. **Features**:
   - `editorial` (`attachesTo: content`): states draft → in review → published → archived; writers submit, editors
     approve, request changes (with a note) or publish; scheduled publishing; only published articles reach readers;
     the newsroom's queue by state;
   - `follow-topics` (`attachesTo: section`): follow a section; "For you" lists followed sections' newest articles.
3. **Types**:
   - **magazine**: front page (a lead story, then rows per section), section pages, the article page (reading width,
     reading time, related articles, comments at the end), Saved;
   - **link aggregator**: ranked list (upvotes and age), the item page with threaded comments, submit a link, New and
     Top tabs.
4. **The reference requirement** generated end to end and its tasks passing.

## Acceptance criteria

- [x] A reader bookmarks an article and follows a section in one click each; an editor publishes a reviewed article
      in two clicks; readers never see drafts.

## Verify

`make domain-check NAME=news`, `make test`, `make kit-test`, the real run in the UI.

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (with deviations).** `templates/domains/news` (role `content` = the article; readers `feed`, newsroom
`back-office`; comments, reactions `save` as the bookmark, follow `Section` on the article's section field) and the type
`magazine`. The real v10 draft (Antigravity) merged the three features (`ArticleComment`, `ArticleReaction`,
`SectionFollow`) and passes **4 of 4** tasks (baseline 1): save with its state in one click, follow a section in one
click, publish in one click, reply under a comment.

Deviations: the editorial workflow is the model's own transitions (they already passed "publish"); "For you" (the
followed sections' newest articles) and the link-aggregator type are not built.
