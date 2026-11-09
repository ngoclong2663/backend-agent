# Story 29.3 — Players and uploads in the kit

**Epic:** [29 — Media fields](epic29_media_fields.md) · **Requirements:** FR-43, FR-36 · **Depends on:** 29.1, 29.2

## User story

As a user of a generated app, I want to upload a video or a recording and see it upload, then play it with
subtitles in my language, so that media in the app work like in any product I use.

## Context

- The storage plugin's frontend (`templates/plugins/storage/frontend/files/src/components/plugins/storage/`):
  `UploadField.tsx`, `FileValue.tsx`, exported through the kit's `plugins.ts` slots (22.7).
- `FieldValue.tsx` sends file and image fields to `FileValue`; the kit's tokens and the recipe (23.7) give the look.

## Steps

1. **`VideoPlayer`** (storage plugin frontend): `<video controls playsinline preload="metadata">` with the poster
   (the record's `media` role image when there is one, else the first frame), the tracks of the field (29.1's
   `tracks`: label, language, `default` on the user's language), and the kit's controls look (focus ring, radius,
   tokens). Compact mode in lists: the poster with a play badge and the duration; it opens the record or plays in
   place, by the view.
2. **`AudioPlayer`:** `<audio controls preload="metadata">` with a compact row (play button, time, a seek bar) and the
   full native controls in records.
3. **Subtitles:** `.vtt` used as is; `.srt` converted in the browser to WebVTT (a small parser: cue numbers dropped,
   `,` → `.` in times) and given to `<track>` as a blob URL. A `subtitles` field shown alone (a track record) shows its
   language and a download link.
4. **Expired URLs (D8):** on a media `error` the player refetches the record's query once and resumes at the same
   time.
5. **`UploadField` for media:** upload through `XMLHttpRequest` with a progress bar and a cancel button; after
   choosing, a preview (the local file plays before upload); reads the duration from the file's metadata and fills a
   form field whose role is `duration` or whose name says so (`duration`, `durationSeconds`, `length`) when the form
   has one and it is empty.
6. **Accessibility:** players reachable and operable by keyboard; captions toggle; no autoplay with sound (D5);
   reduced motion turns hover previews off.
7. Tests (vitest): the SRT converter; tracks chosen by language; the refetch on error; upload progress and cancel
   (mocked XHR); the duration fill.

## Acceptance criteria

- [ ] On mocks, a media record plays its video or audio with its subtitle tracks, light and dark, at 375 and 1440 px.
- [ ] Uploading a media file shows progress, can be cancelled, and the record plays it after saving.
- [x] `.srt` and `.vtt` subtitles both show as captions.
- [x] Apps without media fields get no new code in their bundle.

## Verify

The kit's vitest and `tsc`, `make design-check-app` on the synthetic media app, `make up`.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** Storage plugin frontend: `VideoPlayer` (native `<video controls playsinline preload=metadata>`,
the record's poster (its first image field) or the first frame, the tracks of the field with the user's language on by
default, a compact mode with the poster, a play badge and the duration that plays in place), `AudioPlayer` (native
controls in records with "Keep playing" to the listening bar; a compact play / pause in lists that plays through the
bar, one at a time), `subtitles.ts` (`srtToVtt`, blob URLs for SubRip tracks, `defaultTrack`, `formatDuration`),
`FileValue` dispatches image / video / audio / subtitles (a track record shows its language and a download link) and
reads the tracks (`useTracks`: a same-record field, or the child list filtered by the parent). Expired URLs (D8): on a
media error the player asks the record's queries again once and resumes at the same time. `UploadField`: XHR with
progress and a Cancel, a local preview that plays before saving, the file's type from its name when the browser gives
none (`.srt`, `.vtt`), the duration read from the file's metadata (with a 2.5 s cap) filling the form's empty
`duration` / `runtime` / `length` field (minutes when the name or unit says so). Accessibility: native players, no
autoplay with sound, the compact badge is a button. The plugin's files are copied only for apps with the storage
plugin, and the players render only for media kinds, so other bundles are unchanged. Tests (vitest, `make kit-test
--app media-library:media-library`): the converter, the default track by language, durations, upload progress and
cancel on a fake XHR, the duration fill. Light / dark at 375 / 1440: `make design-check-app` on the media app (below,
29.4).
