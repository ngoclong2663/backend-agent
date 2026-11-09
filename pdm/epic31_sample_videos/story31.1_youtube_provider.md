# Story 31.1 — The YouTube video provider

**Epic:** [31 — Sample videos](epic31_sample_videos.md) · **Requirements:** FR-45 · **Depends on:** 27.1

## User story

As the drafting code, I want to turn a short phrase into an embeddable, safe, credited YouTube video within the daily
quota, so that sites and apps can show real videos without the model naming any.

## Context

- Epic 27's shape: `images/port.py`, `images/unsplash.py` (search, cache under `ARTIFACT_ROOT/asset-cache/stock/`,
  limits), `images/factory.get_stock_photos()`, `IMAGE_PROVIDER`.
- YouTube Data API v3: `search.list` (100 units), `videos.list` (1 unit), default quota 10,000 units a day per project.

## Steps

1. **Terms first (D7):** read the YouTube API Services Terms of Service and Developer Policies; record here what they
   require for storing ids and metadata, refreshing them, embedding, branding and links, and adjust D3, D5 and D6 to
   them before writing code.
2. **Port** `videos/port.py`: `search(phrase, *, language, duration, count) -> list[VideoHit]` (`id`, `title`,
   `channel`, `channelUrl`, `thumbnail`, `duration`), `available(ids) -> dict[id, bool]`.
3. **Adapter** `videos/youtube.py` (httpx): the filters of D2; `videos.list` for duration and `status.embeddable`;
   the key from settings only; errors and quota exhaustion (`403 quotaExceeded`) end the search with no result, never
   the draft.
4. **Cache and quota:** results cached by phrase + language + duration under `ARTIFACT_ROOT/asset-cache/video/`; a
   local daily counter of units spent (reset at midnight Pacific time, as the quota is) that refuses a search when the
   remaining units are under a margin.
5. **Settings:** `VIDEO_PROVIDERS` (a list of `youtube`, `pixabay`; empty by default), `YOUTUBE_API_KEY`; listed in
   `.env.example`; the settings page shows which providers are on. A quick key check script like Epic 27's
   (`videos.list`, 1 unit).
6. **Tests:** the adapter against a recorded responder injected from `tests/` (no network, per the test-code rule);
   cache hits; quota refusal; an unembeddable result filtered out. The responder is listed in
   `docs/development/test-doubles.md`.

## Acceptance criteria

- [ ] The terms' requirements are recorded in this Status and reflected in the epic's decisions.
- [x] A phrase returns embeddable, safe-search videos with their credit, from the cache on the second call.
- [x] With no key, no quota or an error, the provider returns nothing and the draft goes on.

## Verify

`make lint`, `make test`, the key check script with the user's key (a few units).

## Status

Proposed 2026-11-08. Key checked the same day (see the epic's Status): `videos.list` and one `search.list` with
D2's filters both answered; 101 units spent.

**Done 2026-11-09.** Terms (D7, read 2026-11-09, applied in `videos/youtube.py`'s docstring and code): videos play
only in YouTube's embedded player (`youtube-nocookie.com/embed/<id>`, 31.3), never downloaded or re-hosted; each shows
its title and channel with a link back to YouTube (`credit`), no YouTube branding of our own; API data stays fresh
(ids and metadata cached a day, availability checked again when a site is previewed, nothing stored in the project but
the id, title and channel); safe search strict, embeddable results only, the app's language. The port
(`videos/port.py`: `VideoHit`, `VideoCredit`, `VideoUnavailable`, the places `watch` / `background` / `seed` and their
duration limits). The adapter: `search.list` (100 units) with D2's filters and `videoDuration` from the place, then
`videos.list` (1 unit) for the duration and `status.embeddable`; cached by phrase, language and place under
`ARTIFACT_ROOT/asset-cache/video/youtube/`; a daily unit counter (midnight Pacific) that refuses a search under a 600-unit
margin; 403 `quotaExceeded`, other errors and the network end the search with a reason, never the draft. Settings:
`VIDEO_PROVIDERS`, `YOUTUBE_API_KEY` (`.env.example`, compose, the Makefile's dev env); the engines API carries `media`
(the photo provider and the video providers on) and the Options card shows it. `make video-keys` is the key check
(`scripts/check_video_keys.py`, one `videos.list`). Tests: `tests/test_video_providers.py` on a recorded responder
(the filters, the unembeddable result filtered out, the cache, the day's units, the margin, the quota, errors,
availability).
