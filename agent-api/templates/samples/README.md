# Sample files

Small files of our own (public domain, CC0) that the generated apps' mocks and seeds, and the evaluation's walker,
use where a file field needs something to show or to upload (Stories 28.6, 29.2). Made once by `make sample-media`
(`scripts/sample-media.sh`: ffmpeg in a one-off container, so no image of ours gains ffmpeg) and committed.

- `placeholder.png`: a 1×1 transparent PNG (the walker's upload when nothing better fits a field).
- `sample.mp4`, `sample.webm`: 6 s, 640×360, a moving test pattern in neutral tones, a silent track.
- `sample.mp3`, `sample.ogg`: 6 s of a soft tone, faded in and out.
- `sample-poster.jpg`: one frame of the pattern.
- `sample.en.vtt`, `sample.ja.vtt`, `sample.en.srt`: three cues each (English, Japanese; SubRip for the converter).

Each is under 400 KB. Apps with media fields get them under `public/samples/`; the seeds upload them under each
seeded media key, so a preview plays them until someone uploads a real file.
