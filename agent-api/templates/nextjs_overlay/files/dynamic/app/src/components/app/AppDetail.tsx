"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { app, fieldLabel, recordTitle, resolveParams, type TAppSection, type TRecord, type TRouteParams } from "./app";
import { useOperationMutation, useOperationQuery } from "./bindings";
import { designRegistry } from "./design-registry";
import { RecordDetail } from "./details";
import { LoadError } from "./AppList";
import { entityDesign, useLayout } from "./layout";
import { ActionButtons } from "./RecordActions";
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

/** One record (Story 22.4): its name as the page heading, its actions (only those it allows), its fields; the
 *  layout's detail-view plugin arranges them (Epic 30: `design-registry.ts`); `variant: "summary"` shows a custom
 *  operation's figures instead. */
/** Epic 32 (Story 32.5): the section's `onOpen` operation, called once per record when it has loaded (a view counted);
 *  a failure is silent, as a view that was not counted is no error for the person looking. */
function useOnOpen(section: TAppSection, route: TRouteParams, record: TRecord | undefined) {
  const onOpen = section.content?.onOpen;
  const mutation = useOperationMutation(onOpen?.operationId);
  const done = useRef<string | null>(null);
  const id = record ? String(record.id ?? "") : "";
  useEffect(() => {
    if (!onOpen || !id || done.current === id) return;
    done.current = id;
    mutation.mutate({ params: resolveParams(onOpen.params, route, record), body: resolveParams(onOpen.body, route, record) });
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
}

export function AppDetail({ section }: { section: TAppSection }) {
  const route = (useParams() ?? {}) as TRouteParams;
  const entity = app.entities[section.content?.entity ?? ""];
  const query = useOperationQuery(section.data?.operationId, resolveParams(section.data?.params, route));
  const record = query.data as TRecord | undefined;
  useOnOpen(section, route, record);
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
  const Detail = designRegistry.detailViews[design.detailView ?? ""] ?? RecordDetail;
  return (
    <Detail
      section={section}
      entity={entity}
      record={record}
      design={design}
      fields={fields}
      title={recordTitle(entity, record)}
      actions={<ActionButtons actions={section.content?.actions ?? []} record={record} />}
    />
  );
}
