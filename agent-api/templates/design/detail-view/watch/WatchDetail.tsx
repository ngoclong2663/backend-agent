"use client";

// Detail-view plugin `watch` (Epic 30, Story 30.5): the player at the top (left on wide screens), the title, meta and
// actions under it, and an "Up next" list of records of the same group (the shelves' group field), else the same
// parent, else the newest; one column on phones with the list below.
import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import { enumLabel, pageHref, resolveParams, type TRecord, listOf } from "@/components/app/app";
import { useOperationQuery } from "@/components/app/bindings";
import type { TDetailProps } from "@/components/app/design-types";
import { FieldGrid, audioFieldOf } from "@/components/app/details";
import { FileValue } from "@/components/app/plugins";
import { t } from "@/components/app/messages";
import { Media, Meta, durationText, mediaKind, plain, titleOf } from "@/components/app/views";

function UpNext({ props, exclude }: { props: TDetailProps; exclude: TRecord }) {
  const { entity, design } = props;
  const field = design.groupBy ?? Object.keys(entity?.references ?? {})[0];
  const params: Record<string, unknown> = { limit: 8 };
  const value = field ? exclude[field] : undefined;
  if (field && value !== undefined && value !== null) params[field] = typeof value === "object" ? (value as { id?: unknown }).id : value;
  const query = useOperationQuery(entity?.listOperation ?? undefined, params);
  const records = listOf(query.data).records.filter((record) => record.id !== exclude.id).slice(0, 6);
  const detail = entity?.detail ?? undefined;
  const heading = field && value !== null && value !== undefined ? `${t("upNext")} · ${enumLabel(plain(entity, exclude, field))}` : t("upNext");
  return (
    <aside className="flex flex-col gap-3" aria-label={t("upNext")} data-bga-up-next>
      <h2 className="text-sm font-semibold text-muted-foreground">{heading}</h2>
      {query.isLoading && <Skeleton className="h-40 w-full" />}
      <ul className="flex flex-col gap-3">
        {records.map((record) => {
          const title = titleOf(entity, record, design.roles);
          const href = detail ? pageHref(detail, resolveParams({ id: "$record.id" }, {}, record), {}) : undefined;
          const duration = durationText(entity, record, design.roles);
          return (
            <li key={String(record.id)} className="flex gap-3">
              <div className="relative w-36 shrink-0 overflow-hidden rounded-md">
                <Media entity={entity} record={record} field={design.roles.media} title={title} className="aspect-video w-full" />
                {duration && <span className="absolute right-1 bottom-1 rounded bg-black/70 px-1 text-[10px] tabular-nums text-white">{duration}</span>}
              </div>
              <div className="flex min-w-0 flex-col gap-0.5">
                <h3 className="line-clamp-2 text-sm font-medium leading-snug">
                  {href ? (
                    <Link href={href} className="underline-offset-4 hover:underline">
                      {title}
                    </Link>
                  ) : (
                    title
                  )}
                </h3>
                <Meta entity={entity} record={record} roles={design.roles} />
              </div>
            </li>
          );
        })}
      </ul>
      {!query.isLoading && records.length === 0 && <p className="text-sm text-muted-foreground">{t("nothingHere")}</p>}
    </aside>
  );
}

export function WatchDetail(props: TDetailProps) {
  const { section, entity, record, design, fields, title, actions } = props;
  const media = design.roles.media;
  const kind = mediaKind(entity, media);
  const audioField = audioFieldOf(entity, media);
  const shown = fields.filter((field) => field !== media && field !== audioField && field !== design.roles.title);
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(16rem,1fr)] lg:items-start" data-bga-detail="watch">
      <div className="flex min-w-0 flex-col gap-5">
        {media && kind && (
          <div className="overflow-hidden rounded-xl bg-black" data-bga-detail-media={kind}>
            <FileValue entity={entity} field={media} record={record} />
          </div>
        )}
        {media && !kind && <Media entity={entity} record={record} field={media} title={title} className="aspect-video w-full rounded-xl" />}
        {!media && audioField && (
          <div data-bga-detail-media="audio">
            <FileValue entity={entity} field={audioField} record={record} />
          </div>
        )}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <p className="text-sm text-muted-foreground">{section.content?.title ?? entity?.label}</p>
            <h1 className="text-2xl font-semibold tracking-tight break-words">{title}</h1>
            <Meta entity={entity} record={record} roles={design.roles} />
          </div>
          {actions}
        </div>
        <FieldGrid entity={entity} record={record} fields={shown} />
      </div>
      <UpNext props={props} exclude={record} />
    </div>
  );
}
