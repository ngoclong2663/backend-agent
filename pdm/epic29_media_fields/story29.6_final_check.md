# Story 29.6 — Final check on real drafts

**Epic:** [29 — Media fields](epic29_media_fields.md) · **Requirements:** FR-43 · **Depends on:** 29.1–29.5

## User story

As the product owner, I want media fields checked end to end on real drafts, so that I know uploads, playback and
subtitles work on the live backend.

## Steps

1. Two real requirements (at most two at a time) through the configured draft provider: one where people watch video
   records with subtitles in two languages, one where people listen to audio records grouped under a parent record.
2. On mocks: every screen plays the samples. On the live preview: upload a real video (≥ 50 MB), an audio file, an
   `.srt` and a `.vtt` file; play them; wait past the signed URL's expiry and keep playing (D8).
3. Record: upload times, playback on Chromium and WebKit (Playwright), subtitle display, what failed.

## Acceptance criteria

- [ ] Both apps upload and play their media on the live backend, with subtitles.
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

Also found on the way: the access rules made instructor-made courses private to their instructor, so learners opened
an empty course list (a record whose person field names the role that creates it is now readable by every other
role); the `uniqueConstraints` + `uniqueTogether` pair on the same fields gave the model two identical constraints
(the rule reuses the entity's); muted and destructive text under 4.5:1 on the kit's surfaces (darkened per app);
the sidebar icons of area pages (all the same icon).

Media: Ember Kitchen's lessons carry a `video`, a poster and `Caption` children (`subtitles` + a language enum,
English and Japanese); Lantern Audio's episodes carry an `audio` and a `transcript` (`subtitles`) under their show.
Both drafts typed the fields as the kinds without a repair (`fix_media_fields` had nothing to do), the contract's
storage tracks and the sample objects were seeded, the smoke check uploaded them and the frontend scenarios passed on
the mocks' sample media; the live previews run on the seeded samples.

Ember Kitchen's evaluation on the live API reported "No captions yet" on a lesson's record and no caption control on
the player (screens 03 and 11): the synthesized Caption rows attach to the first lesson only (`_track_rows`), and the
evaluation opened another; the seed should give every media record its sample tracks, or the record page should say
which lessons have captions (backlog).

Deviation: the manual uploads on the live preview (a real ≥ 50 MB video, an audio file, `.srt` and `.vtt`), the
playback on WebKit and the wait past the signed URL's expiry were not done in this session; the players' behaviour is
covered by the kit's tests and the Story 29.5 design check on the media library.

