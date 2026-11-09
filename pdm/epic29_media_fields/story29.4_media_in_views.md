# Story 29.4 — Media in lists, records and the shell

**Epic:** [29 — Media fields](epic29_media_fields.md) · **Requirements:** FR-43, FR-37 · **Depends on:** 29.3

## User story

As a user browsing media records, I want lists to show posters and durations, records to open on the player, and
audio to keep playing while I move around the app, so that media feel at home in every view.

## Context

- Views (`views.tsx`): `MediaGrid`, `Feed`, `RoleCards`, `CatalogueRows`; detail views `record`, `media`, `profile`
  (`AppDetail.tsx`); field roles (`media`, `title`, `meta`, …) from `design.py`.
- `Media` draws the `media` role as an image.

## Steps

1. **Field roles:** `media` may be a video field (the poster is the record's image field, else the first frame), and a
   new role `duration` (a number of seconds or a `video` / `audio` field's own duration) shows as `m:ss` on cards.
   `design.py` assigns them by type and name; `ROLE_ORDER` gains `duration`.
2. **Lists:** `MediaGrid`, `RoleCards` and `Feed` show a video's poster with a play badge and the duration; an audio
   record shows a compact play button in its row or card (playing in place, one at a time).
3. **Records:** the `media` detail view puts the video player at the top; for audio, the player under the title; the
   tracks (29.1) list below as their own rows when they are child records.
4. **Listening bar:** when the app has `audio` fields, `AppShell` gets a bar above the bottom tabs or at the page's
   bottom that keeps the current audio playing across pages (title, play / pause, seek, close); the compact players
   hand their file to it. Video is not kept across pages.
5. **Design check:** the synthetic media app joins `make app-design-report`'s set; every view with media is
   screenshot at 375 / 1440, light / dark.
6. Tests: role assignment on synthetic specs (a video with an image field, a video alone, audio with a duration
   number); vitest: one compact audio at a time, the listening bar survives navigation.

## Acceptance criteria

- [ ] Lists of media records show posters, durations and play affordances in every view that has a `media` role.
- [ ] A record with a video opens on its player; audio keeps playing across pages in the listening bar.
- [ ] Design checks pass for the media app in every shell and recipe the report covers.

## Verify

`make test`, the kit's vitest, `make design-check-app`, `make app-design-report`.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** `design.py`: the `media` role takes a video or audio field (`_Data.media`), a new `duration` role
(a number of seconds or minutes, or the media field itself) in `ROLE_ORDER`, filled by code for media entities
(`first_duration`), a video record's `detailView` defaults to `media`; `AppFieldRoles.duration`. Views: `Media` shows a
video field as the compact player (poster, play badge, duration) and an audio field as a compact play button;
`MediaGrid`, `RoleCards` and `Feed` show the `duration` role as m:ss (`durationText`). Records: the `media` detail puts
the video player at the top; an audio field's player sits under the title. The listening bar (`ListeningBar`, a storage
plugin slot; `listening.ts` is the one store) is mounted by `AppShell` for apps with audio (`app.json` `media.audio`),
above the bottom tabs on phones; compact players hand their file to it, so audio keeps playing across pages. The
synthetic media app (`examples/specs/media-library.json`, outline and requirement) joins `make app-design-report`'s
set as a hand-written example. Tests: `test_media_fields.py` (roles and defaults on the media app and a brief with
wrong roles, `app.json`'s tracks and media). Design check: `make design-check-app ARGS="--app
media-library:media-library"` (result below).

**Design check (2026-11-09):** `make design-check-app ARGS="--app media-library:media-library"`: 64 views (16 screens,
375 / 1440 px, light / dark), no sideways scroll, two font families, no clipped or unlabelled form control; the media
grid shows each lesson's first frame with the play badge and the duration, the lesson page opens on the player with
its caption tracks under it, the podcast feed shows the compact play button. The first compact video collapsed to a
line before the players took their card's whole box (`fill`), fixed the same day. Screenshots under
`agent-api/.data/shots/epic29/media-library/`.
