# Story 28.7 — Final check on real drafts

**Epic:** [28 — A tour you do](epic28_interactive_tour.md) · **Requirements:** FR-42 · **Depends on:** 28.1–28.6

## User story

As the product owner, I want the interactive tour checked on real drafts of different workflow shapes, so that I
know it works beyond the synthetic cases.

## Steps

1. Draft and generate two real requirements (at most two at a time) with business workflows on, through the
   configured draft provider: one with a single role whose workflow creates and then changes a record, one with two
   or more roles that hand a record to each other (an approval or an assignment).
2. Play each role's tour by hand on mocks and on the live API (with the live notice), then read the walker's Tour
   block in the Business tab.
3. Record per workflow: steps completed by doing, steps skipped and why, stuck steps, time to finish; and what a
   first-time user would still not understand.

## Acceptance criteria

- [ ] Every `do` step completes by doing on mocks in both apps, or its skip reason is a known limit noted here.
- [ ] The walker's results match the hand run.
- [x] Findings and deviations are in this Status, with run folders as evidence.

## Verify

`make lint`, `make test`, `make up`, the two real runs.

## Status

Proposed 2026-11-08.

**Done 2026-11-09 (with deviations).** **Runs (2026-11-09, the UI's one-click flow as `admin@bga.local`, stack `make up VIDEO_PROVIDERS=youtube,pixabay`,
drafts on `antigravity_json` (gemini-3.8-flash-low, fast), generation on the `antigravity` engine, the account login):**

| Requirement | Generation | Result | Total | Draft |
|---|---|---|---|---|
| Ember Kitchen, a cooking video school (`.data/final/studio-lessons.md`: video lessons with captions in two languages, instructors and learners, questions handed from learner to instructor, a dark cinema look) | `gen_01M6Z75NJYKSXNF4JGQPZ4XYF8` | COMPLETED_WITH_WARNINGS, all three lanes, live API switched | 10 min 14 s (03:55:59 → 04:06:13) | 4 calls, 70 s, $0 |
| Lantern Audio, a podcast network (`.data/final/podcast-network.md`: audio episodes with transcripts under shows, a producer drafts then publishes, a warm paper look) | `gen_01M6Z81Z2TM5SFN3ZMD05TPW56` | COMPLETED_WITH_WARNINGS, all three lanes, live API switched | 5 min 53 s (04:11:26 → 04:17:19) | 5 calls, 60 s, $0 |
| TikTok Clone, the user's own requirement (`.data/final/tiktok-lite.md`: "a website with basic features look like tiktok"; videos, comments, likes as interactions, viewers and creators) | `gen_01M6ZAFZH8VYM36J6DWVQEYE36` | COMPLETED, all three lanes, no warnings, live API switched (rerun of finding 4 below) | 10 min 01 s (04:53:37 → 05:03:38) | 5 calls, 73 s, $0 |
| TikTok, the same requirement again after findings 5 and 6 (videos published on creation, likes, comments, a viewer's visibility policy) | `gen_01M6ZFMEQSMCSEN4GXT0RAJEZ6` | COMPLETED, all three lanes, no warnings, live API switched; checked live: the creator adds a video, the viewer lists, opens and views it | 5 min 24 s (06:23:52 → 06:29:16) | 5 calls, 70 s, $0 |
| TikTok, the same requirement on `draft_app@v8` (findings 7 and 8: a video's status is its own, UPLOADED → PUBLISHED / REJECTED; watching is an action and a `VideoView` entity; likes once per person) | `gen_01M6ZGXFSDP3CPGVCP9C6BNV5X` | COMPLETED, all three lanes, no warnings, live API switched; checked live with a real upload: a new video is 404 to the viewer until published, then opened, watched and still in the feed; a second like is 409 | 7 min 04 s (06:46:17 → 06:53:21) | 4 calls, 57 s, $0 |
| TikTok again after finding 9 (person fields `viewerId` as v8 asks; likes through `interaction.like`) | `gen_01M6ZJ7D91VHY0Z6RE83FMX7DZ` | COMPLETED, all three lanes, live API switched; checked live as the demo viewer: no user picker in any form, no user directory (`/users` 404), a comment with its text alone, a like with the video alone (owner set by the server), a second like 409 | 5 min 04 s (07:09:10 → 07:14:14) | n/a |

The only warning left on both is the migration check (a duplicated unique constraint, fixed afterwards, below). Three
earlier rounds of the same two requirements failed and each failure became a fix with a regression test on the real
drafted spec (`tests/fixtures/specs/ember-kitchen*.json`, `lantern-audio*.json`):

1. `gen_01M6Z63NYZ0EFVPZG0YJK659R8` / `gen_01M6Z63RXKVZN823Y6RY74CNYV` (cancelled): `frontend:scenarios` failed.
   The visibility rule's scenario pass (Story 23.9) rewrote the auth plugin's "no token" call into an authenticated
   one (the mock answered 200 for an expected 401), and a public read's success scenario pointed at a draft record a
   signed-out caller cannot see (404 for 200). `policies._visibility_contract` now skips unauthenticated scenarios and
   points a public read at a visible record.
2. `gen_01M6Z6HPQQ0WMJ3ZSZGABM70NR` (crashed) / `gen_01M6Z6HKT859PCNTAGVK2WEY4Z` (backend failed): the draft had an
   `EpisodeGuest` entity *and* a many-to-many Episode–Guest, so the relations plugin planned a link table without an
   entity; the completion's context pack escaped its None name. And the synthesized Progress fixtures cycled two
   lessons and two demo learners over three rows, which the `uniqueTogether` index refused at seed time.
   `completion.related_entities` skips entity-less models; `build_fixtures` keeps `uniqueTogether` pairs unique.
3. `gen_01M6Z75RG2H8YD1JT4XNZ5AMPP` (backend startup failed): the same link table's routes landed in the join entity's
   module (`episode_guests_router` missing). The planner now drops a many-to-many whose join entity exists.

4. `gen_01M6Z9E38WE8XQHJ50MKTBEM78` (the user's own run, "a website with basic features look like tiktok", backend
   startup failed in generator-owned files): `VideoInteraction` had a `uniqueTogether` rule (one like per viewer) but
   only a list operation, so its repository got the `CONSTRAINT_ERRORS` table, which names `ErrorCode`, without the
   import that only a writing repository adds (`NameError` at import; the engine may not repair owned files). The
   table is written only with the writes that consult it (`tests/fixtures/specs/tiktok-lite.json`). Found with it:
   the free-pair trim of the `uniqueTogether` fixtures counted a free text field as one slot and cut the booking
   fixtures to two, which lost the overlap and duplicate scenarios; it now counts foreign keys only. Rerun as
   `gen_01M6ZAFZH8VYM36J6DWVQEYE36` (the table's third row: clean).

5. `gen_01M6ZAFZH8VYM36J6DWVQEYE36` (completed, but a viewer saw no video after a creator published one, found by
   the user in the UI): the draft wrote the creator's ownership policy for the creator's actions and a visibility
   policy "viewers see only published videos" (Story 23.9), and the access rules still put the owner's policy on
   `video.get` / `video.list`, so a viewer's feed listed only their own videos: none. An entity with a visibility
   policy now keeps its reads as drafted (the policy says who sees what; `tests/fixtures/specs/tiktok-clone.json`).
   The rerun `gen_01M6ZF872FJ83Q6CYZ6TTNT5PF` drafted differently and ended NEEDS_REVIEW (finding 6).
6. `gen_01M6ZF872FJ83Q6CYZ6TTNT5PF` (the draft's FrontendSpec invalid, `FE_UNKNOWN_PAGE`): the draft added a
   `FeedSession` a viewer starts with nothing to fill in (the owner from the signed-in user, the status and date
   defaulted); the screen planner linked "New feed" on its list to a create page it never planned (a form with no
   field is no form). Such a create is now a button in the list page's actions (the kit's collection action), and a
   create link to a page that does not exist is dropped in any case (`tests/fixtures/drafts/tiktok-feed-sessions/`).
   Rerun as the table's fourth row.

7. `gen_01M6ZFMEQSMCSEN4GXT0RAJEZ6` (the user's video, created from the creator's studio, missing from the viewer's
   list even with `status=published`): the draft modelled viewing as a *status* of the video (`published` → `viewed`,
   moved by `video.view`) next to the visibility policy "viewers see only published videos", so a video any viewer
   opened left every viewer's feed (two of the three seeded videos were already `viewed` by the checks; the same
   draft family had `VIEWED` / `LIKED` statuses in finding 4's run). `draft_app@v8` adds one rule: a status is the
   record's state; what a person does with a record (viewed, liked, saved) is an interaction entity or a counter,
   never a status value or a transition. Rerun as the table's fifth row.
8. The same run, from the user's hands-on review: a like was a tab on the video with a link to a form page of one
   button, far from the video being watched. A child create with nothing visible to fill in (the parent from the
   route, the owner from the signed-in user) is now an action on the parent's record, on its cards and rows and on
   its page (`screens.quick_create`; the kit gates such an action by the operation's access and resolves the record
   into its body); the news-feed golden app's bookmark takes the same shape (`tests/fixtures/drafts/tiktok-likes/`).
   What the model never says is *where an interaction belongs* (a like while watching, a view when the record
   opens): a placement input in the outline is proposed in the Epic 30 plugin backlog, not made.
9. The fifth row's run, from the user's review: signed in as a viewer, the comment and like forms ask to *choose a
   user*, and the viewer can browse the user list. The draft named the liker / commenter `creatorId` (the field of
   the role that made the row was named after the other role), so the access rules read "a viewer creates a record
   for a creator" and added the staff directory (`user.list` for viewers) and a picker. `draft_app@v8` now also
   says a person field is named after that person's role. Code: "staff create it for a person" (25.4) now needs the
   creating roles to manage those records too (a role policy on another of its operations, or an ownership bypass:
   staff update and assign a member's case); a role that only creates a record makes it for itself and owns it,
   whatever its person field is called (`_maker_owns`). No picker, no viewers' user directory; a like with nothing
   left to fill in becomes the one-click button of finding 8. Rerun as the table's sixth row (a run before it, `gen_01M6ZJ0ABG3C8XF93BRTV495HN`, failed with no generated code: the sandbox images had been removed from Docker outside the session; `make runner runner-node` rebuilt them).

Also found on the way: the access rules made instructor-made courses private to their instructor, so learners opened
an empty course list (a record whose person field names the role that creates it is now readable by every other
role); the `uniqueConstraints` + `uniqueTogether` pair on the same fields gave the model two identical constraints
(the rule reuses the entity's); muted and destructive text under 4.5:1 on the kit's surfaces (darkened per app);
the sidebar icons of area pages (all the same icon).

Workflows: Ember Kitchen has two roles handing a record over (a learner asks a question, the instructor answers and
marks it; an instructor publishes a lesson); Lantern Audio has one role creating then changing a record (a producer
drafts an episode, then publishes it). The evaluation (the walker playing each role's tour on the mocks, `report.tour`)
ran after each generation. The hand run of the tours on the live API was not done in this session (the user watches
the runs in the UI); the walker's Tour block is the evidence.

**Ember Kitchen's evaluation** (DONE in 13 min, `second_look@v1` on gemini-3.8-flash-medium, $0; score 18 of 75
expectations met, 48 blocked): the walker signed in as each role on the mocks and played the tours, but got little
further than the first step. Learner: "Browse published courses and lessons" completed (34 ms), "play video" and
"mark watched" not reached; instructor: "create course" **stuck: no control to click** after 26 s, the rest not
reached. The checker on the live API found: `POST /courses` refuses a create without a `coverImage` upload (the
required image field: the kit uploads first, the checker does not); `POST /progress` answered 409 on the first
"mark watched" because the synthesized seed filled every learner × lesson pair (fixed: `build_fixtures` leaves one
pair free); the engine-written `question.answer` accepts an empty answer and moves the status; "No captions yet" on a
lesson's record and no caption control on the player; a learner reading another learner's question got 200 where the
checker expected 404 (to verify by hand: the ownership policy is on the operation).

**Lantern Audio's evaluation** (DONE in 4 min 47 s, $0; 0 of 32 expectations met, 29 blocked): the producer's tour
"listen to an episode" completed its first `note` step (browse shows) and reached nothing further; the publishing
tour's first `do` step (create a show) was not reached; the listener's tour stopped at once: "no app role for
listener" (the requirement's public listener is not a role, so the walker has nobody to sign in as: a signed-out tour
is the gap). The checker's gaps: `POST /shows` refused without the cover-art upload (the same checker limit as above);
taking an episode down left "Published" on the dashboard's status (the engine-written transition); transcripts shown as
raw file links next to the player (the `subtitles` field's value in the field grid; the player itself attaches the
track).

Findings for the tour itself (not fixed here, the plugin and tour backlog): (1) the first `do` step of the instructor's
tour did not find its control on the mocks: the step's page is the learners area's course list, where the instructor
has no "New" button (the areas of Story 23.10 and the tour's page binding need to agree on the area the role works
in); (2) a `look` step that needs a record (play a lesson) is "not reached" when the role sees no record on the mocks
(the fixtures' lessons are drafts, hidden from learners by the visibility rule); the tour should pick a visible record
or say why none is there; (3) a tour for signed-out visitors (the requirement's public listeners) needs a walker
pass without a login; (4) the checker's API caller should upload a sample file for a required image or media field
before a create, as the kit does, so a create with a required cover is not counted as a gap.

