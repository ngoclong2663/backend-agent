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

- [x] Under `feed`, comments are readable by every reader of their post and changed by their author alone.
- [x] Under `back-office` and for every person's record that is not a public shape, the access rules behave as today.

## Verify

`make test`; the contract's scenarios for a public child pass on the mocks (`frontend:scenarios`).

## Status

Proposed 2026-11-09.

**Done 2026-11-09 (with a deviation).** `drafting/access.secure_access(spec, public)` takes the child shapes the app's
patterns make public; `contributions` finds a person's text on a parent record in the BackendSpec (a person-tied child
of another entity, the user entity left out, with a required text field of its own); their `get` and `list` keep the
parent's readers (one note per operation), while updates, deletes and actions keep the author's policy. A read policy
the draft wrote itself stays (D8: the requirement said so). `drafting/app.public_shapes` reads the drafted outline's
archetype per area (else the app's, else code's hint) and counts only ready patterns, so nothing changes until `feed`
or `storefront` is ready; the hint is now computed before the access rules. Tests: `test_access_rules.py` (comments
public, likes and deletes the author's, the draft's own policy kept, no pattern no change) and
`test_planner_patterns.py` (a feed drafted end to end passes every feed check, `contributions-readable` included).

Found on the way, fixed in `patterns.manages`: an area's roles manage the main entity when they change or remove other
people's records (a role policy or an ownership bypass on its update or delete). Reading every record (the bypass
Epic 25 gives the roles a creator makes records for) and a role's own actions on a record (view, like) are not
managing; counted as such, a feed's viewers were taken for staff. The baseline is unchanged but for the TikTok-like
creators' studio (`workspace` → `back-office`: they update and delete videos).

Deviation: step 3 (an interaction's count on its parent's cards and record) needs a count per parent the contract does
not offer yet; it moves to 32.5 with the feed's cards.
