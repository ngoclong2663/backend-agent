/** Story 29.3: subtitle tracks for the players. WebVTT is used as it is; SubRip (`.srt`) is converted in the browser
 *  (cue numbers dropped, `,` → `.` in the times) and handed to `<track>` as a blob URL. */

export type TTrack = { src: string; language?: string | null; label?: string | null; default?: boolean };

/** SubRip text → WebVTT text. */
export function srtToVtt(srt: string): string {
  const blocks = srt
    .replace(/\r\n?/g, "\n")
    .trim()
    .split(/\n{2,}/);
  const cues = blocks.map((block) => {
    const lines = block.split("\n");
    if (lines.length > 1 && /^\d+$/.test(lines[0].trim())) lines.shift(); // the cue number
    return lines.map((line, index) => (index === 0 ? line.replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, "$1.$2") : line)).join("\n");
  });
  return `WEBVTT\n\n${cues.join("\n\n")}\n`;
}

export function isSrt(url: string, type?: string | null): boolean {
  return type === "application/x-subrip" || /\.srt(\?|$)/i.test(url);
}

/** The URL a `<track>` can load: the file itself for WebVTT; for SubRip, the converted text as a blob URL (the
 *  caller revokes it). */
export async function trackUrl(url: string, type?: string | null): Promise<string> {
  if (!isSrt(url, type)) return url;
  const response = await fetch(url);
  const text = await response.text();
  return URL.createObjectURL(new Blob([srtToVtt(text)], { type: "text/vtt" }));
}

/** The user's language (`en` of `en-GB`), to turn one caption track on by default (D5). */
export function userLanguage(): string {
  if (typeof navigator === "undefined") return "en";
  return (navigator.language || "en").split("-")[0].toLowerCase();
}

/** The track that is on by default: the user's language when a track has it, else none. */
export function defaultTrack(tracks: TTrack[]): TTrack | undefined {
  const wanted = userLanguage();
  return tracks.find((track) => (track.language ?? "").toLowerCase().split("-")[0] === wanted);
}

/** `m:ss` (or `h:mm:ss`) of a duration in seconds. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "";
  const whole = Math.max(0, Math.round(seconds));
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
