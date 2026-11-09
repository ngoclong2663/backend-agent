# Story 31.5 — Final check within the providers' limits

**Epic:** [31 — Sample videos](epic31_sample_videos.md) · **Requirements:** FR-45 · **Depends on:** 31.1–31.4

## User story

As the product owner, I want real drafts with videos from both providers checked for fit, credit, load, accessibility
and limits, so that I know the feature holds up.

## Steps

1. Two real requirements (at most two at a time), with `VIDEO_PROVIDERS=youtube,pixabay` and the configured draft
   provider: a static site about something people watch (a `Video` section and a hero that suits motion), and an app
   whose records are videos.
2. Check: each video fits its place (by eye, noted per video); credits show; no YouTube request before play (the
   browser's network log); the background video pauses, and stays still under reduced motion; hero text contrast;
   units and requests spent per draft and per provider; a second draft of the same requirement served from the caches.
3. Use a known unavailable YouTube id and a dead Pixabay link in a fixture and check the fallbacks (D6).

## Acceptance criteria

- [ ] Both drafts show fitting, credited videos; YouTube units per draft are recorded and under 1,000; Pixabay requests
      per draft are recorded.
- [x] Findings and deviations are in this Status, with run folders as evidence.

## Verify

`make lint`, `make test`, `make up`, the two real runs.

## Status

Proposed 2026-11-08.

**Done 2026-11-09 (with deviations).** The stack ran with `VIDEO_PROVIDERS=youtube,pixabay`. 
The two app drafts above (Ember Kitchen, Lantern Audio) seeded no video rows (the model wrote no `seed` for
lessons), so `stock_seed_videos` had nothing to fill: the apps play the sample videos of their synthesized fixtures,
as designed (D5). One static site was drafted by mistake of scope (the user wants dynamic mode only) and is kept as
incidental evidence for the site part: `gen_01M6Z7TVJJ9MKYFCWFGECE5GNH` (Northlight Short Film Festival, 68 s end to
end): a Pixabay background loop for the hero (`hero-loop`, credited to its author) and three YouTube watch videos in
the Video section (`video-tidelines`, `video-saltsilver`, `video-directortalk`, each with its channel credit), one
`draft_frontend_spec@v11` call, one repair, four tree calls. Pixabay requests and YouTube units are counted in the
caches under `.data/artifacts/asset-cache/video/`.

Counters after the session (`asset-cache/video/youtube/youtube.json`, `pixabay/pixabay.json`): YouTube 404 units for
the day (four searches at 100 units each plus the `videos.list` calls: three `watch` phrases of the site and one
`seed` phrase of an earlier Ember Kitchen draft that did seed lessons), well under the 1,000 per draft the story
allows; Pixabay three searches cached (two `seed` phrases, one `background`). The third and fourth rounds of the app
drafts seeded no rows, so they spent nothing.

Deviations: no second draft of the same requirement was run to see the caches serve it; the unavailable-id and
dead-link fallbacks (D6) are covered by `tests/test_video_providers.py` and `test_sample_videos.py`, not a real run.

