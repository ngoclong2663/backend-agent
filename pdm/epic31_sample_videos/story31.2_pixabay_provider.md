# Story 31.2 — The Pixabay video provider

**Epic:** [31 — Sample videos](epic31_sample_videos.md) · **Requirements:** FR-45 · **Depends on:** 27.1

## User story

As the drafting code, I want to turn a short phrase and a place into a stock video file that fits the place, light
enough to load, with its credit and within the API's limits, so that sites can have moving heroes and apps can seed
videos our own player plays.

## Context

- Epic 27's shape: `images/port.py`, `images/unsplash.py` (search, cache, limits), `images/factory.get_stock_photos()`.
- 31.1 adds `videos/port.py` and the YouTube adapter; this story adds the second adapter behind the same port.
- Pixabay API (docs read 2026-11-08, https://pixabay.com/api/docs/): `GET https://pixabay.com/api/videos/` with `key`,
  `q`, `lang`, `video_type` (`film` / `animation` / `all`), `min_width`, `min_height`, `safesearch`, `order`,
  `per_page`. A hit has `id`, `pageURL`, `tags`, `duration` (s), `user`, `user_id`, and `videos.large / medium / small /
  tiny`, each with `url`, `width`, `height`, `size` (bytes) and `thumbnail`. Content under the Pixabay Content License.
- **What the docs require** (quoted 2026-11-08):
  - "Videos may be embedded directly in your applications. Yet, we recommend storing them on your server." (Images may
    not be hotlinked; this story only uses videos and their thumbnails as posters, see step 3.)
  - "By default, you can make up to 100 requests per 60 seconds. Requests are associated with the API key"; the
    `X-RateLimit-Limit / Remaining / Reset` headers give the status.
  - "requests must be cached for 24 hours"; "the API is made for real human requests; do not send lots of automated
    queries. Systematic mass downloads are not allowed."
  - "show your users where the images and videos are from, whenever search results are displayed."
- **Found on 2026-11-08:** Pixabay sits behind Cloudflare, which answers `429` with a bot challenge
  (`cf-mitigated: challenge`) to curl's default client name; with a descriptive `User-Agent`
  (`fullstack-generation-agent/1.0`) the same request is answered (200). Clips found for "ocean waves" were about 40 s
  long; their `tiny` file was 2.5–5.4 MB at 640×360, but a 4K source's `tiny` is 1280×720 and 16.8 MB, so the file
  must be chosen by size, not by name.

## Steps

1. **Adapter** `videos/pixabay.py` (httpx, `User-Agent: <APP_NAME>/<version>` from settings): search by phrase with
   `video_type=film`, `safesearch=true`, the app's language as `lang`, `min_width` from the place; keep hits whose
   orientation matches the place (from the files' width and height: landscape for heroes and players, portrait for
   phone-first places) and whose duration fits it (short clips for backgrounds and cards); choose the smallest file at
   least as wide as the place, under a byte budget per place (about 6 MB for a hero background, 12 MB for a player),
   else the next hit; return the file URL, its size, width, height, duration, the poster (the file's `thumbnail`), and
   the credit (`Video by <user> on Pixabay`, links to the video's page and to Pixabay).
2. **Limits and cache:** read `X-RateLimit-Remaining` and stop under a margin; cache every search for at least 24 h
   (the docs' rule) by phrase + language + place under `ARTIFACT_ROOT/asset-cache/video/pixabay/`; a draft makes only the
   searches its places need (never a background crawl); errors, `429` and a Cloudflare challenge end the search with no
   result and a note, never the draft.
3. **Files and posters:** video files are linked directly (allowed for videos). Poster thumbnails are images, which the
   docs do not allow hotlinking: the poster is downloaded once into the asset cache and shipped with the site (or
   uploaded with the app's seed). Storing the video files too (Pixabay's recommendation) is an option behind a setting
   (`PIXABAY_STORE_VIDEOS`), off by default, measured in 31.5 (bundle size versus reliability).
4. **Settings:** `pixabay` in `VIDEO_PROVIDERS`, `PIXABAY_API_KEY` in `.env.example`; the settings page shows it; a
   key check script like Epic 27's (one request, with the descriptive `User-Agent`).
5. **Tests:** the adapter against a recorded responder injected from `tests/` (no network): file choice by width and
   size budget (including a 4K source whose `tiny` is too large), orientation and duration filters, limits from the
   headers, a `429` challenge page, cache hits within 24 h. The responder is listed in
   `docs/development/test-doubles.md`.

## Acceptance criteria

- [ ] A phrase and a place return an MP4 file that fits the place and its byte budget, with a poster stored by us and
      its credit, from the cache on the second call.
- [x] Every request sends the descriptive `User-Agent`; every search is cached for at least 24 h.
- [x] With no key, no requests left, a challenge or an error, the provider returns nothing and the draft goes on.

## Verify

`make lint`, `make test`, the key check script with the user's key (one request).

## Status

Proposed 2026-11-08. Replaces the Pexels provider (Pexels stopped issuing API keys for now, the user, 2026-11-08);
Pexels can return later behind the same port.

**Key checked (2026-11-08):** `PIXABAY_API_KEY` in `.env` works: one search ("ocean waves", `safesearch=true`, 3
results) answered 200 with 500 total hits and four sizes per hit; `X-RateLimit-Limit: 100`, `Remaining: 98`,
`Reset: 60`. The first two requests (curl's default client name) got Cloudflare's challenge (`429`), see Context.

**Done 2026-11-09.** `videos/pixabay.py`: `api/videos/` with `video_type=film`, `safesearch=true`, the language and the
place's `min_width`; hits kept by orientation (landscape for every place today) and duration (≤ 45 s for a background,
≤ 240 s for a card); the file chosen by its numbers (`choose_file`: the smallest at least as wide as the place, under
its byte budget: 6 MB background, 12 MB player; a 4K source's 16.8 MB `tiny` loses to its 11 MB `small`); the credit
"Video by <user> on Pixabay" with the video's page and the user's page. `User-Agent: <app>/<version>` on every
request; `X-RateLimit-Remaining` read, a search refused under 10 left; a 429 with `cf-mitigated` is reported as the
challenge; 24 h cache under `asset-cache/video/pixabay/`; posters downloaded once into the cache (`poster_bytes`) and
shipped as a public file of the site (31.3). `PIXABAY_STORE_VIDEOS` is a setting (off), not yet acted on (31.5
measures it). Tests: the responder with four sizes, the orientation and duration filters, the file choice per place,
the limits, the challenge, errors, an empty answer, the cache, the poster download.
