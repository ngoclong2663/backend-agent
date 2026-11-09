# Story 32.4 — Public children: what people write on a shared record is readable

**Epic:** [32 — Product patterns](epic32_product_patterns.md) · **Requirements:** FR-46, FR-39 (access) ·
**Depends on:** 32.2

## User story

As a viewer, I want to read the comments other people left on a post, and as its creator I want to read the comments
on my posts, so that a conversation is visible to the people it is about.

## Context

- The access rules (`drafting/access.py`, Epic 25) make a record tied to a person private to that person unless the
  requirement says otherwise; staff bypass to read. Since 2026-11-09 a role that only creates a record owns it
  (`_maker_owns`), and a record a role makes for everyone is readable by the other roles (Ember Kitchen's courses).
- So a comment on a video is readable by its author alone: other viewers and the video's creator see none.
- The drafting prompt (`draft_app@v8`) says records belonging to a person are private "unless the requirement says
  otherwise"; most requirements do not say it for comments.

## Steps

1. **The pattern's `public` shapes** (32.2): under `feed`, `contribution` children (comments, replies) are readable
   by every reader of the parent; `interaction` children stay the person's own (my likes), their count public on the
   parent; under `storefront`, `contribution` children (reviews) are public, `part` children (order items) follow the
   order's access.
2. **The access rules read the pattern**: a public child's `list` and `get` keep the parent's readers (no ownership
   policy on reads, the owner's on update and delete); one note per entity ("Comment: readable by everyone who can
   read the video"). A requirement that says otherwise wins (D8): the draft's own policy on the read stays.
3. **Counts on the parent**: an interaction's count is an aggregate shown on the parent's cards and record (32.3's
   inline count), never a list of other people's likes.
4. Tests: on a synthetic feed spec (posts, comments, likes; two viewers and a creator): viewer B reads viewer A's
   comment, the creator reads every comment on their post, B cannot delete A's comment, A's likes are A's own; on a
   synthetic booking spec, a member's booking stays private (no pattern makes it public); the visibility tests of
   Story 23.9 unchanged.

## Acceptance criteria

- [ ] Under `feed`, comments are readable by every reader of their post and changed by their author alone.
- [ ] Under `back-office` and for every person's record that is not a public shape, the access rules behave as today.

## Verify

`make test`; the contract's scenarios for a public child pass on the mocks (`frontend:scenarios`).

## Status

Proposed 2026-11-09.
