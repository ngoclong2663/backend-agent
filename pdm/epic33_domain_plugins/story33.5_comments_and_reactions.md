# Story 33.5 — The first two features: comments with replies, reactions with state

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** 33.4

## User story

As a member of a community, I want to reply to a comment right under the post and see that I already liked
something, so that the app works like the social products I use every day.

## Context

- These are the two behaviours the real runs got wrong most often (Epic 32's findings, the overview table).
- Both are used by three domains: socials, news and learning (lesson discussion).

## Steps

1. **`comments`** (`attachesTo: content`):
   - data: a comment has its target, its author (from the session), its text, an optional `parentId` (a reply; one
     level of nesting shown, deeper replies flattened under the top comment), timestamps, and `edited`;
   - rules: the author edits and deletes their own comment; moderators delete any; a reply's parent is on the same
     target; readable by everyone who can read the target (Epic 32's public children);
   - target fields: `commentCount`;
   - kit: `CommentThread` (newest or top first, Reply opens an inline box under the comment, "View 3 replies"),
     placed inline under the record or in a sheet, by the type's slot.
2. **`reactions`** (`attachesTo: content`, options: the kinds, e.g. `like`, `save`):
   - data: one row per person, target and kind (a unique constraint);
   - rules: toggle (a second press removes it; never a 409 shown to the person);
   - target fields: `<kind>Count`, `<kind>dByMe` (`likeCount`, `likedByMe`);
   - kit: `ReactionButton` (optimistic, shows the state and the count), on cards and on the record; "Saved" lists the
     person's own saved items.
3. Each with its contract scenarios (reply on another post's comment → 400; a second like → removed, count back),
   mock emulation and UX checks (the like shows its state; a reply is reachable in ≤ 3 clicks from the feed).
4. Tests: both features attached to a synthetic post entity; the backend's generated tests and the mocks' scenarios;
   the kit's component tests.

## Acceptance criteria

- [ ] On a synthetic social app, a member replies to a comment under the post and a like shows its state and count,
      on the mocks and on the generated backend.
- [ ] The 33.1 tasks "reply to a comment" and "like and see it's liked" pass on the socials baseline draft with the
      features attached.

## Verify

`make test`, `make kit-test`, `BGA_SANDBOX_TESTS=1 make test` for the backend files.

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (planner and kit; the live run comes with 33.8).** `templates/features/comments` (a `<Target>Comment`
with `parentId` replies, the author from the session, own edits and deletes, readable by the target's readers,
`commentCount`) and `templates/features/reactions` (a `<Target>Reaction` per person, target and kind, one each by a
unique rule; `<kind>Count` and `my<Kind>Id` per kind). The planner gives feature entities no screens: the target's
cards and page get a `reaction` action per kind (state, count, undo) and its page a `CommentThread` section. Kit:
`ReactionButton` (optimistic toggle, `aria-pressed`, the count, refetch on success) and `CommentThread` (comments with
one level of replies, Reply in place, "View n more replies", delete one's own); `make kit-test` passes. On the socials
reference draft the tasks go from 2 to 4 of 5 (like with its state, like in one click, reply under a comment); follow
comes with 33.8. Tests: `test_feature_screens.py`.
