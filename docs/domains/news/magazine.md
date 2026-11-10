# News: magazine (front page by section)

A newsroom publishes articles in sections. Readers land on a front page with a lead story and rows per section,
read at a comfortable width, save articles and follow sections. Writers draft, editors review, publish or schedule.
Readers only ever see published articles.

## Studied

- The Guardian: front page by section, live and long reads, comments under articles.
- The New York Times: lead package, section fronts, saved articles, a For you tab.
- BBC News: section fronts, short articles, related stories.
- The Atlantic: magazine sections, long reads, saved list.
- The Economist: weekly edition by section plus a daily front.
- Le Monde: front by section, follow topics, comments for subscribers.
- Medium: articles by topic with follow and reading lists.

## People and areas

| Role | Area | First device |
|---|---|---|
| Reader | Readers (front page, sections, article, saved) | Mobile-first, works on desktop |
| Writer | Newsroom (my drafts) | Desktop |
| Editor | Newsroom (review queue, publish, schedule) | Desktop |
| Visitor (signed out) | Readers, read only | Mobile-first |

## Pages

### Readers

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Front page | Menu tab "Home" | `hero`: the lead story (media, headline, standfirst, section, time, `reaction-button` save) · `card-row` per section, in a set order: newest articles (media, headline, section, time, reading time, `reaction-button` save with savedByMe), "More in Section" link | Open an article, save, open a section |
| For you | Menu tab "For you" | `card-list`: newest articles from followed sections and authors · followed sections as chips (`filter-bar`) | Open, save, manage follows |
| Section | Menu "Sections" list, a section name on a card | `record-header`: section name, `follow-button` (followedByMe) · `hero`: the section's lead · `card-list`: newest articles (media, headline, standfirst, author, time, save) | Follow, open, save |
| Article | Any card | `article-reader`: section, headline, standfirst, author and time, reading time, hero `media` with caption, the body at reading width · `action-bar`: `reaction-button` save, share, comment count (jumps to comments) · `author-card`: author name, bio, `follow-button` · `card-row` "Related": same-section articles · `comment-thread`: at the end (newest or top, replies under each, the composer) | Save, share, follow the author, comment, reply, report a comment |
| Saved | Menu tab "Saved" | `card-list`: saved articles (headline, section, saved time, reading time), newest saved first | Open, remove |
| Search | Search button in the header | `search-bar` · `filter-bar`: section, date · `card-list`: results | Open |
| Account | Menu "Account" | `form`: name, email, newsletter choice · `card-list`: followed sections with `follow-button` | Edit, unfollow |

### Newsroom

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| My articles (writer home) | Menu "My articles" | `tab-strip`: Drafts, In review, Changes asked, Published · `data-table`: articles (headline, section, `status-pill`, updated, editor note flag) | New article, open |
| Editor | "New article" or a row | `workflow-bar`: `status-pill` (draft, in review, changes asked, scheduled, published), the allowed next steps by role · `rich-editor`: headline, standfirst, section, hero image (`media-upload`), body · `comment-thread`: editor notes on the draft (newsroom only) | Save, submit for review; editor: request changes, publish, schedule |
| Review queue (editor home) | Menu "Review" | `filter-bar`: section, writer · `review-queue`: articles in review (headline, section, writer, submitted time) with Publish and Request changes on each row | Open, publish, request changes |
| Schedule | Menu "Schedule" | `data-table`: scheduled articles (headline, section, publish time) | Change time, unschedule |
| Published | Menu "Published" | `filter-bar`: section, date · `data-table`: published articles (headline, section, published time, saves, comments) | Unpublish, open, moderate comments |

## Main tasks

| Task | Role | Path (click by click) | Clicks | Budget |
|---|---|---|---|---|
| bookmark-article: bookmark an article and see it's saved | Reader | Front page: Save on a card (1); the button shows saved | 1 | 1 |
| follow-section: follow a section | Reader | Sections menu (1), the section (2), Follow (3). From a card's section name: the name (1), Follow (2) | 2 | 2 |
| publish-reviewed: publish an article in review | Editor | Review queue: open the article (1), Publish (2) | 2 | 2 |
| reply-to-comment: reply to a comment under an article | Reader | Front page: an article (1), Reply on a comment (2), type, Post (3) | 3 | 3 |
| Read a saved article later | Reader | Saved (1), the article (2) | 2 | 2 |
| Submit a draft for review | Writer | My articles: New article (1), write, Submit for review (2) | 2 | 2 |
| Schedule an article | Editor | Review queue: the article (1), Schedule (2), pick the time, Confirm (3) | 3 | 3 |
| Ask for changes | Editor | Review queue: the article (1), Request changes (2), type the note, Send (3) | 3 | 3 |

## Data the pages need

- Card: `headline`, `standfirst`, `heroImage`, `section`, `publishedAt`, `readingTime`*, `author.name`,
  `savedByMe`*.
- Front page: `lead`* (the editor's pick or the newest with the lead flag), `rows`* per section (newest N
  published), in the section order.
- Article: the card's fields plus `body`, `heroCaption`, `author` (name, bio, `followedByMe`*), `commentCount`*,
  `related`* (same section, newest, excluding this one).
- Section: `name`, `followedByMe`*, `followerCount`*.
- For you: newest published articles from `followedSections`* and followed authors.
- Comment: `text`, `author`, `createdAt`, `parentId`, `replyCount`*.
- Newsroom: `status`, `submittedAt`, `scheduledFor`, `publishedAt`, `editorNote`, `writer`, `editor`,
  `allowedTransitions`* by role.

\* computed by the server. `readingTime` comes from the body length. Only `status = published` with
`publishedAt` in the past reaches a reader query.

## States

- Front page with a section that has no articles: the row is left out, not shown empty.
- For you with no follows: show the sections with their `follow-button`.
- Saved empty: say how to save, with a link to the front page.
- Article loading: headline and standfirst first, the body after; the hero image keeps its space.
- Comments closed on an article: show "Comments are closed" and keep the existing ones.
- Editor: unsaved changes are kept as a draft automatically; leaving warns once.
- Publish error: the article stays in review with the error on the workflow bar.

## Never shown to

- Readers: drafts, in-review, changes-asked and scheduled articles, editor notes, the newsroom menu, who else
  saved an article.
- Writers: other writers' drafts (unless shared), the publish and schedule actions.
- Editors: readers' email addresses.

## Options

- Front page rows per section (default) or one ranked column.
- Comments at the end of the article (default), in a sheet, or off per article.
- Save on every card (default) or only on the article.
- Follow sections only (default) or authors too.
- Scheduled publishing on (default) or publish now only.

## Slots used

- `action-bar`
- `article-reader`
- `author-card`
- `card-list`
- `card-row`
- `comment-thread`
- `data-table`
- `filter-bar`
- `follow-button`
- `form`
- `hero`
- `media`
- `media-upload`
- `reaction-button`
- `record-header`
- `review-queue`
- `rich-editor`
- `search-bar`
- `status-pill`
- `tab-strip`
- `workflow-bar`
