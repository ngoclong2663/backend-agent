# News: link aggregator (upvotes, ranked)

Members submit links or short text posts into topics. The front page is a ranked list by votes and age. Each item
has a page with a threaded discussion. Editors (moderators) approve submissions in topics that need review and
remove what breaks the rules.

## Studied

- Reddit: topic communities, ranked lists, deep threaded comments.
- Hacker News: one ranked list of links, New and Top, threaded comments.
- Lobsters: tagged links, invite-based members, threaded comments.
- Digg: curated and voted links on a ranked front page.
- Product Hunt: daily ranked launches with upvotes and comments.
- Slashdot: editor-approved submissions with threaded discussion.
- Tildes: topic groups, tags and threaded comments.

## People and areas

| Role | Area | First device |
|---|---|---|
| Reader (member) | Readers (front page, item, submit, saved) | Mobile-first, works on desktop |
| Editor (moderator) | Moderation (pending queue, reports, topics) | Desktop |
| Visitor (signed out) | Readers, read only | Mobile-first |

## Pages

### Readers

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Front page | Menu tab "Top" (home) | `tab-strip`: Top, New, Following · `ranked-list`: rank, `reaction-button` upvote (votedByMe, score), title, link domain, topic, submitter, age, comment count (link to the item), `reaction-button` save | Upvote, save, open the link, open comments, open a topic |
| Topic | A topic name on a row, Topics list | `record-header`: topic name, description, member count, `follow-button` (followedByMe) · `tab-strip`: Top, New · `ranked-list` of the topic's items | Follow, upvote, open |
| Topics | Menu "Topics" | `search-bar` · `card-list`: topics (name, description, followerCount, `follow-button`) | Follow, open |
| Item | Comment count on a row, the title for text posts | `record-header`: title, link domain, submitter, age, topic · `action-bar`: `reaction-button` upvote with score, `reaction-button` save, share · `article-reader`: the text body for text posts, or the link out · `filter-bar`: sort comments (top, new) · `comment-thread`: nested replies with collapse, each comment with its own upvote, score, age, Reply | Upvote, save, comment, reply, collapse a branch, report |
| Submit | Menu button "Submit" | `form`: title, URL or text, topic · a duplicate check (an existing item with the same URL shown before posting) | Submit, open the duplicate |
| Saved | Menu tab "Saved" | `card-list`: saved items (title, topic, saved time) | Open, unsave |
| Profile | A submitter's name | `profile-header`: name, joined, karma (sum of scores), `follow-button` · `tab-strip`: Submissions, Comments · `ranked-list` or `card-list` | Follow, open |
| Notifications | Menu tab "Inbox" (unread badge) | `notification-list`: replies to my comments and items, mentions | Open the reply in its thread |

### Moderation

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Pending (editor home) | Menu "Pending" | `filter-bar`: topic · `review-queue`: submissions waiting (title, domain, submitter, topic, age) with Publish and Reject on each row | Open, publish, reject |
| Reports | Menu "Reports" | `review-queue`: reported items and comments (excerpt, reason, report count) | Remove, dismiss |
| Topics admin | Menu "Topics" | `data-table`: topics (name, needs review flag, item count) · `form`: rules text | Add, edit, toggle review |

## Main tasks

| Task | Role | Path (click by click) | Clicks | Budget |
|---|---|---|---|---|
| bookmark-article: save an item and see it's saved | Reader | Front page: Save on a row (1); the button shows saved | 1 | 1 |
| follow-section: follow a topic | Reader | Front page: the topic name on a row (1), Follow (2) | 2 | 2 |
| publish-reviewed: publish a submission in review | Editor | Pending: open the submission (1), Publish (2). Or Publish on its row (1) | 1 (2) | 2 |
| reply-to-comment: reply to a comment under an item | Reader | Front page: comment count on a row (1), Reply on a comment (2), type, Post (3) | 3 | 3 |
| Upvote an item and see the score move | Reader | Front page: upvote on a row (1) | 1 | 1 |
| Submit a link | Reader | Submit (1), type title and URL, pick the topic, Submit (2) | 2 | 2 |
| See the newest items | Reader | Front page: New tab (1) | 1 | 1 |
| Remove a reported comment | Editor | Reports (1), Remove on its row (2), confirm (3) | 3 | 3 |

## Data the pages need

- Ranked row: `title`, `url`, `domain`*, `topic`, `submitter`, `createdAt`, `score`*, `votedByMe`*,
  `savedByMe`*, `commentCount`*, `rank`* (from score and age, decaying over hours).
- Item: the row's fields plus `text` for text posts, `status` (pending, published, rejected, removed).
- Comment: `text`, `author`, `createdAt`, `parentId` (any depth), `score`*, `votedByMe`*, `replyCount`*,
  `depth`*, `removed`.
- Topic: `name`, `description`, `needsReview`, `followerCount`*, `followedByMe`*.
- Profile: `karma`*, `joinedAt`, submissions and comments.
- Duplicate check: `existingItem`* for a URL.

\* computed by the server. The client never sends a score or a rank, only a vote toggle.

## States

- Vote: the arrow turns on and the score moves at once; voting again removes the vote.
- New member's submission in a review topic: it shows on their profile as "pending", never on the front page.
- Item with no comments: the composer is open with "No comments yet".
- Long threads: branches past a depth or a reply count collapse with "show N more replies".
- Removed comment with replies: "removed" stays in place so the replies keep their thread.
- Dead link: the item stays; the domain is shown so readers know where it goes.

## Never shown to

- Readers: pending and rejected submissions of others, who voted on what, reporters' names, moderation menus,
  the raw rank formula.
- Visitors: vote, save, comment and submit (they prompt sign-in).
- Editors: members' passwords and email addresses.

## Options

- Votes: up only (default) or up and down.
- Ranking: score with age decay (default), or newest only.
- Review: all submissions published at once (default) or topics that need an editor's approval.
- Threads: nested with collapse (default) or flat with quoting.
- Text posts allowed (default) or links only.

## Slots used

- `action-bar`
- `article-reader`
- `card-list`
- `comment-thread`
- `data-table`
- `filter-bar`
- `follow-button`
- `form`
- `notification-list`
- `profile-header`
- `ranked-list`
- `reaction-button`
- `record-header`
- `review-queue`
- `search-bar`
- `tab-strip`
