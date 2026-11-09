# Story 29.1 — `video`, `audio` and `subtitles` field types

**Epic:** [29 — Media fields](epic29_media_fields.md) · **Requirements:** FR-43, FR-34 · **Depends on:** 10.5

## User story

As a user describing an app with recordings or videos, I want media fields that the backend accepts and checks like
images, with sensible types and sizes, so that uploads of media work without me listing MIME types.

## Context

- `FieldType` (`backend_spec/schema_v1.py`) and the validator's file rules (`accept`, `maxSize` only on `file` and
  `image`, `backend_spec/validator.py`).
- `backend/planner.py` builds `column.file` (`kind`, `accept`, `maxSize`, `prefix`); the `storage` plugin
  (`plugins/storage.py`) writes presign checks, upload checks in use cases, `<field>Url`, tests and seeds, and picks a
  content type per kind for its scenarios (`image/png`, else the first `accept`).

## Steps

1. **Schema:** `FieldType` gains `video`, `audio`, `subtitles`; `accept` and `maxSize` apply to them; the validator
   refuses an `accept` entry outside the kind's playable set (D2) with the allowed list as the suggestion.
2. **Planner:** defaults per kind in one table (`MEDIA_KINDS` next to `IMAGE_TYPES`): types and `maxSize` (D7);
   `column.file.kind` is the field type.
3. **Storage plugin:** presign and upload checks per kind; scenarios and test cases use a content type of the kind
   (`video/mp4`, `audio/mpeg`, `text/vtt`), a too-large size from the kind's limit, a refused type from another kind;
   `x-bga.storage.fields` carries `kind`. Subtitles accept `.srt` (`application/x-subrip`) and `.vtt`.
4. **Reads:** the signed read URL of a media field allows range requests (the S3-compatible store answers them; a test
   checks `Range` on the sandbox store) and sets `ResponseContentType` from the stored key's type.
5. **Subtitle shapes (D3), code only:** the contract marks the tracks of a media field:
   `x-bga.storage.tracks[<Entity>.<mediaField>]` = the same record's `subtitles` fields, or a child entity (a reference
   to the media record) with a `subtitles` field and a language-like field (`language`, `lang`, `locale`, an enum of
   language codes), plus an optional label field.
6. Tests: schema and validator cases; planner defaults; plugin scenarios per kind; the tracks finder on synthetic
   specs (same-record track, child tracks with a language enum, a child without a language: one track, no language);
   contract snapshot updates.

## Acceptance criteria

- [x] A BackendSpec with `video`, `audio` and `subtitles` fields validates, generates and passes the smoke check.
- [x] Uploads of a refused type or a too-large file get the plugin's 422 codes, per kind.
- [x] The contract lists the subtitle tracks of each media field in both shapes.
- [x] Specs without the new types generate byte-identical code (backend golden tests).

## Verify

`make lint`, `make test`, `make up` with a synthetic media spec (backend only).

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** `backend_spec/media.py` holds the kinds (`FILE_KINDS`, `MEDIA_KINDS`), the playable types per
kind (D2: MP4 / WebM; MPEG, MP4, OGG, WAV, WebM audio; WebVTT and SubRip), the default sizes (D7: 200 MB video, 50 MB
audio, 1 MB subtitles), the samples' names and `media_tracks` (D3). `FieldType` gains the three types; the validator
lets `accept` / `maxSize` on every file kind and refuses an `accept` entry outside the kind's playable set with the
allowed list as the hint. The planner's `MEDIA_KINDS` table gives `column.file` its kind, types and size. The storage
plugin applies to every file kind, uses the kind's sample type for the presign scenarios, the smoke objects and the
generated tests (`sample_content_type`), stands in `.mp4` / `.mp3` / `.vtt` keys for outside links, and writes
`x-bga.storage.tracks` (`Entity.field` → tracks, `shape: field` or `shape: child` with the foreign key, language and
label fields). The S3 adapter's read URLs carry `ResponseContentType` from the key's extension (range requests are
S3's own; checked on the live preview in 29.6 rather than by a sandbox test). The committed schema and digests were
regenerated. Tests: `tests/test_media_fields.py` (validation and defaults, the refused type, the plugin's types per
kind, tracks in both shapes and a child without a language); the storage, contract, planner and golden suites pass
unchanged. The smoke check on a generated media backend is part of 29.6's real run.
