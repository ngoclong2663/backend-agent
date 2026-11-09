"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { defaultTrack, formatDuration, isSrt, trackUrl, type TTrack } from "./subtitles";

type VideoPlayerProps = {
  src: string;
  poster?: string | null;
  tracks?: TTrack[];
  title?: string;
  /** Lists (Story 29.4): the poster with a play badge and the duration; plays in place on click. */
  compact?: boolean;
  className?: string;
  /** A known duration (a record's field), shown before the file's metadata loads. */
  duration?: number | null;
};

/** The native `<video>` (Epic 29 D4), styled by the kit's tokens: `controls`, `playsinline`, metadata preloaded, never
 *  autoplay with sound (D5); the record's subtitle tracks, the user's language on by default; SubRip converted in the
 *  browser. A read URL that expired mid-way (D8) is asked again once (the record's queries refetch) and playback
 *  resumes at the same time. */
export function VideoPlayer({ src, poster, tracks = [], title, compact = false, className, duration }: VideoPlayerProps) {
  const queryClient = useQueryClient();
  const video = useRef<HTMLVideoElement>(null);
  const resumeAt = useRef<number | null>(null);
  const retried = useRef(false);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [playing, setPlaying] = useState(!compact);
  const [length, setLength] = useState<number | null>(duration ?? null);
  const chosen = defaultTrack(tracks);

  useEffect(() => {
    // SubRip tracks become WebVTT blob URLs (revoked when the tracks change)
    let active = true;
    const made: string[] = [];
    Promise.all(
      tracks.filter((track) => isSrt(track.src)).map(async (track) => {
        const url = await trackUrl(track.src, "application/x-subrip").catch(() => track.src);
        if (url !== track.src) made.push(url);
        return [track.src, url] as const;
      }),
    ).then((pairs) => {
      if (active) setUrls(Object.fromEntries(pairs));
    });
    return () => {
      active = false;
      for (const url of made) URL.revokeObjectURL(url);
    };
  }, [tracks]);

  useEffect(() => {
    // the URL changed (a refetch after an expired one): back to where playback was
    const element = video.current;
    if (!element || resumeAt.current === null) return;
    const at = resumeAt.current;
    resumeAt.current = null;
    const seek = () => {
      element.currentTime = at;
      void element.play().catch(() => {});
    };
    if (element.readyState >= 1) seek();
    else element.addEventListener("loadedmetadata", seek, { once: true });
  }, [src]);

  function onError() {
    const element = video.current;
    if (!element || retried.current) return;
    retried.current = true;
    resumeAt.current = element.currentTime || 0;
    void queryClient.invalidateQueries();
  }

  if (compact && !playing) {
    return (
      <button
        type="button"
        className={cn("group/video relative block aspect-video w-full overflow-hidden rounded-lg bg-muted text-left focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none", className)}
        onClick={() => setPlaying(true)}
        aria-label={title ? `Play ${title}` : "Play"}
        data-bga-media="video"
      >
        {poster ? (
          // eslint-disable-next-line @next/next/no-img-element -- a signed URL or a sample
          <img src={poster} alt="" className="size-full object-cover" loading="lazy" />
        ) : (
          <video src={`${src}#t=0.5`} preload="metadata" muted playsInline className="absolute inset-0 size-full object-cover" onLoadedMetadata={(event) => setLength(event.currentTarget.duration)} />
        )}
        <span className="absolute inset-0 flex items-center justify-center bg-black/20 transition-colors group-hover/video:bg-black/30 motion-reduce:transition-none">
          <span className="flex size-11 items-center justify-center rounded-full bg-background/90 text-foreground shadow">
            <Play className="ml-0.5 size-5" aria-hidden />
          </span>
        </span>
        {length ? <span className="absolute right-1.5 bottom-1.5 rounded bg-black/70 px-1.5 py-0.5 text-xs tabular-nums text-white">{formatDuration(length)}</span> : null}
      </button>
    );
  }
  return (
    <video
      ref={video}
      key={src}
      src={src}
      poster={poster ?? undefined}
      controls
      playsInline
      preload="metadata"
      autoPlay={compact}
      className={cn("w-full rounded-lg bg-black outline-none focus-visible:ring-3 focus-visible:ring-ring/50", className)}
      title={title}
      onError={onError}
      onLoadedMetadata={(event) => setLength(event.currentTarget.duration)}
      data-bga-media="video"
    >
      {tracks.map((track) => (
        <track
          key={track.src}
          kind="subtitles"
          src={urls[track.src] ?? track.src}
          srcLang={track.language ?? undefined}
          label={track.label ?? track.language ?? "Subtitles"}
          default={track === chosen}
        />
      ))}
    </video>
  );
}
