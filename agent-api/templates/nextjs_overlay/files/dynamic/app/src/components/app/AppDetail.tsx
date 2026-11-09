"use client";

import { useParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { app, fieldLabel, recordTitle, resolveParams, type TAppSection, type TRecord, type TRouteParams } from "./app";
import { useOperationQuery } from "./bindings";
import { FieldValue } from "./FieldValue";
import { LoadError } from "./AppList";
import { entityDesign, useLayout } from "./layout";
import { ActionButtons } from "./RecordActions";
import { FileValue } from "./plugins";
import { Media, mediaKind } from "./views";
import { t } from "./messages";

function SummaryValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <span className="text-muted-foreground">—</span>;
  if (typeof value === "number") return <span className="tabular-nums">{new Intl.NumberFormat().format(value)}</span>;
  if (typeof value === "boolean") return <span>{value ? t("yes") : t("no")}</span>;
  if (typeof value === "object") return <span className="text-muted-foreground">…</span>;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}(T|$)/.test(value)) {
    const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
    if (!Number.isNaN(date.getTime())) {
      const style = value.length === 10 ? { dateStyle: "medium" as const } : { dateStyle: "medium" as const, timeStyle: "short" as const };
      return <time dateTime={value}>{new Intl.DateTimeFormat(app.locale, style).format(date)}</time>;
    }
  }
  return <span>{String(value)}</span>;
}

/** A record's own summary (`deck.stats`): its response's values as figures. */
function Summary({ section, record }: { section: TAppSection; record: TRecord }) {
  const entries = Object.entries(record).filter(([key]) => key !== "id" && key !== "allowedActions");
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{section.content?.title}</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {entries.map(([key, value]) => (
            <div key={key} className="flex flex-col gap-1">
              <dt className="text-xs text-muted-foreground">{fieldLabel(undefined, key)}</dt>
              <dd className="text-lg font-semibold">
                <SummaryValue value={value} />
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

/** One record (Story 22.4): its name as the page heading, its actions (only those it allows), its fields in a
 *  description grid; `variant: "summary"` shows a custom operation's figures instead. */
export function AppDetail({ section }: { section: TAppSection }) {
  const route = (useParams() ?? {}) as TRouteParams;
  const entity = app.entities[section.content?.entity ?? ""];
  const query = useOperationQuery(section.data?.operationId, resolveParams(section.data?.params, route));
  const record = query.data as TRecord | undefined;
  const summary = section.content?.variant === "summary";
  const design = entityDesign(useLayout(), section.content?.entity);

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (query.error || !record) return <LoadError onRetry={() => query.refetch()} />;
  if (summary) return <Summary section={section} record={record} />;

  const fields = section.data?.fields?.length ? section.data.fields : (entity?.detailFields ?? []);
  const title = recordTitle(entity, record);
  // Epic 23 (Story 23.3): a media record opens on its image, a profile on its picture beside the name; Epic 29: a
  // video opens on its player, an audio record's player sits under the title
  const media = design.detailView === "media" ? design.roles.media : undefined;
  const picture = design.detailView === "profile" ? (design.roles.avatar ?? design.roles.media) : undefined;
  const kind = mediaKind(entity, media);
  const audioField = kind === "audio" ? media : Object.keys(entity?.fields ?? {}).find((name) => entity?.fields?.[name]?.type === "audio");
  const shown = fields.filter((field) => field !== media && field !== picture && field !== audioField);
  return (
    <div className="flex flex-col gap-6">
      {media && kind === "video" && (
        <div data-bga-detail-media="video">
          <FileValue entity={entity} field={media} record={record} />
        </div>
      )}
      {media && !kind && <Media entity={entity} record={record} field={media} title={title} className="aspect-[21/9] w-full rounded-xl" />}
      <div className="flex flex-wrap items-start justify-between gap-3">
        {picture && <Media entity={entity} record={record} field={picture} title={title} className="size-20 shrink-0 rounded-full" />}
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-sm text-muted-foreground">{section.content?.title ?? entity?.label}</p>
          <h1 className="text-2xl font-semibold tracking-tight break-words">{title}</h1>
        </div>
        <ActionButtons actions={section.content?.actions ?? []} record={record} />
      </div>
      {audioField && (
        <div data-bga-detail-media="audio">
          <FileValue entity={entity} field={audioField} record={record} />
        </div>
      )}
      <Card>
        <CardContent>
          <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
            {shown
              .filter((field) => field !== entity?.displayField)
              .map((field) => (
                <div key={field} className="flex min-w-0 flex-col gap-1">
                  <dt className="text-sm text-muted-foreground">{fieldLabel(entity, field)}</dt>
                  <dd className="min-w-0 break-words">
                    <FieldValue entity={entity} field={field} record={record} />
                  </dd>
                </div>
              ))}
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}
