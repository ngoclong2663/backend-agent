// Story 29.3: the SubRip converter, the default track by the user's language, durations as m:ss.
import { describe, expect, it, vi } from "vitest";
import { defaultTrack, formatDuration, isSrt, srtToVtt } from "./subtitles";

describe("subtitles", () => {
  it("converts SubRip to WebVTT: cue numbers dropped, commas to dots in the times", () => {
    const srt = "1\r\n00:00:00,500 --> 00:00:02,000\r\nA sample video.\r\n\r\n2\r\n00:00:02,200 --> 00:00:04,000\r\nIts captions, here.\r\n";
    expect(srtToVtt(srt)).toBe("WEBVTT\n\n00:00:00.500 --> 00:00:02.000\nA sample video.\n\n00:00:02.200 --> 00:00:04.000\nIts captions, here.\n");
    expect(isSrt("https://files.example/a.srt?X-Amz=1")).toBe(true);
    expect(isSrt("https://files.example/a.vtt", "text/vtt")).toBe(false);
  });

  it("turns on the track of the user's language, none otherwise", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("ja-JP");
    const tracks = [
      { src: "/samples/sample.en.vtt", language: "en", label: "English" },
      { src: "/samples/sample.ja.vtt", language: "ja", label: "日本語" },
    ];
    expect(defaultTrack(tracks)?.language).toBe("ja");
    vi.spyOn(navigator, "language", "get").mockReturnValue("fr");
    expect(defaultTrack(tracks)).toBeUndefined();
    vi.restoreAllMocks();
  });

  it("formats durations", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(372)).toBe("6:12");
    expect(formatDuration(3725)).toBe("1:02:05");
    expect(formatDuration(null)).toBe("");
    expect(formatDuration(Number.NaN)).toBe("");
  });
});
