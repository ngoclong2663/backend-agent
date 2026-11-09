"use client";

// Epic 23: the ways a list's records are shown (Stories 23.3–23.5). Every view presents the same AppList section:
// the same operation, parameters, row actions and `allowedActions`; only the presentation changes.
import { CalendarDays, ChevronLeft, ChevronRight, Inbox } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import {
  app,
  enumLabel,
  fieldLabel,
  listOf,
  pageHref,
  photoCredit,
  recordTitle,
  resolveParams,
  type TAppAction,
  type TAppEntity,
  type TAppSection,
  type TCardAspect,
  type TEntityDesign,
  type TFieldRoles,
  type TRecord,
  type TRouteParams,
} from "./app";
import { useOperationQuery } from "./bindings";
import { designRegistry } from "./design-registry";
import type { TCardProps, TViewProps } from "./design-types";
import { PhotoCredit } from "./PhotoCredit";
import { FieldValue } from "./FieldValue";
import { FileValue } from "./plugins";
import { RowActions } from "./RecordActions";
import { slots } from "./slots";
import { inSentence, t } from "./messages";

export type { TViewProps } from "./design-types";

const dateFormat = new Intl.DateTimeFormat(app.locale, { weekday: "long", day: "numeric", month: "long" });
const monthFormat = new Intl.DateTimeFormat(app.locale, { month: "long", year: "numeric" });
const timeFormat = new Intl.DateTimeFormat(app.locale, { hour: "numeric", minute: "2-digit" });
const weekdays = Array.from({ length: 7 }, (_, i) =>
  new Intl.DateTimeFormat(app.locale, { weekday: "short" }).format(new Date(2024, 0, 1 + i)),
); // 2024-01-01 is a Monday

/** Story 30.4: a card's media aspect (the entity design's, else the view's own default). Static class names: Tailwind
 *  only ships what it can read. */
const ASPECT_CLASS: Record<TCardAspect, string> = {
  wide: "aspect-video",
  portrait: "aspect-[2/3]",
  square: "aspect-square",
  auto: "aspect-video",
};
export function aspectClass(design: TEntityDesign, fallback: TCardAspect = "wide"): string {
  return ASPECT_CLASS[design.aspect ?? fallback];
}

/** Story 30.4: the grid's columns on wide screens (the entity design's, else the view's own). */
const GRID_COLUMNS: Record<number, string> = {
  2: "sm:grid-cols-2",
  3: "sm:grid-cols-2 lg:grid-cols-3",
  4: "sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4",
  5: "sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5",
  6: "grid-cols-2 md:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6",
};
export function gridColumns(design: TEntityDesign, fallback: number): string {
  const wanted = design.columns ?? designRegistry.cardColumns[design.card ?? ""] ?? fallback;
  return GRID_COLUMNS[wanted] ?? GRID_COLUMNS[fallback];
}

/** Story 30.4: one record drawn by the entity's card plugin (`design-registry.ts`), or null for the view's own card. */
export function CardOf({ design, ...props }: Omit<TCardProps, "design"> & { design: TEntityDesign }) {
  const Plugin = designRegistry.cards[design.card ?? ""];
  return Plugin ? <Plugin design={design} {...props} /> : null;
}

export function viewHref(actions: TAppAction[], record: TRecord, route: TRouteParams): string | undefined {
  const view = actions.find((action) => action.id === "view" && action.page);
  return view?.page ? pageHref(view.page, resolveParams(view.params, route, record), route) : undefined;
}

function hue(value: unknown): number {
  let hash = 0;
  for (const char of String(value)) hash = (hash * 31 + char.charCodeAt(0)) % 360;
  return hash;
}

export function imageUrl(entity: TAppEntity | undefined, record: TRecord, field: string | undefined): string | null {
  if (!field) return null;
  const urlField = entity?.fields?.[field]?.urlField;
  const value = (urlField ? record[urlField] : null) ?? record[field];
  return typeof value === "string" && /^(https?:|data:|blob:|\/)/.test(value) ? value : null;
}

/** Epic 29: `m:ss` of a record's duration role (seconds, or minutes when the field's name says so). */
export function durationText(entity: TAppEntity | undefined, record: TRecord, roles: TFieldRoles): string {
  const field = roles.duration;
  if (!field) return "";
  const kind = entity?.fields?.[field]?.type;
  if (kind === "video" || kind === "audio") return ""; // the player reads the file's own length
  const value = record[field];
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  const seconds = /min/i.test(field) ? value * 60 : value;
  const whole = Math.max(0, Math.round(seconds));
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const sec = whole % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

/** Epic 29: whether the media role is a video or an audio field (shown through the kit's players, not as an image). */
export function mediaKind(entity: TAppEntity | undefined, field: string | undefined): "video" | "audio" | null {
  const kind = field ? entity?.fields?.[field]?.type : undefined;
  return kind === "video" || kind === "audio" ? kind : null;
}

/** A record's image, or a placeholder in the title's colour with its initial (never a broken image). A video field
 *  (Epic 29) shows its poster with a play badge and plays in place; an audio field a compact play button. */
export function Media({ entity, record, field, title, className }: { entity?: TAppEntity; record: TRecord; field?: string; title: string; className?: string }) {
  const url = imageUrl(entity, record, field);
  const [failed, setFailed] = useState(false);
  const kind = mediaKind(entity, field);
  if (kind === "video" && field) {
    return (
      <div className={cn("relative overflow-hidden", className)} data-bga-media-card="video">
        <FileValue entity={entity} field={field} record={record} compact fill />
      </div>
    );
  }
  if (kind === "audio" && field) {
    return (
      <div className={cn("relative flex items-center justify-center bg-muted", className)} data-bga-media-card="audio">
        <FileValue entity={entity} field={field} record={record} compact fill />
      </div>
    );
  }
  if (url && !failed) {
    const credit = photoCredit(url);
    if (credit) {
      return (
        <div className={cn("relative overflow-hidden", className)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={url} alt="" loading="lazy" className="size-full object-cover" onError={() => setFailed(true)} />
          <PhotoCredit credit={credit} />
        </div>
      );
    }
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt="" loading="lazy" className={cn("object-cover", className)} onError={() => setFailed(true)} />;
  }
  const h = hue(title);
  return (
    <div
      aria-hidden
      data-bga-placeholder
      className={cn("relative overflow-hidden", className)}
      style={{
        background: `radial-gradient(120% 90% at 0% 0%, oklch(0.78 0.13 ${h}), transparent 60%), radial-gradient(120% 90% at 100% 100%, oklch(0.55 0.16 ${(h + 70) % 360}), transparent 65%), oklch(0.66 0.12 ${(h + 35) % 360})`,
      }}
    >
      <span className="absolute -right-2 -bottom-6 font-heading text-[7rem] leading-none font-bold text-white/25 select-none">
        {title.trim().slice(0, 1).toUpperCase()}
      </span>
    </div>
  );
}

export function Avatar({ entity, record, field, label }: { entity?: TAppEntity; record: TRecord; field?: string; label: string }) {
  const url = imageUrl(entity, record, field);
  if (url) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt="" className="size-8 shrink-0 rounded-full object-cover" />;
  }
  return (
    <span
      aria-hidden
      className="flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
      style={{ background: `oklch(0.58 0.13 ${hue(label)})` }}
    >
      {label.trim().slice(0, 1).toUpperCase()}
    </span>
  );
}

/** A field as plain text: a parent by its name, an enum by its label (for badges, headers and colours). */
export function plain(entity: TAppEntity | undefined, record: TRecord, field: string | undefined): string {
  if (!field) return "";
  const reference = entity?.references?.[field];
  if (reference) {
    const summary = record[reference.summary] as { label?: unknown } | null | undefined;
    return summary?.label ? String(summary.label) : "";
  }
  const value = record[field];
  if (value === null || value === undefined) return "";
  return entity?.fields?.[field]?.type === "enum" ? enumLabel(String(value)) : String(value);
}

export function titleOf(entity: TAppEntity | undefined, record: TRecord, roles: TFieldRoles): string {
  return (roles.title && plain(entity, record, roles.title)) || recordTitle(entity, record);
}

export function Meta({ entity, record, roles, skip }: { entity?: TAppEntity; record: TRecord; roles: TFieldRoles; skip?: string }) {
  const fields = (roles.meta ?? []).filter((f) => f !== skip && record[f] !== null && record[f] !== undefined && record[f] !== "");
  if (fields.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 text-sm text-muted-foreground">
      {fields.map((field, index) => (
        <span key={field} className="flex items-center gap-1.5">
          {index > 0 && <span aria-hidden>·</span>}
          <FieldValue entity={entity} field={field} record={record} link={false} />
        </span>
      ))}
    </div>
  );
}

export function Figure({ entity, record, field }: { entity?: TAppEntity; record: TRecord; field?: string }) {
  if (!field || record[field] === null || record[field] === undefined) return null;
  return (
    <span className="text-sm font-medium tabular-nums">
      <FieldValue entity={entity} field={field} record={record} link={false} />{" "}
      <span className="font-normal text-muted-foreground">{(entity?.fieldLabels?.[field] ?? field).toLowerCase()}</span>
    </span>
  );
}

export function Title({ href, title, className }: { href?: string; title: string; className?: string }) {
  return (
    <h3 className={cn("font-semibold leading-snug", className)}>
      {href ? (
        <Link href={href} className="underline-offset-4 hover:underline focus-visible:underline">
          {title}
        </Link>
      ) : (
        title
      )}
    </h3>
  );
}

/** Pictures first (videos, courses, products): the image, its badge, the title and a meta line. */
export function MediaGrid({ section, entity, records, design }: TViewProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  const roles = design.roles;
  const plugin = Boolean(designRegistry.cards[design.card ?? ""]);
  return (
    <ul className={cn("grid gap-x-5 gap-y-8", gridColumns(design, 4))} data-bga-view="media-grid">
      {records.map((record) => {
        const title = titleOf(entity, record, roles);
        const href = viewHref(actions, record, route);
        const badge = plain(entity, record, roles.badge);
        const subtitle = plain(entity, record, roles.subtitle);
        if (plugin) {
          return (
            <li key={String(record.id)}>
              <CardOf design={design} entity={entity} record={record} roles={roles} title={title} href={href} actions={actions} boxed={false} size="md" />
            </li>
          );
        }
        return (
          <li key={String(record.id)} className="group flex flex-col gap-3">
            <Card className="relative gap-0 overflow-hidden p-0" data-bga-media>
              <Media entity={entity} record={record} field={roles.media} title={title} className="aspect-video w-full transition-transform duration-300 group-hover:scale-[1.02] motion-reduce:transition-none" />
              {badge && (
                <Badge className="absolute top-2 left-2" variant="secondary">
                  {badge}
                </Badge>
              )}
              {durationText(entity, record, roles) && (
                <span className="absolute right-2 bottom-2 rounded bg-black/70 px-1.5 py-0.5 text-xs tabular-nums text-white" data-bga-duration>
                  {durationText(entity, record, roles)}
                </span>
              )}
              {href && !mediaKind(entity, roles.media) && <Link href={href} className="absolute inset-0" aria-label={title} tabIndex={-1} />}
            </Card>
            <div className="flex gap-3">
              {roles.avatar && <Avatar entity={entity} record={record} field={roles.avatar} label={subtitle || title} />}
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <Title href={href} title={title} className="line-clamp-2" />
                {subtitle && <p className="truncate text-sm text-muted-foreground">{subtitle}</p>}
                <Meta entity={entity} record={record} roles={roles} />
                <Figure entity={entity} record={record} field={roles.price ?? roles.stat} />
              </div>
              <RowActions actions={actions} record={record} label={title} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** One after another, newest first (posts, updates): who it is from, the title, a summary, the image, a figure. */
export function Feed({ section, entity, records, design }: TViewProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  const roles = design.roles;
  return (
    <ul className="mx-auto flex w-full max-w-2xl flex-col gap-5" data-bga-view="feed">
      {records.map((record) => {
        const title = titleOf(entity, record, roles);
        const href = viewHref(actions, record, route);
        // who it is from: a parent named in a role (the source, the channel), else the subtitle
        const fromField = [roles.badge, roles.subtitle, roles.avatar].find((f) => f && entity?.references?.[f]);
        const from = plain(entity, record, fromField) || plain(entity, record, roles.subtitle);
        const summary = fromField === roles.subtitle || !roles.subtitle ? "" : plain(entity, record, roles.subtitle);
        const badge = roles.badge === fromField ? "" : plain(entity, record, roles.badge);
        return (
          <li key={String(record.id)}>
            <Card className="gap-3 p-5" data-bga-feed-item>
              <div className="flex items-center gap-3">
                <Avatar entity={entity} record={record} field={fromField ? undefined : roles.avatar} label={from || title} />
                <div className="min-w-0 flex-1">
                  {from && from !== summary && <p className="truncate text-sm font-semibold">{from}</p>}
                  <Meta entity={entity} record={record} roles={roles} />
                </div>
                <RowActions actions={actions} record={record} label={title} />
              </div>
              <Title href={href} title={title} className="text-lg" />
              {summary && <p className="line-clamp-2 text-sm text-muted-foreground">{summary}</p>}
              {roles.media && <Media entity={entity} record={record} field={roles.media} title={title} className="aspect-[2.4/1] w-full rounded-lg" />}
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-3">
                  <Figure entity={entity} record={record} field={roles.stat} />
                  {durationText(entity, record, roles) && <span className="text-xs tabular-nums text-muted-foreground" data-bga-duration>{durationText(entity, record, roles)}</span>}
                </span>
                {badge && <Badge variant="outline">{badge}</Badge>}
              </div>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}

/** The rows of a table (Story 22.4): the list's fields as columns, the first a link, the actions in a menu. */
export function TableRows({ section, entity, records }: TViewProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const router = useRouter();
  const fields = section.data?.fields ?? [];
  const actions = section.content?.actions ?? [];
  const compact = app.density === "compact";
  return (
    <div className="overflow-x-auto rounded-lg border" data-bga-view="table">
      <Table>
        <TableHeader>
          <TableRow>
            {fields.map((field) => (
              <TableHead key={field}>{fieldLabel(entity, field)}</TableHead>
            ))}
            {actions.length > 0 && <TableHead className="w-12 text-right"><span className="sr-only">Actions</span></TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {records.map((record) => {
            const href = viewHref(actions, record, route);
            return (
              <TableRow
                key={String(record.id)}
                className={cn(href && "cursor-pointer", compact && "[&_td]:py-1.5")}
                onClick={(event) => {
                  if (!href || (event.target as HTMLElement).closest("a,button,[role=menuitem]")) return;
                  router.push(href);
                }}
              >
                {fields.map((field, index) => (
                  <TableCell key={field} className={cn(index === 0 && "font-medium")}>
                    {index === 0 && href && !entity?.references?.[field] ? (
                      <Link href={href} className="underline-offset-4 hover:underline">
                        <FieldValue entity={entity} field={field} record={record} link={false} />
                      </Link>
                    ) : (
                      <FieldValue entity={entity} field={field} record={record} />
                    )}
                  </TableCell>
                ))}
                {actions.length > 0 && (
                  <TableCell className="text-right">
                    <RowActions actions={actions} record={record} label={recordTitle(entity, record)} />
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/** Plain cards (Story 22.4): the record's name and its list fields as a description list, for an entity without
 *  field roles (an outline's `listStyle: "cards"`). */
export function PlainCards({ section, entity, records }: TViewProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const fields = section.data?.fields ?? [];
  const actions = section.content?.actions ?? [];
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-bga-view="cards">
      {records.map((record) => {
        const href = viewHref(actions, record, route);
        const title = recordTitle(entity, record);
        return (
          <li key={String(record.id)}>
            <Card size="sm" className="h-full">
              <CardHeader className="flex flex-row items-start justify-between gap-2">
                <CardTitle className="min-w-0 truncate">
                  {href ? (
                    <Link href={href} className="underline-offset-4 hover:underline">
                      {title}
                    </Link>
                  ) : (
                    title
                  )}
                </CardTitle>
                <RowActions actions={actions} record={record} label={title} />
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                  {fields
                    .filter((field) => field !== entity?.displayField)
                    .map((field) => (
                      <div key={field} className="contents">
                        <dt className="text-muted-foreground">{fieldLabel(entity, field)}</dt>
                        <dd className="min-w-0 truncate">
                          <FieldValue entity={entity} field={field} record={record} />
                        </dd>
                      </div>
                    ))}
                </dl>
              </CardContent>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}

/** Cards laid out by role: an image on top when there is one, the title, a subtitle, the meta line, a badge and a
 *  price or a figure. */
export function RoleCards({ section, entity, records, design }: TViewProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  const roles = design.roles;
  if (!roles?.title && !roles?.media) return <PlainCards section={section} entity={entity} records={records} design={design} />;
  const plugin = Boolean(designRegistry.cards[design.card ?? ""]);
  return (
    <ul className={cn("grid gap-4", gridColumns(design, 3))} data-bga-view="cards">
      {records.map((record) => {
        const title = titleOf(entity, record, roles);
        const href = viewHref(actions, record, route);
        const badge = plain(entity, record, roles.badge);
        const subtitle = plain(entity, record, roles.subtitle);
        if (plugin) {
          return (
            <li key={String(record.id)}>
              <CardOf design={design} entity={entity} record={record} roles={roles} title={title} href={href} actions={actions} boxed size="md" />
            </li>
          );
        }
        return (
          <li key={String(record.id)}>
            <Card className="h-full gap-0 overflow-hidden p-0">
              {roles.media && <Media entity={entity} record={record} field={roles.media} title={title} className="aspect-video w-full" />}
              <div className="flex flex-1 flex-col gap-2 p-4">
                <div className="flex items-start justify-between gap-2">
                  <Title href={href} title={title} className="line-clamp-2" />
                  <RowActions actions={actions} record={record} label={title} />
                </div>
                {subtitle && <p className="line-clamp-2 text-sm text-muted-foreground">{subtitle}</p>}
                <Meta entity={entity} record={record} roles={roles} />
                <div className="mt-auto flex items-center justify-between gap-2 pt-2">
                  {badge ? <Badge variant="secondary">{badge}</Badge> : <span />}
                  <span className="flex items-center gap-3">
                    {durationText(entity, record, roles) && <span className="text-xs tabular-nums text-muted-foreground" data-bga-duration>{durationText(entity, record, roles)}</span>}
                    <Figure entity={entity} record={record} field={roles.price ?? roles.stat} />
                  </span>
                </div>
              </div>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}

export function CardBody({ entity, record, roles, href, actions, skip }: { entity?: TAppEntity; record: TRecord; roles: TFieldRoles; href?: string; actions: TAppAction[]; skip?: string }) {
  const title = titleOf(entity, record, roles);
  const subtitle = plain(entity, record, roles.subtitle);
  const badge = roles.badge === skip ? "" : plain(entity, record, roles.badge);
  return (
    <>
      <div className="flex items-start justify-between gap-2">
        <Title href={href} title={title} className="line-clamp-2 text-sm" />
        <RowActions actions={actions} record={record} label={title} />
      </div>
      <Meta entity={entity} record={record} roles={roles} skip={skip} />
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          {subtitle && (
            <>
              <Avatar entity={entity} record={record} label={subtitle} />
              <span className="truncate text-xs text-muted-foreground">{subtitle}</span>
            </>
          )}
        </span>
        {badge && <Badge variant="secondary">{badge}</Badge>}
      </div>
    </>
  );
}

/** Records in a column per status, in the flow's order (Story 23.4). A card moves through its menu: the record's
 *  transitions, offered only when its `allowedActions` allow them (the backend decides; a refusal shows its message). */
export function Board({ section, entity, records, design }: TViewProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  const field = design.groupBy ?? "status";
  const states = entity?.fields?.[field]?.values ?? [...new Set(records.map((r) => String(r[field])))];
  return (
    <div className="-mx-1 flex snap-x gap-4 overflow-x-auto px-1 pb-2" data-bga-view="board" role="list" aria-label={`${entity?.plural ?? "Records"} by ${field}`}>
      {states.map((state) => {
        const items = records.filter((record) => String(record[field]) === state);
        return (
          <section key={state} role="listitem" className="flex w-72 shrink-0 snap-start flex-col gap-3 rounded-xl bg-muted/60 p-3" data-bga-column={state}>
            <h3 className="flex items-center justify-between px-1 text-sm font-semibold">
              {enumLabel(state)}
              <span className="rounded-full bg-background px-2 text-xs tabular-nums text-muted-foreground">{items.length}</span>
            </h3>
            {items.map((record) => (
              <Card key={String(record.id)} className="gap-2 p-3">
                <CardBody entity={entity} record={record} roles={design.roles} actions={actions} href={viewHref(actions, record, route)} skip={field} />
              </Card>
            ))}
            {items.length === 0 && <p className="px-1 py-6 text-center text-xs text-muted-foreground">{t("nothingHere")}</p>}
          </section>
        );
      })}
    </div>
  );
}

function asDate(value: unknown): Date | null {
  if (typeof value !== "string") return null;
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
const dayKey = (date: Date) => `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
const iso = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

type TRange = { field: string; from: string; to: string };

/** The date range parameters of the list, for its date field (Story 23.4), when the contract has them. */
function rangeOf(section: TAppSection, field: string): TRange | undefined {
  const ranges = (section.content?.controls as { ranges?: TRange[] } | undefined)?.ranges;
  return ranges?.find((range) => range.field === field);
}

function EmptyDates({ title }: { title: string }) {
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Inbox aria-hidden />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{t("appearOnceAdded")}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

/** A month (wide screens) or the agenda (phones) of a list's records by their date (Story 23.4): the month comes
 *  from the address (`<section>.month`), else the month of the next record, else of the latest one; the list is
 *  asked for that month only, through its date range. */
export function Calendar({ section, entity, params, design, agenda = false }: { section: TAppSection; entity?: TAppEntity; params: Record<string, unknown>; design: TEntityDesign; agenda?: boolean }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const field = design.dateField ?? "";
  const range = rangeOf(section, field);
  const opId = section.data?.operationId;
  const limit = (section.content?.controls as { maxLimit?: number } | undefined)?.maxLimit ?? 100;
  const today = iso(new Date());
  const sortable = (section.content?.controls?.sort ?? []).includes(field);
  // where to open: the next record from today, else the latest
  const next = useOperationQuery(range && sortable ? opId : undefined, { ...params, [range?.from ?? ""]: today, sort: field, limit: 1, offset: 0 });
  const latest = useOperationQuery(range && sortable ? opId : undefined, { ...params, sort: `-${field}`, limit: 1, offset: 0 });
  const anchor = asDate(listOf(next.data).records[0]?.[field]) ?? asDate(listOf(latest.data).records[0]?.[field]) ?? new Date();
  const key = `${section.id}.month`;
  const chosen = searchParams?.get(key);
  const [year, month] = chosen && /^\d{4}-\d{2}$/.test(chosen) ? chosen.split("-").map(Number).map((n, i) => (i === 1 ? n - 1 : n)) : [anchor.getFullYear(), anchor.getMonth()];
  const first = new Date(year, month, 1);
  const start = new Date(year, month, 1 - ((first.getDay() + 6) % 7));
  const days = Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  const bounds = range ? { [range.from]: iso(days[0]), [range.to]: iso(days[41]) } : {};
  const waiting = Boolean(range && sortable && !chosen && (next.isLoading || latest.isLoading));
  const query = useOperationQuery(waiting ? undefined : opId, { ...params, ...bounds, ...(sortable ? { sort: field } : {}), limit, offset: 0 });
  const records = listOf(query.data).records;
  const dated = records
    .map((record) => ({ record, date: asDate(record[field]) }))
    .filter((x): x is { record: TRecord; date: Date } => x.date !== null);
  const byDay = new Map<string, TRecord[]>();
  for (const { record, date } of dated) byDay.set(dayKey(date), [...(byDay.get(dayKey(date)) ?? []), record]);
  const timed = entity?.fields?.[field]?.type === "datetime";
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  function go(delta: number) {
    const target = new Date(year, month + delta, 1);
    const nextParams = new URLSearchParams(searchParams?.toString() ?? "");
    nextParams.set(key, `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}`);
    router.replace(`${pathname}?${nextParams.toString()}`, { scroll: false });
  }
  if (waiting || query.isLoading) return <Skeleton className="h-96 w-full" aria-busy="true" aria-label="Loading" />;
  const list = <Agenda section={section} entity={entity} records={dated.map((x) => x.record)} design={design} />;
  if (agenda) return dated.length ? list : <EmptyDates title={t("noneThisMonth", { name: inSentence(entity?.plural ?? t("records")) })} />;
  return (
    <>
      <div className="md:hidden">{dated.length ? list : <EmptyDates title={t("nothingIn", { month: monthFormat.format(first) })} />}</div>
      <Card className="hidden gap-0 overflow-hidden p-0 md:flex" data-bga-view="calendar">
        <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
          <h3 className="flex items-center gap-2 font-semibold">
            <CalendarDays className="size-4 text-muted-foreground" aria-hidden />
            {monthFormat.format(first)}
          </h3>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon-sm" onClick={() => go(-1)} aria-label={t("previousMonth")}>
              <ChevronLeft aria-hidden />
            </Button>
            <Button variant="outline" size="icon-sm" onClick={() => go(1)} aria-label={t("nextMonth")}>
              <ChevronRight aria-hidden />
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-7 border-b text-xs font-medium text-muted-foreground" aria-hidden>
          {weekdays.map((d) => (
            <div key={d} className="px-2 py-1.5">
              {d}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {days.map((day) => {
            const items = byDay.get(dayKey(day)) ?? [];
            const outside = day.getMonth() !== month;
            const isToday = iso(day) === today;
            return (
              <div key={day.toISOString()} className={cn("min-h-24 border-r border-b p-1.5 [&:nth-child(7n)]:border-r-0", outside && "bg-muted/40")}>
                <div className={cn("mb-1 flex size-6 items-center justify-center rounded-full text-xs tabular-nums", outside ? "text-muted-foreground/60" : "text-muted-foreground", isToday && "bg-primary text-primary-foreground")}>
                  {day.getDate()}
                </div>
                <div className="flex flex-col gap-1">
                  {items.slice(0, 3).map((record) => {
                    const title = titleOf(entity, record, design.roles);
                    const href = viewHref(actions, record, route);
                    const date = asDate(record[field]);
                    const chip = (
                      <span
                        className="block truncate rounded-md bg-primary/10 px-1.5 py-0.5 text-xs text-foreground"
                        style={{ borderLeft: `3px solid oklch(0.6 0.14 ${hue(plain(entity, record, design.roles.badge) || title)})` }}
                      >
                        {timed && date && <span className="mr-1 tabular-nums text-muted-foreground">{timeFormat.format(date)}</span>}
                        {title}
                      </span>
                    );
                    return href ? (
                      <Link key={String(record.id)} href={href} className="rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                        {chip}
                      </Link>
                    ) : (
                      <span key={String(record.id)}>{chip}</span>
                    );
                  })}
                  {items.length > 3 && <span className="px-1 text-xs text-muted-foreground">+{items.length - 3} more</span>}
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </>
  );
}

/** The records by day, in order (Story 23.4; the agenda home of Story 23.5, and the calendar on phones). */
export function Agenda({ section, entity, records, design }: TViewProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  const field = design.dateField ?? "";
  const dated = records
    .map((record) => ({ record, date: asDate(record[field]) }))
    .filter((x): x is { record: TRecord; date: Date } => x.date !== null)
    .sort((a, b) => a.date.getTime() - b.date.getTime());
  const groups: { day: Date; items: TRecord[] }[] = [];
  for (const { record, date } of dated) {
    const last = groups[groups.length - 1];
    if (last && dayKey(last.day) === dayKey(date)) last.items.push(record);
    else groups.push({ day: date, items: [record] });
  }
  const timed = entity?.fields?.[field]?.type === "datetime";
  return (
    <div className="flex flex-col gap-6" data-bga-view="agenda">
      {groups.map(({ day, items }) => (
        <section key={dayKey(day)} className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">{dateFormat.format(day)}</h3>
          {items.map((record) => {
            const date = asDate(record[field]);
            return (
              <Card key={String(record.id)} className="flex-row items-start gap-4 p-4">
                {timed && date && <span className="w-16 shrink-0 pt-0.5 text-sm font-semibold tabular-nums">{timeFormat.format(date)}</span>}
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <CardBody entity={entity} record={record} roles={design.roles} actions={actions} href={viewHref(actions, record, route)} skip={field} />
                </div>
              </Card>
            );
          })}
        </section>
      ))}
    </div>
  );
}

/** The catalogue home (Story 23.5): rows of records by category, each with a link to the whole category. */
export function CatalogueRows({ section, entity, records, design, listHref }: TViewProps & { listHref?: string }) {
  const field = design.roles.badge && entity?.fields?.[design.roles.badge]?.type !== "reference" ? design.roles.badge : undefined;
  const groups = new Map<string, TRecord[]>();
  for (const record of records) {
    const key = field ? plain(entity, record, field) || t("other") : t("all");
    groups.set(key, [...(groups.get(key) ?? []), record]);
  }
  if (groups.size <= 1) return <MediaGrid section={section} entity={entity} records={records} design={design} />;
  return (
    <div className="flex flex-col gap-10" data-bga-view="catalogue">
      {[...groups.entries()].map(([label, items]) => {
        const value = field ? items[0]?.[field] : undefined;
        const href = listHref && field && value !== undefined ? `${listHref}?${encodeURIComponent(`${section.id}.${field}`)}=${encodeURIComponent(String(value))}` : listHref;
        return (
          <section key={label} className="flex flex-col gap-4">
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-lg font-semibold">{label}</h2>
              {href && (
                <Link href={href} className="text-sm font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                  {t("seeAll")}
                </Link>
              )}
            </div>
            <MediaGrid section={section} entity={entity} records={items.slice(0, 4)} design={design} />
          </section>
        );
      })}
    </div>
  );
}

/** Story 23.11: the records as an engine-written card, laid out by the view (a grid, or a column for a feed). */
function SlotCards({ section, entity, records, design }: TViewProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  const Card = slots.cards[section.content?.entity ?? ""];
  return (
    <ul className={cn(design.view === "feed" ? "mx-auto flex w-full max-w-2xl flex-col gap-5" : "grid gap-5 sm:grid-cols-2 lg:grid-cols-3")} data-bga-view={design.view} data-bga-slot>
      {records.map((record) => {
        const title = titleOf(entity, record, design.roles);
        return (
          <li key={String(record.id)}>
            <Card
              record={record}
              entity={entity}
              roles={design.roles}
              title={title}
              href={viewHref(actions, record, route)}
              actions={<RowActions actions={actions} record={record} label={title} />}
              view={design.view}
            />
          </li>
        );
      })}
    </ul>
  );
}

/** The records in the entity's list-view plugin (Epic 30: `design-registry.ts` holds the ones this app uses); on the
 *  home page a home plugin may take the main list over (a catalogue's rows, a featured record). */
export function RecordsView(props: TViewProps & { home?: boolean; homeView?: string; listHref?: string }) {
  const { design } = props;
  if (slots.cards[props.section.content?.entity ?? ""] && !designRegistry.whole.includes(design.view)) return <SlotCards {...props} />;
  const Home = props.home ? designRegistry.homes[props.homeView ?? ""] : undefined;
  if (Home) return <Home {...props} />;
  const View = designRegistry.listViews[design.view] ?? TableRows;
  return <View {...props} />;
}
