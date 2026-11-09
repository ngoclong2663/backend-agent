"use client";

import { useState } from "react";
import { assets } from "@/assets";
import { cn } from "@/lib/utils";

type TVideo = {
  provider: "youtube" | "pixabay";
  id: string;
  title?: string;
  url?: string;
  poster?: string;
  width?: number;
  height?: number;
  duration?: number;
};
type TCredit = { provider?: string; name: string; sourceUrl: string; profileUrl?: string; title?: string };

type VideoEmbedProps = {
  /** The asset (`asset:<id>`) of kind `video`. */
  asset: string;
  className?: string;
  /** Lists (the Video section's grid): a smaller play badge. */
  compact?: boolean;
};

function videoOf(entry: object | undefined): TVideo | undefined {
  return (entry as { video?: TVideo } | undefined)?.video;
}

function creditOf(entry: object | undefined): TCredit | undefined {
  return (entry as { credit?: TCredit } | undefined)?.credit;
}

/** Epic 31 (Story 31.3): a video people watch. A YouTube video is a **facade** (D3): the poster with a play button,
 *  the title and the credit; the `youtube-nocookie.com` player loads only when the user presses play, so no YouTube
 *  request happens before that. Without JavaScript the facade is a link to the video. A Pixabay file plays in our own
 *  `<video controls>` with its poster. Keyboard operable; the credit links back as each provider asks (D5). */
export function VideoEmbed({ asset, className, compact = false }: VideoEmbedProps) {
  const id = asset.replace(/^asset:/, "");
  const entry = assets[id];
  const video = videoOf(entry);
  const credit = creditOf(entry);
  const [playing, setPlaying] = useState(false);
  const label = entry?.alt ?? video?.title ?? id;
  const frame = cn("relative w-full overflow-hidden rounded-xl bg-muted", className);

  if (!video) {
    return <div data-bga-asset={id} role="img" aria-label={label} className={cn(frame, "aspect-video bg-gradient-to-br from-primary/30 via-accent to-secondary")} />;
  }
  if (video.provider === "pixabay" && video.url) {
    return (
      <figure data-bga-asset={id} data-bga-video="pixabay" className="flex flex-col gap-2">
        <video src={video.url} poster={video.poster} controls playsInline preload="metadata" className={cn(frame, "aspect-video")} title={video.title} />
        {credit && <VideoCredit credit={credit} />}
      </figure>
    );
  }
  const watch = `https://www.youtube.com/watch?v=${video.id}`;
  return (
    <figure data-bga-asset={id} data-bga-video="youtube" className="flex flex-col gap-2">
      {playing ? (
        <iframe
          src={`https://www.youtube-nocookie.com/embed/${video.id}?autoplay=1&rel=0`}
          title={video.title ?? label}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          referrerPolicy="strict-origin-when-cross-origin"
          allowFullScreen
          className={cn(frame, "aspect-video border-0")}
        />
      ) : (
        <a
          href={watch}
          target="_blank"
          rel="noopener noreferrer"
          className={cn(frame, "group/facade block aspect-video focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none")}
          onClick={(event) => {
            event.preventDefault();
            setPlaying(true);
          }}
          aria-label={`Play ${video.title ?? label}`}
          data-bga-video-play
        >
          {video.poster ? (
            // eslint-disable-next-line @next/next/no-img-element -- YouTube's thumbnail, hotlinked as its terms allow
            <img src={video.poster} alt="" loading="lazy" className="size-full object-cover" />
          ) : null}
          <span className="absolute inset-0 flex items-center justify-center bg-black/25 transition-colors group-hover/facade:bg-black/35 motion-reduce:transition-none">
            <span className={cn("flex items-center justify-center rounded-full bg-background/90 text-foreground shadow", compact ? "size-11" : "size-16")}>
              <svg viewBox="0 0 24 24" aria-hidden className={cn("ml-0.5 fill-current", compact ? "size-5" : "size-7")}>
                <path d="M8 5v14l11-7z" />
              </svg>
            </span>
          </span>
          {!compact && video.title && (
            <span className="absolute inset-x-0 top-0 truncate bg-gradient-to-b from-black/60 to-transparent px-4 py-3 text-sm font-medium text-white">{video.title}</span>
          )}
        </a>
      )}
      {credit && <VideoCredit credit={credit} />}
    </figure>
  );
}

/** "<title> · <channel> on YouTube" or "Video by <name> on Pixabay", linked as each provider asks. */
export function VideoCredit({ credit, className }: { credit: TCredit; className?: string }) {
  const youtube = credit.provider === "youtube";
  return (
    <figcaption className={cn("text-xs text-muted-foreground", className)} data-bga-video-credit>
      {youtube ? (
        <>
          {credit.title && <span className="font-medium text-foreground">{credit.title} · </span>}
          <a href={credit.profileUrl ?? credit.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
            {credit.name}
          </a>{" "}
          on{" "}
          <a href={credit.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
            YouTube
          </a>
        </>
      ) : (
        <>
          Video by{" "}
          <a href={credit.profileUrl ?? credit.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
            {credit.name}
          </a>{" "}
          on{" "}
          <a href={credit.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
            Pixabay
          </a>
        </>
      )}
    </figcaption>
  );
}
