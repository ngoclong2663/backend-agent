"use client";

import { Captions, FileText } from "lucide-react";
import { useState } from "react";
import { app, listOf, pageHref, photoCredit, recordTitle, type TAppEntity, type TRecord } from "@/components/app/app";
import { useOperationQuery } from "@/components/app/bindings";
import { PhotoCredit } from "@/components/app/PhotoCredit";
import type { TFileValue } from "@/components/app/plugin-types";
import { AudioPlayer } from "./AudioPlayer";
import type { TTrack } from "./subtitles";
import { VideoPlayer } from "./VideoPlayer";

/** The first image field of the record with a URL: a video's poster (Story 29.4). */
export function posterOf(entity: TAppEntity | undefined, record: TRecord): string | null {
  for (const [name, spec] of Object.entries(entity?.fields ?? {})) {
    if (spec.type === "image" && spec.urlField && typeof record[spec.urlField] === "string" && record[spec.urlField]) {
      return record[spec.urlField] as string;
    }
  }
  return null;
}

/** A duration for the record: its `duration`-like number field (seconds, or minutes when the name says so). */
export function durationOf(entity: TAppEntity | undefined, record: TRecord): number | null {
  for (const [name, spec] of Object.entries(entity?.fields ?? {})) {
    if (!["integer", "number"].includes(spec.type)) continue;
    const lower = name.toLowerCase();
    if (!/duration|length|runtime/.test(lower)) continue;
    const value = record[name];
    if (typeof value !== "number") continue;
    return /min/.test(lower) ? value * 60 : value;
  }
  return null;
}

/** The subtitle tracks of a media field (Epic 29 D3): the record's own `subtitles` fields, and the child records of
 *  a track entity (one per language), read through the child's list filtered by the parent. */
export function useTracks(entity: TAppEntity | undefined, field: string, record: TRecord): TTrack[] {
  const specs = entity?.tracks?.[field] ?? [];
  const child = specs.find((track) => track.shape === "child" && track.listOperation);
  const params = child ? { [child.parent ?? "parentId"]: record.id, limit: 50 } : {};
  const query = useOperationQuery(child?.listOperation ?? undefined, params);
  const tracks: TTrack[] = [];
  for (const track of specs) {
    if (track.shape === "field") {
      const url = record[`${track.field}Url`];
      if (typeof url === "string" && url) tracks.push({ src: url, language: app.locale, label: null });
    }
  }
  if (child) {
    for (const row of listOf(query.data).records) {
      const url = row[`${child.field}Url`];
      if (typeof url !== "string" || !url) continue;
      const language = child.language ? (row[child.language] as string | undefined) : undefined;
      const label = child.label ? (row[child.label] as string | undefined) : undefined;
      tracks.push({ src: url, language: language ?? null, label: label ?? null });
    }
  }
  return tracks;
}

type MediaFileProps = { entity: TAppEntity | undefined; field: string; record: TRecord; compact?: boolean; fill?: boolean; url: string };

function MediaFile({ entity, field, record, compact, fill, url }: MediaFileProps) {
  const tracks = useTracks(entity, field, record);
  const spec = entity?.fields?.[field];
  const title = recordTitle(entity, record);
  const href = entity?.detail && record.id !== undefined ? pageHref(entity.detail, { id: record.id }) : null;
  if (spec?.type === "audio") {
    // a card shows the duration role itself; the compact button in a cell shows the file's length
    return <AudioPlayer src={url} title={title} compact={compact} duration={fill ? null : durationOf(entity, record)} href={href} className={compact ? undefined : "max-w-xl"} />;
  }
  return (
    <VideoPlayer
      src={url}
      poster={posterOf(entity, record)}
      tracks={tracks}
      title={title}
      compact={compact}
      duration={durationOf(entity, record)}
      className={fill ? "size-full rounded-none" : compact ? "aspect-video h-10 w-16" : "aspect-video max-w-2xl"}
    />
  );
}

/** A file, image or media field in a list or a record (Story 22.7, Epic 29): through its signed read URL
 *  (`<field>Url`). An image that does not load (a seeded outside link that went away) shows the empty value, not a
 *  broken image; a video or an audio file plays in the kit's native players; a subtitle file shows its language and
 *  a download link. */
export const FileValue: TFileValue = ({ entity, field, record, compact, fill }) => {
  const spec = entity?.fields?.[field];
  const url = spec?.urlField ? record[spec.urlField] : undefined;
  const [failed, setFailed] = useState(false);
  if (typeof url !== "string" || !url || (failed && spec?.type === "image")) {
    return <span className="text-muted-foreground">—</span>;
  }
  if (spec?.type === "video" || spec?.type === "audio") {
    return <MediaFile entity={entity} field={field} record={record} compact={compact} fill={fill} url={url} />;
  }
  if (spec?.type === "subtitles") {
    const language = ["language", "lang", "locale"].map((name) => record[name]).find((value) => typeof value === "string") as string | undefined;
    return (
      <a href={url} className="inline-flex items-center gap-1.5 font-medium underline-offset-4 hover:underline" download data-bga-media="subtitles">
        <Captions aria-hidden className="size-4" />
        <span className="truncate">{language ? language.toUpperCase() : String(record[field] ?? "").split("/").pop()}</span>
      </a>
    );
  }
  if (spec?.type === "image") {
    const credit = photoCredit(url);
    if (credit) {
      return (
        <span className={compact ? "relative inline-block h-10 w-14" : "relative inline-block aspect-video max-h-56 w-full max-w-sm"}>
          {/* eslint-disable-next-line @next/next/no-img-element -- a seeded stock photo, hotlinked as its service asks */}
          <img
            src={url}
            alt=""
            title={compact ? `Photo by ${credit.name} on Unsplash` : undefined}
            className="size-full rounded-lg border object-cover"
            loading="lazy"
            onError={() => setFailed(true)}
          />
          {!compact && <PhotoCredit credit={credit} />}
        </span>
      );
    }
    return (
      // eslint-disable-next-line @next/next/no-img-element -- a signed URL from the API, not a static asset
      <img
        src={url}
        alt=""
        className={compact ? "h-10 w-14 rounded-md border object-cover" : "aspect-video max-h-56 w-full max-w-sm rounded-lg border object-cover"}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    );
  }
  const name = String(record[field] ?? "").split("/").pop() || "Download";
  return (
    <a href={url} className="inline-flex items-center gap-1.5 font-medium underline-offset-4 hover:underline" download>
      <FileText aria-hidden className="size-4" />
      <span className="truncate">{name}</span>
    </a>
  );
};
