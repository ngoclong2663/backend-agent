"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ListMusic, Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { listen, setPlaying as setBarPlaying, useListening } from "./listening";
import { formatDuration } from "./subtitles";

type AudioPlayerProps = {
  src: string;
  title: string;
  /** Lists and cards (Story 29.4): one play button; the file plays in the listening bar, one at a time. */
  compact?: boolean;
  className?: string;
  duration?: number | null;
  /** The record's page, so the bar can link back to it. */
  href?: string | null;
};

/** The native `<audio>` (Epic 29 D4): the full controls in a record, with "Keep playing" to hand the file to the
 *  listening bar; in lists a compact play / pause that uses the bar. Never autoplays. An expired read URL (D8) asks
 *  the record's queries again once and resumes at the same time. */
export function AudioPlayer({ src, title, compact = false, className, duration, href }: AudioPlayerProps) {
  const queryClient = useQueryClient();
  const audio = useRef<HTMLAudioElement>(null);
  const resumeAt = useRef<number | null>(null);
  const retried = useRef(false);
  const [length, setLength] = useState<number | null>(duration ?? null);
  const bar = useListening();
  const inBar = bar.current?.src === src;

  useEffect(() => {
    const element = audio.current;
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
    const element = audio.current;
    if (!element || retried.current) return;
    retried.current = true;
    resumeAt.current = element.currentTime || 0;
    void queryClient.invalidateQueries();
  }

  if (compact) {
    const playing = inBar && bar.playing;
    return (
      <span className={cn("inline-flex items-center gap-2", className)} data-bga-media="audio">
        <Button
          type="button"
          size="icon-sm"
          variant={inBar ? "default" : "outline"}
          aria-label={playing ? `Pause ${title}` : `Play ${title}`}
          aria-pressed={playing}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            if (inBar) setBarPlaying(!bar.playing);
            else listen({ src, title, href });
          }}
        >
          {playing ? <Pause aria-hidden /> : <Play aria-hidden className="ml-0.5" />}
        </Button>
        {length ? <span className="text-xs tabular-nums text-muted-foreground">{formatDuration(length)}</span> : null}
      </span>
    );
  }
  return (
    <div className={cn("flex flex-col gap-2", className)} data-bga-media="audio">
      <audio
        ref={audio}
        key={src}
        src={src}
        controls
        preload="metadata"
        className="w-full"
        title={title}
        onError={onError}
        onPlay={() => {
          if (inBar) setBarPlaying(false); // one thing plays at a time
        }}
        onLoadedMetadata={(event) => setLength(event.currentTarget.duration)}
      />
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="tabular-nums">{formatDuration(length)}</span>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => {
            const element = audio.current;
            element?.pause();
            listen({ src, title, href });
          }}
          data-bga-listen
        >
          <ListMusic data-icon="inline-start" aria-hidden />
          Keep playing
        </Button>
      </div>
    </div>
  );
}
