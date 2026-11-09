"use client";

import { useEffect, useRef, useState } from "react";
import { assets } from "@/assets";
import { cn } from "@/lib/utils";

type TVideo = { provider: "youtube" | "pixabay"; id: string; url?: string; poster?: string; duration?: number };
type TCredit = { provider?: string; name: string; sourceUrl: string; profileUrl?: string };

type BackgroundVideoProps = {
  /** The asset (`asset:<id>`) of kind `video` with a Pixabay file (YouTube is never a backdrop, D8). */
  asset: string;
  className?: string;
};

/** Epic 31 (Story 31.3, D9): a muted, looping background clip behind a hero's text: the poster first, `playsinline`,
 *  a visible pause / play button, paused and still under `prefers-reduced-motion` and when the browser asks to save
 *  data; a scrim keeps the text readable; the credit in the corner. Nothing plays when the asset has no file. */
export function BackgroundVideo({ asset, className }: BackgroundVideoProps) {
  const id = asset.replace(/^asset:/, "");
  const entry = assets[id];
  const video = (entry as { video?: TVideo } | undefined)?.video;
  const credit = (entry as { credit?: TCredit } | undefined)?.credit;
  const element = useRef<HTMLVideoElement>(null);
  const [still, setStill] = useState(true); // until the browser said motion is fine
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    const quiet = () => reduced.matches || Boolean(connection?.saveData);
    const apply = () => setStill(quiet());
    apply();
    reduced.addEventListener("change", apply);
    return () => reduced.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const media = element.current;
    if (!media) return;
    if (still || paused) media.pause();
    else void media.play().catch(() => setPaused(true));
  }, [still, paused]);

  if (!video?.url || video.provider !== "pixabay") {
    return video?.poster ? (
      // eslint-disable-next-line @next/next/no-img-element -- the poster of a clip that cannot play
      <img src={video.poster} alt="" className={cn("size-full object-cover", className)} data-bga-asset={id} />
    ) : null;
  }
  return (
    <div className={cn("absolute inset-0", className)} data-bga-asset={id} data-bga-video="background" data-bga-video-playing={!still && !paused ? "" : undefined}>
      {still ? (
        video.poster ? (
          // eslint-disable-next-line @next/next/no-img-element -- the poster stands still under reduced motion
          <img src={video.poster} alt="" className="size-full object-cover" />
        ) : null
      ) : (
        <video
          ref={element}
          src={video.url}
          poster={video.poster}
          muted
          loop
          playsInline
          autoPlay
          preload="metadata"
          aria-hidden
          className="size-full object-cover"
        />
      )}
      {/* the scrim: text over the clip keeps its contrast on the worst frame */}
      <div className="absolute inset-0 bg-background/70" aria-hidden />
      {!still && (
        <button
          type="button"
          onClick={() => setPaused((value) => !value)}
          aria-pressed={paused}
          aria-label={paused ? "Play the background video" : "Pause the background video"}
          className="absolute right-3 bottom-3 z-10 flex size-9 items-center justify-center rounded-full bg-background/80 text-foreground shadow focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
          data-bga-video-pause
        >
          {paused ? (
            <svg viewBox="0 0 24 24" aria-hidden className="ml-0.5 size-4 fill-current">
              <path d="M8 5v14l11-7z" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden className="size-4 fill-current">
              <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
            </svg>
          )}
        </button>
      )}
      {credit && (
        <span className="absolute bottom-3 left-3 z-10 max-w-[70%] truncate rounded bg-black/55 px-1.5 py-0.5 text-[10px] leading-4 text-white" data-bga-video-credit>
          Video by{" "}
          <a href={credit.profileUrl ?? credit.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
            {credit.name}
          </a>{" "}
          on{" "}
          <a href={credit.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
            Pixabay
          </a>
        </span>
      )}
    </div>
  );
}
