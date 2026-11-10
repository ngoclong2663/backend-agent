# Socials: short-video feed

One clip per screen, scrolled vertically. The actions sit on the clip itself, comments open in a sheet over it,
and the profile is a grid of the member's clips. Members both watch and post. Moderators work a report queue.

## Studied

- TikTok: full-screen vertical clips with a For you and a Following feed.
- Instagram Reels: vertical clips inside a wider photo network.
- YouTube Shorts: vertical clips inside a long-form video service.
- Snapchat Spotlight: vertical clips beside camera messaging.
- Kwai: short-video community with creator follow and duets.
- Triller: music-led short clips with creator profiles.

## People and areas

| Role | Area | First device |
|---|---|---|
| Member | Members (watch, post, profile, inbox) | Mobile-first |
| Moderator | Moderation (report queue) | Desktop |
| Visitor (signed out) | Members, read only | Mobile-first |

## Pages

### Members

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Home (feed) | Menu tab "Home" | `tab-strip`: For you, Following · `media-feed`: one clip per screen; over each clip: `author-card` (avatar, handle, `follow-button` with followedByMe), caption, sound or tag text · `action-bar` on the clip: `reaction-button` (like, likedByMe, likeCount), comments (commentCount, opens `comment-thread` in a sheet), share, report | Like, open comments, follow, open the author, share, report, scroll to next |
| Comments sheet | Comments button on a clip | `comment-thread`: top comments first (author, text, time, likeCount, likedByMe, reply count, "view replies"), replies one level under their comment, a composer pinned at the bottom with "Replying to @x" | Comment, reply, like a comment, report, delete own |
| Discover | Menu tab "Discover" | `search-bar`: members, tags, captions · `card-row` per trending tag: clips (cover, viewCount) · `card-grid`: search results (cover, likeCount) | Search, open a tag, open a clip in the feed |
| Tag | A tag in a caption or Discover | `record-header`: tag, clip count · `card-grid`: clips (cover, viewCount) | Open a clip |
| Create | Menu button "+" | `media-upload`: pick a clip, preview, upload progress · `form`: caption, who can comment · Post | Pick, post, cancel |
| Profile (member) | Avatar on a clip, a mention, search | `profile-header`: avatar, name, handle, bio, followerCount, followingCount, likeCount total, `follow-button` · `tab-strip`: Clips, Liked (own profile, or when public) · `card-grid`: clips (cover, viewCount) | Follow, open a clip, see followers |
| Me | Menu tab "Me" | Same as Profile, with Edit profile instead of Follow, and the Liked tab | Edit, open a clip, sign out |
| Followers / Following | Counts on a profile | `card-list`: members (avatar, handle, `follow-button`) | Follow back, open a member |
| Inbox | Menu tab "Inbox" (unread badge) | `tab-strip`: All, Likes, Comments, Follows · `notification-list`: actor, what happened (liked your clip, replied to your comment, followed you), time, clip thumbnail, read state | Open the clip or comment, follow back |
| Clip (single) | A notification, a grid cover, a shared link | `media`: the clip · `author-card` · `action-bar` · `comment-thread` (sheet on phone, beside on desktop) | As on the feed |

### Moderation

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Reports | Menu "Reports" (home) | `filter-bar`: open, resolved; kind: clip, comment; reason · `review-queue`: reports (thumbnail or comment text, reason, reporter count, first reported) | Hide, dismiss, open |
| Report detail | Row in Reports | `media` or the comment text · `record-header`: author, posted, reason, report count · `card-list`: other reports on it · `workflow-bar`: open, hidden, dismissed | Hide, dismiss, warn author |
| Hidden content | Menu "Hidden" | `data-table`: hidden items (author, reason, moderator, time) | Restore |

## Main tasks

| Task | Role | Path (click by click) | Clicks | Budget |
|---|---|---|---|---|
| like-shows-state: like a clip and see it's liked | Member | Home: Like on the clip (1); the button turns on and likeCount moves by one | 1 | 1 |
| like-in-one-click: like the first clip from the feed | Member | Home: Like on the first clip | 1 | 1 |
| reply-to-comment: reply to a comment under a clip | Member | Home: Comments (1), Reply on a comment (2), type, Send (3) | 3 | 3 |
| follow-creator: follow a clip's creator and see it | Member | Home: Follow on the author avatar (1); the button shows Following. Or the avatar (1), Follow (2) | 1 (2) | 2 |
| moderate-report: hide a reported clip | Moderator | Reports: Hide on the first report (1), confirm (2) | 2 | 2 |
| Post a clip | Member | "+" (1), pick the clip (2), type the caption, Post (3) | 3 | 3 |
| Find my own clips and likes | Member | Me (1) shows Clips; Liked tab (2) | 2 | 2 |
| Open a notification | Member | Inbox (1), the notification (2) opens the clip with the comment highlighted | 2 | 2 |
| Report a comment | Member | Comments (1), Report on a comment (2), pick a reason, Send (3) | 3 | 3 |

## Data the pages need

- Clip: `videoUrl`, `cover`, `caption`, `createdAt`, `author` (handle, avatar), `likeCount`*, `likedByMe`*,
  `commentCount`*, `viewCount`*, `author.followedByMe`*, `hidden`*.
- Feed: `For you` ranked by the server (newest with some weight on likes), `Following` newest from followed members;
  paged by a cursor.
- Comment: `text`, `author`, `createdAt`, `parentId` (one reply level), `replyCount`*, `likeCount`*, `likedByMe`*,
  `isAuthorOfClip`*.
- Profile: `handle`, `name`, `avatar`, `bio`, `followerCount`*, `followingCount`*, `likeTotal`*, `followedByMe`*,
  `isMe`*.
- Notification: `kind` (like, reply, follow), `actor`, `target` (clip or comment), `createdAt`, `read`;
  `unreadCount`* for the badge.
- Report: `target`, `reason`, `reporter`, `createdAt`, `status`; `reportCount`* per target.

\* computed by the server. Counts and the "by me" flags come from the reactions, comments and follow features; the
client sends only the toggle.

## States

- Like: the button turns on at once and the count moves; on error it turns back with a short notice.
- Following feed empty: suggest members to follow with their `follow-button`, not a blank screen.
- Comments empty: "No comments yet" with the composer focused.
- Clip loading: show the cover until the video can play; never a blank screen.
- Upload: a progress bar; the clip appears on Me as "processing" until ready; failed uploads offer retry.
- Hidden clip: the author sees it marked hidden with the reason; other members never see it.
- Signed out: like, comment and follow ask to sign in, then complete the action.

## Never shown to

- Members: who reported them, other members' Liked tab when private, hidden content, the moderation menu,
  the ranking score.
- Visitors: the composer, the inbox, the Following tab.
- Moderators: members' private messages and passwords; reporters are shown to moderators, never to the author.

## Options

- Comments in a sheet over the clip (default on phone) or beside the clip (desktop).
- One reply level (default) or nested threads.
- Follow on the avatar overlay (default) or only on the profile.
- For you ranked (default) or newest only.
- Liked tab public or private (default private).

## Slots used

- `action-bar`
- `author-card`
- `card-grid`
- `card-list`
- `card-row`
- `comment-thread`
- `data-table`
- `filter-bar`
- `follow-button`
- `form`
- `media`
- `media-feed`
- `media-upload`
- `notification-list`
- `profile-header`
- `reaction-button`
- `record-header`
- `review-queue`
- `search-bar`
- `tab-strip`
- `workflow-bar`
