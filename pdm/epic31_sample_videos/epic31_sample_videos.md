# Epic 31 — Sample videos: YouTube embeds and stock video files

## Overview

Proposed 2026-11-08 for the user's review. Epic 27 fills sites and apps with real photos from Unsplash. Requirements
about video (a channel, lessons, a portfolio of films, product demos, events with recordings) still get no real
video: static sites have a `video` asset kind that only accepts uploads, page trees refuse `<video>` and `<iframe>`,
and Epic 29's media fields play our own short test samples.

This epic adds sample videos from **two providers**, the same way Epic 27 adds photos: the model writes **what** a
video should show (a short search phrase) and **where** it goes; the agent's code searches at draft time and keeps
what it found with its credit. Nothing is downloaded, and no API key reaches the generated project.

- **YouTube** (Data API v3): videos people **watch** (a talk, a lesson, a demo, a trailer-like clip), embedded with
  YouTube's own player through `youtube-nocookie.com`.
- **Pixabay** (videos API): stock video **files** (MP4) under the Pixabay Content License, played by our own `<video>`: hero
  background loops, ambient clips, and seeded video fields that play in Epic 29's player with our subtitles.

| Finding (code, 2026-11-08) | Effect |
|---|---|
| `AssetKind` has `video` (`frontend_spec/schema_v1.py`), but the validator says videos are uploaded; no section draws one | A static site cannot show a video unless the user uploads one |
| Page trees refuse `video`, `iframe`, `embed` (`frontend_spec/trees.py`) | Designed pages cannot embed a video, rightly for any source |
| Hero layouts (Epic 20) take an image or a drawing, never a video | No site can have a moving hero |
| Epic 29's media fields hold object keys; seeds keep an outside `http(s)` link as it is (Story 10.5) | A seeded link to a video file plays in `<video>` as is; a YouTube link needs an embed |
| `images/` has a provider port, a cache and Unsplash's search (`images/unsplash.py`, `images/stock.py`) | The same shape fits video searches |

**Which provider for which place:**

| Place | Provider | Why |
|---|---|---|
| Hero background, ambient loop (muted, decorative) | Pixabay | A file our `<video>` loops muted with no controls; YouTube's player always shows its controls and branding |
| A video people watch (a `Video` section, a featured video) | YouTube first, Pixabay when YouTube has nothing or no quota | Real content with sound, credited to its channel |
| Seeded `video` fields in apps | Pixabay first, YouTube when there is no Pixabay key | Plays in Epic 29's player, with our subtitle tracks and our controls |

**Requirements:** FR-45 (new, proposed: sample videos with attribution), extends FR-41 and FR-43.

## Decisions (proposed 2026-11-08)

| # | Decision | Instead of |
|---|---|---|
| D1 | `VIDEO_PROVIDERS` lists the providers that are on (`youtube`, `pixabay`; empty by default), with `YOUTUBE_API_KEY` and `PIXABAY_API_KEY`; each place asks the providers in the order of the table above | One provider for every place |
| D2 | **Search at draft time in code.** YouTube: `search.list` with `type=video`, `videoEmbeddable=true`, `safeSearch=strict`, a duration filter from the place, the app's language as `relevanceLanguage`. Pixabay: `api/videos/` with `video_type=film`, `safesearch=true`, the app's language and a minimum width, then code keeps the place's orientation and duration; the file chosen is the smallest of the four sizes at least as wide as the place and under the place's byte budget (Story 31.2) | The model naming videos or URLs |
| D3 | **Embed or hotlink, never copy** (confirmed against each provider's terms in 31.1 / 31.2). YouTube plays in its player, loaded only when the user presses play (a facade). Pixabay video files are played from Pixabay's links (its docs: "Videos may be embedded directly in your applications"); their poster thumbnails are images, which Pixabay does not allow hotlinking, so posters are stored with the site or the app's seed | Downloading videos into the project |
| D4 | **Limits first.** A YouTube search costs 100 of the default 10,000 units a day (about 100 searches); Pixabay allows 100 requests per 60 s per key and asks that requests be cached for 24 h and that no mass or automated querying happens. Phrases are cached per provider (phrase + language + orientation / duration → results); a draft makes at most a handful of searches; with nothing left, the place falls back as today | One search per video place |
| D5 | **Credit**: YouTube: the title and "<channel> on YouTube" with a link; Pixabay: "Video by <name> on Pixabay" with links (Pixabay asks to show users where videos come from). The project README lists every video | No credit |
| D6 | **Videos can disappear**: a video that is gone or no longer embeddable shows its poster with a link (YouTube) or the place's fallback (Pixabay); the preview checks each one once | Trusting ids and links forever |
| D7 | **Each provider's terms are read before its code** (YouTube API Services Terms and Developer Policies; Pixabay's API documentation and Content License), and its story records what they require | Assuming the photo rules carry over |
| D8 | **Sites and trees get video only through the library**: the `Video` section, the hero's background video, and `video` assets drawn by the renderer; trees still refuse raw `iframe` / `video` | Allowing iframes or video tags in trees |
| D9 | **Moving backgrounds are polite**: muted, `playsinline`, a poster first, a pause button (moving content longer than 5 seconds), paused under `prefers-reduced-motion` and when the browser asks to save data, text over it keeps AA contrast on the worst frame (a scrim) | Autoplaying video that cannot be stopped |

```
 draft (model): {query: "<what the video shows>", place: hero-background | watch | seed, duration?}
        │
        ▼ code: providers in the place's order (cached, within limits)
            YouTube search → {id, title, channel}      Pixabay search → {file url, poster, width, author}
        │
        ▼
 FrontendSpec asset {kind: video, source: youtube | pixabay, …, credit}   ·   app seed: video field = link
        │
        ├─▶ site renderer: <VideoEmbed> facade (YouTube) · <BackgroundVideo> in the hero (Pixabay) · Video section
        └─▶ app kit: VideoPlayer: a Pixabay link plays natively (with our tracks), a YouTube link becomes the facade
```

## Stories

| Story | What |
|---|---|
| [31.1](story31.1_youtube_provider.md) | The YouTube provider: terms checked, search, cache, quota, availability check |
| [31.2](story31.2_pixabay_provider.md) | The Pixabay provider: search, file choice by size, posters, cache, limits |
| [31.3](story31.3_video_in_sites.md) | Sites: a `Video` section, hero background videos, video assets, facades, credits |
| [31.4](story31.4_video_in_apps.md) | Apps: seeded video fields from Pixabay (or YouTube), played by the kit |
| [31.5](story31.5_final_check.md) | Real drafts within the providers' limits |

Order: 31.1 and 31.2 (independent) → 31.3 → 31.4 (after Epic 29's 29.3) → 31.5. 31.3 does not need Epic 29.

## Status

Proposed 2026-11-08, for review. The user chose both providers (2026-11-08).

**YouTube key checked (2026-11-08):** `YOUTUBE_API_KEY` in `.env` works: `videos.list` (1 unit) returned an embeddable
video with its duration, and one `search.list` with D2's filters (`type=video`, `videoEmbeddable=true`,
`safeSearch=strict`, `videoDuration=short`, `relevanceLanguage=en`, 3 results; 100 units) returned three embeddable
videos with their channels. 101 units spent.

**Pexels replaced by Pixabay (2026-11-08):** Pexels stopped issuing API keys for now (the user). Pixabay's key
(`PIXABAY_API_KEY`) works, and its docs were read the same day: videos may be linked directly, images (posters) may
not; 100 requests per 60 s per key; requests cached 24 h. Its Cloudflare front refuses curl's default client name, so
the adapter sends a descriptive `User-Agent` (Story 31.2).

**Stories 31.1–31.4 done 2026-11-09** (see each story's Status): both providers behind one port with their caches and
limits, videos in sites (the `Video` section, hero background clips, the facade and the polite background player,
trees) and in apps (seeded video fields, the kit's facade and credits). `FRONTEND_MAX_PHOTOS` now caps paid photos
only (the user's note, 2026-11-09): with Unsplash the hour's requests and the search cache are the bound. 31.5 runs
with the other epics' final checks.

**Done 2026-11-09** (commit 96584c6; final check in Story 31.5): the providers, the site assets, the Video
section and background video, the seeded video fields and the credits are in; the final check ran with both providers
on (Story 31.5's Status: the app drafts seeded no video rows, one incidental static site showed four credited videos).
