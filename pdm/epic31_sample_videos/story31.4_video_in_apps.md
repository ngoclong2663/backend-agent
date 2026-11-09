# Story 31.4 — Seeded videos in apps

**Epic:** [31 — Sample videos](epic31_sample_videos.md) · **Requirements:** FR-45, FR-43 · **Depends on:** 31.1, 31.2, 29.3

## User story

As someone trying a generated app whose records are videos, I want its demo data to play real videos that fit each
record, so that the app looks like a working product on mocks and in the preview.

## Context

- Epic 27 seeds image fields with a photo per record's label (`images/stock.stock_seed_photos`) and the storage plugin
  keeps a seed's outside `http(s)` link as it is (`outside_url`).
- Epic 29's `VideoPlayer` plays files with `<video>` and our subtitle tracks; Epic 29's samples fill seeds today.

## Steps

1. **Seeds:** `stock_seed_videos` gives each seeded `video` field a video searched by the record's label: a Pixabay
   file first (it plays in our player), a YouTube link when there is no Pixabay key or no result (the epic's table);
   one search per distinct label within the limits, the rest reuse results; with nothing found the field keeps Epic
   29's sample. The record's image field (the poster) gets the video's poster when it is empty and no stock photo was
   set.
2. **Kit:** `VideoPlayer` plays a Pixabay link natively, with the record's subtitle tracks when it has any; it
   recognises a YouTube link (`youtube.com/watch?v=`, `youtu.be/`) and renders the same facade as sites (31.3). The
   credit shows under the player (as `PhotoCredit` does).
3. **Contract and backend:** a seeded outside link is returned as the field's URL like a seeded photo; uploads still
   take object keys only (the storage plugin's rule stands).
4. **Views:** the watch page and shelves (Epic 30's 30.5) treat both kinds like uploaded videos (poster, duration when
   known).
5. Tests: seed resolution with both recorded responders (order, fallback, nothing found); the kit's link detection;
   the API returns the link unchanged.

## Acceptance criteria

- [ ] An app draft with video records and the providers on plays real videos on mocks and in the preview.
- [x] Videos uploaded by users still play in the native player with their subtitles.
- [ ] Without the providers the app seeds Epic 29's samples as before.

## Verify

`make test`, the kit's vitest, `make up` with one app draft.

## Status

Proposed 2026-11-08.

**Done 2026-11-09 (unit part).** `videos/stock.stock_seed_videos`: each seeded `video` field gets a video found from
the record's label (one search per distinct label), a Pixabay file first, else a YouTube watch link; the record's empty
image field gets YouTube's thumbnail (hotlinking allowed); a Pixabay poster is never hotlinked, so in apps the player
shows the first frame (deviation: Pixabay posters ship only with sites, as public files); nothing found keeps Epic 29's
sample with a note. The drafting app flow runs it after the seed photos; `app.json` gains `videoCredits` (by URL).
Kit: `VideoPlayer` recognises a YouTube link (`youtubeId`) and renders the facade (poster, play, the iframe on click,
the credit); a Pixabay or an uploaded file plays natively with the record's subtitle tracks, the credit under the
player when the app has one. The storage plugin's rule stands: uploads take keys; a seeded outside link is returned as
the field's URL (`signed_url`). Tests: `test_sample_videos.py` (Pixabay first, then YouTube, posters, credits in
`app.json`; the samples kept without a provider). Epic 30's watch page and shelves are not built yet (30.5).
