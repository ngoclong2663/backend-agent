# Socials: photo and post feed

A column of post cards: each shows its author, its text or photos, its reactions and the newest comments. Opening a
post shows the full thread inline. Profiles are a grid or a list of the member's posts.

## Studied

- Instagram (feed): photo posts in a column, a profile grid, an explore grid.
- Facebook: text and photo posts with reactions and threaded comments.
- Threads: short text posts with photos and reply chains.
- X: short posts with replies, reposts and a following feed.
- Bluesky: short posts with custom feeds and threaded replies.
- Mastodon: federated short posts with a home and a local timeline.
- Pinterest: image pins in a masonry grid with boards.

## People and areas

| Role | Area | First device |
|---|---|---|
| Member | Members (feed, post, explore, profile, notifications) | Mobile-first, works on desktop |
| Moderator | Moderation (report queue) | Desktop |
| Visitor (signed out) | Members, read only | Mobile-first |

## Pages

### Members

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Home (feed) | Menu tab "Home" | `tab-strip`: Following, For you · `form`: a short composer ("What's new?") opening Create · `card-list` of post cards; each card: `author-card` (avatar, name, time, `follow-button` on posts from members not followed), text, `media` (one photo or a swipe set as a scroll), `action-bar` (`reaction-button`: like with likedByMe and likeCount; comments with commentCount; share; save with savedByMe), `comment-preview`: the two newest comments and "view all" | Like, save, open the post, open comments, follow, open the author |
| Post | A card, "view all comments", a notification | `author-card` · text · `media` · `action-bar` · `comment-thread` inline under the post: comments newest or top, replies under each with "view more replies", composer at the bottom | Like, save, comment, reply, like a comment, report, delete own |
| Explore | Menu tab "Explore" | `search-bar`: members, tags, text · `tab-strip`: Top, Latest, People, Tags · `card-grid`: posts with photos (likeCount on hover or below) or `card-list` for text and people | Search, open a post, follow a member |
| Tag | A tag in a post's text, Explore | `record-header`: tag, post count, `follow-button` (follow the tag) · `tab-strip`: Top, Latest · `card-grid` or `card-list`: posts | Follow the tag, open a post |
| Create | Menu button "+" | `media-upload`: photos with previews and order · `form`: text, who can reply · Post | Add photos, post, cancel |
| Profile | Author on a card, a mention | `profile-header`: avatar, name, handle, bio, postCount, followerCount, followingCount, `follow-button` · `tab-strip`: Posts, Replies, Media · `card-grid` (Media) or `card-list` (Posts, Replies) | Follow, open a post |
| Me | Menu tab "Me" | Same as Profile with Edit profile, and tabs Posts, Likes, Saved | Edit, open a post |
| Notifications | Menu tab "Notifications" (unread badge) | `tab-strip`: All, Mentions · `notification-list`: actor (grouped: "x and 3 others"), kind, the post's text or thumbnail, time, read state | Open, follow back |
| Followers / Following | Counts on a profile | `card-list`: members with `follow-button` | Follow, open |

### Moderation

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Reports | Menu "Reports" (home) | `filter-bar`: status, kind (post, comment), reason · `review-queue`: reports (the post or comment excerpt, reason, report count, time) | Hide, dismiss, open |
| Report detail | Row | `record-header`: author, reason, count · the post or comment · `workflow-bar`: open, hidden, dismissed | Hide, dismiss, restore |

## Main tasks

| Task | Role | Path (click by click) | Clicks | Budget |
|---|---|---|---|---|
| like-shows-state: like a post and see it's liked | Member | Home: Like on the post card (1); the button turns on and the count moves | 1 | 1 |
| like-in-one-click: like the first post from the feed | Member | Home: Like on the first card | 1 | 1 |
| reply-to-comment: reply to a comment under a post | Member | Home: "view all comments" on a card (1), Reply on a comment (2), type, Post (3) | 3 | 3 |
| follow-creator: follow a post's author and see it | Member | Home (For you): Follow on the card (1). Or the author (1), Follow (2); the button shows Following | 1 (2) | 2 |
| moderate-report: hide a reported post | Moderator | Reports: Hide on the first report (1), confirm (2) | 2 | 2 |
| Post with a photo | Member | "+" (1), add photo (2), pick it (3), type text, Post (4) | 4 | 4 |
| Save a post and find it later | Member | Home: Save on a card (1); Me (2), Saved tab (3) | 3 | 3 |
| Find my own posts and likes | Member | Me (1) shows Posts; Likes tab (2) | 2 | 2 |
| Report a comment | Member | A post (1), Report on a comment (2), pick a reason, Send (3) | 3 | 3 |

## Data the pages need

- Post card: `text`, `photos`, `createdAt`, `author` (name, handle, avatar, `followedByMe`*), `likeCount`*,
  `likedByMe`*, `commentCount`*, `savedByMe`*, `latestComments`* (two, with author and text).
- Post page: the card's fields plus the comment thread: `text`, `author`, `createdAt`, `parentId`,
  `replyCount`*, `likeCount`*, `likedByMe`*.
- Feeds: Following (newest from followed members) and For you (server ranked), paged by a cursor.
- Profile: `postCount`*, `followerCount`*, `followingCount`*, `followedByMe`*, `isMe`*.
- Notifications: `kind`, `actors` grouped per target*, `target`, `createdAt`, `read`, `unreadCount`*.
- Reports: `target`, `reason`, `status`, `reportCount`*.

\* computed by the server.

## States

- Feed empty for a new member: show members to follow and the For you tab.
- Card actions change at once and roll back on error.
- Post page with no comments: the composer is focused with "Be the first to comment".
- A deleted comment with replies stays as "deleted" so the replies keep their place.
- Photos load with their space reserved, so the column does not jump.
- Notifications read on open; the badge clears when the page is opened.
- Posting: the new post appears at the top of the feed at once, marked "posting" until saved.
- A failed photo upload keeps the text and the other photos, with retry on the failed one.

## Never shown to

- Members: who reported them, hidden posts, other members' Saved, the moderation menu, ranking scores.
- Visitors: the composer, likes and saves (they prompt sign-in), notifications.
- Moderators: members' passwords and private settings; reporter identity is never shown to the author.

## Options

- Comments preview on the card (default two) or none.
- Comments inline on the post page (default) or in a sheet.
- Profile media as a grid (photo-led) or a list (text-led).
- Reactions: one like (default) or a small set of reactions with counts per kind.
- Following feed as home (default) or For you as home.
- Follow tags as well as members, so tag posts join the Following feed.
- Photos required on every post (photo-led) or optional (text-led, default).

## Slots used

- `action-bar`
- `author-card`
- `card-grid`
- `card-list`
- `comment-preview`
- `comment-thread`
- `filter-bar`
- `follow-button`
- `form`
- `media`
- `media-upload`
- `notification-list`
- `profile-header`
- `reaction-button`
- `record-header`
- `review-queue`
- `search-bar`
- `tab-strip`
- `workflow-bar`
