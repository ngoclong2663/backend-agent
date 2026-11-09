"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { videoCredit, youtubeId, type TVideoCredit } from "@/components/app/app";
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
  const credit = videoCredit(src);
  const youtube = youtubeId(src);
  if (youtube) return <YouTubeFacade id={youtube} poster={poster} title={title} compact={compact} className={className} credit={credit} />;
  return <NativeVideo src={src} poster={poster} tracks={tracks} title={title} compact={compact} className={className} duration={duration} credit={credit} />;
}

/** Epic 31 (Story 31.4): a seeded YouTube link plays in YouTube's player, loaded only when the user presses play
 *  (the same facade as the sites'); its title and channel are credited under it. */
function YouTubeFacade({ id, poster, title, compact, className, credit }: { id: string; poster?: string | null; title?: string; compact: boolean; className?: string; credit: TVideoCredit | null }) {
  const [playing, setPlaying] = useState(false);
  const thumb = poster ?? `https://i.ytimg.com/vi/${id}/hqdefault.jpg`;
  if (!playing) {
    return (
      <span className={cn("flex flex-col gap-1", compact && "size-full")} data-bga-media="youtube">
        <button
          type="button"
          className={cn("group/video relative block aspect-video w-full overflow-hidden rounded-lg bg-muted text-left focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none", compact && "size-full rounded-none", className)}
          onClick={() => setPlaying(true)}
          aria-label={title ? `Play ${title}` : "Play"}
          data-bga-video-play
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- YouTube's thumbnail, hotlinked as its terms allow */}
          <img src={thumb} alt="" className="size-full object-cover" loading="lazy" />
          <span className="absolute inset-0 flex items-center justify-center bg-black/25 transition-colors group-hover/video:bg-black/35 motion-reduce:transition-none">
            <span className="flex size-11 items-center justify-center rounded-full bg-background/90 text-foreground shadow">
              <Play className="ml-0.5 size-5" aria-hidden />
            </span>
          </span>
        </button>
        {!compact && credit && <SampleVideoCredit credit={credit} />}
      </span>
    );
  }
  return (
    <span className="flex flex-col gap-1" data-bga-media="youtube">
      <iframe
        src={`https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0`}
        title={title ?? "Video"}
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        referrerPolicy="strict-origin-when-cross-origin"
        allowFullScreen
        className={cn("aspect-video w-full rounded-lg border-0", compact && "size-full rounded-none", className)}
      />
      {!compact && credit && <SampleVideoCredit credit={credit} />}
    </span>
  );
}

/** "<title> · <channel> on YouTube" or "Video by <name> on Pixabay" under a seeded video's player. */
export function SampleVideoCredit({ credit }: { credit: TVideoCredit }) {
  const site = credit.provider === "youtube" ? "YouTube" : "Pixabay";
  return (
    <span className="text-xs text-muted-foreground" data-bga-video-credit>
      {credit.provider === "youtube" ? (credit.title ? <span className="font-medium text-foreground">{credit.title} · </span> : null) : "Video by "}
      <a href={credit.profileUrl ?? credit.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
        {credit.name}
      </a>{" "}
      on{" "}
      <a href={credit.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
        {site}
      </a>
    </span>
  );
}

function NativeVideo({ src, poster, tracks = [], title, compact = false, className, duration, credit }: VideoPlayerProps & { credit: TVideoCredit | null }) {
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
  const player = (
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
  if (compact || !credit) return player;
  return (
    <span className="flex flex-col gap-1">
      {player}
      <SampleVideoCredit credit={credit} />
    </span>
  );
}
