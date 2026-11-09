#!/bin/sh
# Story 29.2: the sample media of the generated apps (mocks, seeds, the evaluation's walker), made once with ffmpeg in
# a one-off container (no image of ours gains ffmpeg) and committed under agent-api/templates/samples/.
#
#   make sample-media            # writes sample.mp4, sample.webm, sample.mp3, sample.ogg, sample-poster.jpg,
#                                #   sample.en.vtt, sample.ja.vtt, sample.en.srt (each under 400 KB)
#
# Our own synthetic content (a test pattern in neutral tones, a soft tone, three cues), licence CC0: see the README.
set -eu
OUT="${1:-agent-api/templates/samples}"
IMAGE="${FFMPEG_IMAGE:-jrottenberg/ffmpeg:7.1-alpine}"
mkdir -p "$OUT"
HOST_OUT="$(cd "$OUT" && pwd)"

run() {
  docker run --rm -v "$HOST_OUT:/out" "$IMAGE" "$@"
}

# 6 s, 640×360, a moving test pattern desaturated to neutral tones, a silent stereo track
run -y -f lavfi -i "testsrc2=size=640x360:rate=24" -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
  -t 6 -vf "hue=s=0.15,eq=contrast=0.9:brightness=0.02" -c:v libx264 -preset veryslow -crf 30 -pix_fmt yuv420p \
  -c:a aac -b:a 32k -shortest -movflags +faststart /out/sample.mp4
run -y -f lavfi -i "testsrc2=size=640x360:rate=24" -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
  -t 6 -vf "hue=s=0.15,eq=contrast=0.9:brightness=0.02" -c:v libvpx-vp9 -b:v 180k -crf 40 -deadline good -cpu-used 2 \
  -c:a libopus -b:a 24k -shortest /out/sample.webm
# 6 s of a soft tone (440 Hz, quiet, faded in and out)
run -y -f lavfi -i "sine=frequency=440:sample_rate=44100" -t 6 -af "volume=0.2,afade=t=in:d=0.5,afade=t=out:st=5.5:d=0.5" \
  -c:a libmp3lame -b:a 64k /out/sample.mp3
run -y -f lavfi -i "sine=frequency=440:sample_rate=44100" -t 6 -af "volume=0.2,afade=t=in:d=0.5,afade=t=out:st=5.5:d=0.5" \
  -c:a libvorbis -q:a 2 /out/sample.ogg
# the poster: one frame of the pattern
run -y -ss 2 -i /out/sample.mp4 -frames:v 1 -update 1 -q:v 6 /out/sample-poster.jpg

cat > "$OUT/sample.en.vtt" <<'EOF'
WEBVTT

1
00:00:00.500 --> 00:00:02.000
A sample video.

2
00:00:02.200 --> 00:00:04.000
Its captions show here, in your language.

3
00:00:04.200 --> 00:00:05.800
Upload your own to replace it.
EOF

cat > "$OUT/sample.ja.vtt" <<'EOF'
WEBVTT

1
00:00:00.500 --> 00:00:02.000
サンプルの動画です。

2
00:00:02.200 --> 00:00:04.000
字幕はここに、あなたの言語で表示されます。

3
00:00:04.200 --> 00:00:05.800
ご自身の動画をアップロードして置き換えてください。
EOF

cat > "$OUT/sample.en.srt" <<'EOF'
1
00:00:00,500 --> 00:00:02,000
A sample video.

2
00:00:02,200 --> 00:00:04,000
Its captions show here, in your language.

3
00:00:04,200 --> 00:00:05,800
Upload your own to replace it.
EOF

ls -la "$OUT"
for f in sample.mp4 sample.webm sample.mp3 sample.ogg sample-poster.jpg; do
  size=$(wc -c < "$OUT/$f")
  if [ "$size" -gt 409600 ]; then echo "$f is $size bytes, over 400 KB" >&2; exit 1; fi
done
echo "sample media written to $OUT"
