# Epic 29 — Media fields: video, audio and subtitles, uploaded and played

## Overview

Proposed 2026-11-08 for the user's review. Story 10.5 gave the BackendSpec `file` and `image` fields: the `storage`
plugin presigns uploads, checks type and size, and returns a signed read URL (`<field>Url`). The pipeline carries
any file, so a video or an audio file can already be uploaded as a `file` with `accept: ["video/*"]`. **But nothing
plays it**: the kit's `FileValue` shows an image or a download link, the upload field has no progress for large
files, the mocks and seeds have no sample media, and there is no notion of subtitles.

This epic makes video, audio and subtitles first-class field types, from the BackendSpec through the contract and
the mocks to players in the app kit. It is about **playing the file the user uploaded**, in formats browsers play
as they are. Transcoding, adaptive streaming (HLS / DASH), live streams and DRM are out of scope.

| Finding (code, 2026-11-08) | Effect |
|---|---|
| `FieldType` has `file` and `image` only (`backend_spec/schema_v1.py`); the planner sets `kind`, `accept` and `maxSize` from `IMAGE_TYPES`, `MAX_IMAGE_SIZE`, `MAX_FILE_SIZE` (`backend/planner.py`) | A media field is a generic file: no playable default types, the file size limit is too small for video |
| `FileValue.tsx` (storage plugin frontend) renders `<img>` for images, else a download link | An uploaded video or audio file cannot be played in the app |
| `UploadField` sends one presigned `PUT`, with no progress | A large upload looks frozen |
| The mocks keep uploads as blob or data URLs (`src/mocks/plugins.ts`, `fileUrls`); seeds use outside links or stand-in keys (`_stand_in`) | On mocks and in previews a media field has nothing to play |
| `Media` in `views.tsx` and the field roles know `media` as an image | A media grid of videos shows no poster, duration or play affordance |
| Signed read URLs expire (`storage_url_expire_seconds`) | A long playback can fail when the URL expires mid-way |

**Requirements:** FR-43 (new, proposed: media fields), extends FR-34 (storage plugin) and FR-36.

## Decisions (proposed 2026-11-08)

| # | Decision | Instead of |
|---|---|---|
| D1 | **Three new field types**: `video`, `audio`, `subtitles`. Like `file` / `image`, each is a string column with the object key and a signed `<field>Url` | `file` with an `accept` list the kit has to interpret |
| D2 | **Only formats browsers play natively** by default: video `video/mp4`, `video/webm`; audio `audio/mpeg`, `audio/mp4`, `audio/ogg`, `audio/wav`, `audio/webm`; subtitles `text/vtt` and SubRip (`.srt`, converted to WebVTT in the browser). `accept` can narrow them, never widen them to formats that need transcoding | A transcoding job (ffmpeg) in every app |
| D3 | **Subtitles have two shapes, both found by code**: a `subtitles` field on the media record (one track), or a child entity with a `subtitles` field and a language field (many tracks, one per language) | A special subtitle model in the BackendSpec |
| D4 | **Native HTML players** (`<video>`, `<audio>`, `<track>`) styled by the kit's tokens, with a small control bar for the look; no player library | A third-party player |
| D5 | **Never autoplay with sound**; captions on when the user's language has a track; keyboard and screen reader friendly; reduced motion: no hover previews | Autoplay previews |
| D6 | **Sample media are ours**: tiny files generated for the kit (a few seconds of a test pattern, a short tone, a WebVTT file), licence-free, used by the mocks, the seeds and the walker | Downloading stock video at draft time |
| D7 | **Single-request uploads with progress** up to the field's `maxSize` (default 200 MB for video, 50 MB for audio, 1 MB for subtitles); multipart uploads for larger files are a later story | Multipart from the start |
| D8 | **A playback that fails on an expired URL refetches the record** and resumes at the same time | Long-lived URLs |

```
 BackendSpec field: video | audio | subtitles (accept, maxSize defaults)
        │  planner: column.file {kind, accept, maxSize, prefix}
        ▼
 contract: presign accepts the kind's types · record has <field>Url · x-bga.storage.fields kind
        │
        ├──▶ backend (storage plugin): checks, signed URLs, seeds upload the sample files
        ├──▶ mocks: sample files from the kit, uploads as blob URLs
        ▼
 kit: UploadField (progress, preview, duration)   FileValue → VideoPlayer / AudioPlayer / tracks
      views: poster + duration + play badge        detail: player at the top    shell: listening bar (audio)
```

## Stories

| Story | What |
|---|---|
| [29.1](story29.1_media_field_types.md) | `video`, `audio`, `subtitles` in the BackendSpec, the planner, the contract and the storage plugin |
| [29.2](story29.2_sample_media.md) | Sample media for mocks, seeds and the walker |
| [29.3](story29.3_players_and_uploads.md) | Players and uploads in the kit: video, audio, subtitles, progress |
| [29.4](story29.4_media_in_views.md) | Media in lists, records and the shell: posters, durations, a listening bar |
| [29.5](story29.5_drafting_media.md) | Drafting picks media field types and roles from the requirement |
| [29.6](story29.6_final_check.md) | Final check on real drafts |

Order: 29.1 → 29.2 → 29.3 → 29.4 → 29.5 → 29.6. Epic 30's media layouts (watch page, shelves) build on 29.3.

## Expected output

- A requirement that mentions videos, recordings, episodes, lessons with audio or captions gets media fields in its
  BackendSpec; the generated app uploads them with progress, plays them in lists and records, and shows subtitles in
  every language uploaded.
- On mocks and in previews, media fields play the sample files, so every screen shows a working player.

Not in this epic: transcoding, thumbnails extracted on the server, adaptive streaming, live video, DRM, uploads larger
than one request, waveform rendering, playlists as a backend concept.

## Status

Proposed 2026-11-08, for review. **Stories 29.1–29.5 done 2026-11-09** (see each story's Status): the three field
types through the schema, the validator, the planner, the storage plugin, the contract's fixtures and tracks, the
seeds' sample objects (also in previews), the kit's players, uploads and listening bar, the design brief's `duration`
role and video media, and the v6 drafting prompt with code fixes. 29.6 (real drafts, uploads on the live backend)
runs with the other epics' final checks.

**Done 2026-11-09** (commit ea5aa73; final check in Story 29.6): video, audio and subtitles fields, their samples,
players and tracks are in; the two real drafts typed their media fields without a repair and seeded the samples;
manual live uploads were not part of this session's run (Story 29.6's deviations).
