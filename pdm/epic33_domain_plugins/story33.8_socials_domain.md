# Story 33.8 — Socials

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** 33.5, 33.7

## User story

As a member of a community app, I want to scroll a feed, react and comment where I'm looking, follow people and find
my own posts on my profile, so that it works like the social apps I already know.

## Context

- The first domain, and the first proof of the epic: it uses comments and reactions (33.5).
- Recorded TikTok-like drafts from 2026-11-09 are in `tests/fixtures/drafts/`.

## Steps

1. **Domain** `templates/domains/socials/`: roles `post` (text, photo or video; an author) and `member` (the signed-in
   user); areas Members (pattern `feed`) and Moderators (`back-office`); required features comments and reactions;
   optional follow, notifications, reports.
2. **Features**:
   - `follow` (`attachesTo: person`): follow and unfollow as a toggle, `followerCount`, `followingCount`,
     `followedByMe` on a member; the feed's "Following" tab;
   - `notifications`: someone liked, replied, followed; a bell with the unread count; read on open (polling, D10);
   - `reports`: report a post or comment with a reason; the moderators' queue; hide or dismiss.
3. **Types** (from 33.2's inventories):
   - **short-video feed**: home = one video per screen with the reaction and comment buttons on it, comments in a
     sheet; Discover (search, trending); Create (upload with progress); Profile (grid of the member's videos, counts,
     Follow); Inbox (notifications);
   - **photo and post feed**: home = a column of post cards (author, media, caption, reactions, the two newest
     comments), comments inline on the post page; Profile with a grid; Explore.
4. **The reference requirement** (33.1) generated end to end (with the user's approval) and its tasks passing.

## Acceptance criteria

- [ ] A member likes (state shown), replies to a comment, follows the author and finds their posts on their profile,
      all within 33.1's click budgets.
- [ ] Moderators handle a report from their queue.

## Verify

`make domain-check NAME=socials`, `make test`, `make kit-test`, the real run in the UI.

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (with deviations).** `templates/domains/socials` (roles `content`, `member`; areas members `feed`,
moderators `back-office`; required comments, reactions `like`, follow `Creator` on the post's author) and the type
`short-video-feed`. The **follow** feature: a `<Subject>Follow` per follower and subject (a person's id or a section,
kept as text), `my<Subject>FollowId` and `<subject>FollowerCount` computed on the post by its author field (`match`), a
toggle reading "Follow" / "Following"; it replaces any drafted follow entity (`replacesAnywhere`). Toggles are now
generic: a feature's `kit.toggles` describe them (reactions per kind, follow, enroll, complete). Real drafts
(Antigravity, v10): the socials reference requirement is recognized and merged; re-planned with today's plugins it
passes **5 of 5** tasks (baseline 2).

Deviations: notifications and reports stay the model's entities (not features yet); a comment's author shows "You" or
"Member" (no person profile feature); profiles with follower counts per person are not a page of their own.
