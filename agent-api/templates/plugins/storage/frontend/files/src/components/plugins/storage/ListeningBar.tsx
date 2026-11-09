"use client";

import { Pause, Play, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { TListeningBar } from "@/components/app/plugin-types";
import { setPlaying, stopListening, useListening } from "./listening";
import { formatDuration } from "./subtitles";

/** Story 29.4: the bar that keeps the current audio playing across pages (above the bottom tabs on phones, at the
 *  page's bottom otherwise): the title (linked to its record), play / pause, a seek bar, close. The one `<audio>`
 *  element of the app's compact players lives here. */
export const ListeningBar: TListeningBar = ({ bottomTabs }) => {
  const { current, playing } = useListening();
  const audio = useRef<HTMLAudioElement>(null);
  const [time, setTime] = useState(0);
  const [length, setLength] = useState(0);

  useEffect(() => {
    const element = audio.current;
    if (!element || !current) return;
    if (playing) void element.play().catch(() => setPlaying(false));
    else element.pause();
  }, [current, playing]);

  if (!current) return null;
  return (
    <div
      className={`fixed inset-x-0 z-30 border-t bg-background/95 backdrop-blur ${bottomTabs ? "bottom-[calc(3.5rem+env(safe-area-inset-bottom))] md:bottom-0" : "bottom-0"}`}
      role="region"
      aria-label="Now playing"
      data-bga-listening-bar
    >
      <audio
        ref={audio}
        key={current.src}
        src={current.src}
        preload="metadata"
        onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)}
        onLoadedMetadata={(event) => setLength(event.currentTarget.duration)}
        onEnded={() => setPlaying(false)}
        onError={() => setPlaying(false)}
      />
      <div className="mx-auto flex w-full max-w-screen-2xl items-center gap-3 px-4 py-2 sm:px-6">
        <Button type="button" size="icon-sm" variant="default" aria-label={playing ? "Pause" : "Play"} onClick={() => setPlaying(!playing)}>
          {playing ? <Pause aria-hidden /> : <Play aria-hidden className="ml-0.5" />}
        </Button>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {current.href ? (
            <Link href={current.href} className="truncate text-sm font-medium underline-offset-4 hover:underline">
              {current.title}
            </Link>
          ) : (
            <span className="truncate text-sm font-medium">{current.title}</span>
          )}
          <div className="flex items-center gap-2 text-xs tabular-nums text-muted-foreground">
            <span>{formatDuration(time)}</span>
            <input
              type="range"
              min={0}
              max={length || 0}
              step={1}
              value={Math.min(time, length || 0)}
              aria-label="Seek"
              className="h-1 flex-1 accent-primary"
              onChange={(event) => {
                const next = Number(event.target.value);
                if (audio.current) audio.current.currentTime = next;
                setTime(next);
              }}
            />
            <span>{formatDuration(length)}</span>
          </div>
        </div>
        <Button type="button" size="icon-sm" variant="ghost" aria-label="Close the player" onClick={stopListening}>
          <X aria-hidden />
        </Button>
      </div>
    </div>
  );
};
