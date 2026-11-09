"use client";

import { ChevronLeft, ChevronRight, Inbox, Plus, Search, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { usePathname, useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  canUse,
  pageOperation,
  enumLabel,
  app,
  fieldLabel,
  listOf,
  pageHref,
  resolveParams,
  type TAppEntity,
  type TAppSection,
  type TRecord,
  type TRouteParams,
} from "./app";
import { filterOptions, useOperationQuery } from "./bindings";
import { entityDesign, useLayout } from "./layout";
import { useSession } from "./plugins";
import { RowActions } from "./RecordActions";
import { designRegistry } from "./design-registry";
import { Calendar, PlainCards, RecordsView, TableRows } from "./views";
import { inSentence, t } from "./messages";

const PAGE_SIZE = 20;
const RECENT = 5;

type ListProps = { section: TAppSection; heading: "h1" | "h2"; pageId: string; hideTitle?: boolean };

/** The list parameters in the URL, per section (`<section>.q`, `.page`…), so two lists on a page do not share them. */
function useListState(sectionId: string) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const key = (name: string) => `${sectionId}.${name}`;
  const get = (name: string) => searchParams?.get(key(name)) ?? null;
  function set(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams?.toString() ?? "");
    for (const [name, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key(name));
      else next.set(key(name), value);
    }
    if (!("page" in changes)) next.delete(key("page"));
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }
  return { get, set };
}

/** A filter's values as a row of chips (Story 23.5): one press filters, the pressed chip again clears. */
function Chips({ name, label, options, state }: { name: string; label: string; options: string[]; state: ReturnType<typeof useListState> }) {
  const current = state.get(name);
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={label}>
      {[null, ...options].map((option) => (
        <Button
          key={option ?? "ALL"}
          size="sm"
          variant={current === option ? "default" : "outline"}
          className="rounded-full"
          aria-pressed={current === option}
          onClick={() => state.set({ [name]: option })}
        >
          {option === null ? t("all") : enumLabel(option)}
        </Button>
      ))}
    </div>
  );
}

function Controls({ section, entity, state, style = "toolbar" }: { section: TAppSection; entity?: TAppEntity; state: ReturnType<typeof useListState>; style?: string }) {
  const controls = section.content?.controls ?? {};
  const [search, setSearch] = useState(state.get("q") ?? "");
  const options = filterOptions[section.data?.operationId ?? ""] ?? {};
  useEffect(() => {
    const timer = setTimeout(() => {
      if (search !== (state.get("q") ?? "")) state.set({ q: search || null });
    }, 300);
    return () => clearTimeout(timer);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps
  const filters = (controls.filters ?? []).filter((name) => options[name]?.length);
  if (!controls.search && filters.length === 0 && !controls.sort?.length) return null;
  // Story 23.5: chips for short value lists, a facet panel, or a search first with the filters as chips under it
  const chipped = style === "chips" || style === "search-first" ? filters.filter((name) => options[name].length <= 12) : [];
  if (style === "facets" && filters.length) {
    return (
      <aside className="flex flex-col gap-5" aria-label="Filters" data-bga-filters="facets">
        {controls.search && (
          <Input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("search", { name: inSentence(entity?.plural ?? t("records")) })} aria-label={t("search", { name: inSentence(entity?.plural ?? t("records")) })} />
        )}
        {filters.map((name) => (
          <fieldset key={name} className="flex flex-col gap-1">
            <legend className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{fieldLabel(entity, name)}</legend>
            {[null, ...options[name]].map((option) => (
              <button
                key={option ?? "ALL"}
                type="button"
                aria-pressed={state.get(name) === option}
                onClick={() => state.set({ [name]: option })}
                className="rounded-md px-2 py-1 text-left text-sm text-muted-foreground hover:bg-accent hover:text-foreground aria-pressed:bg-accent aria-pressed:font-medium aria-pressed:text-foreground"
              >
                {option === null ? t("all") : enumLabel(option)}
              </button>
            ))}
          </fieldset>
        ))}
      </aside>
    );
  }
  if (chipped.length) {
    return (
      <div className="flex flex-col gap-3" data-bga-filters={style}>
        {controls.search && style === "search-first" && (
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("search", { name: inSentence(entity?.plural ?? t("records")) })} aria-label={t("search", { name: inSentence(entity?.plural ?? t("records")) })} className="h-12 rounded-full pl-11 text-base" />
          </div>
        )}
        {chipped.map((name) => (
          <Chips key={name} name={name} label={fieldLabel(entity, name)} options={options[name]} state={state} />
        ))}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2" role="search">
      {controls.search && (
        <div className="relative min-w-48 flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("search", { name: inSentence(entity?.plural ?? t("records")) })}
            aria-label={t("search", { name: inSentence(entity?.plural ?? t("records")) })}
            className="pl-8"
          />
        </div>
      )}
      {filters.map((name) => (
        <Select
          key={name}
          items={{ ALL: t("allOf", { name: inSentence(fieldLabel(entity, name)) }), ...Object.fromEntries(options[name].map((o) => [o, enumLabel(o)])) }}
          value={state.get(name) ?? "ALL"}
          onValueChange={(value) => state.set({ [name]: value === "ALL" || value === null ? null : String(value) })}
        >
          <SelectTrigger className="w-40" aria-label={fieldLabel(entity, name)}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">{t("allOf", { name: inSentence(fieldLabel(entity, name)) })}</SelectItem>
            {options[name].map((option) => (
              <SelectItem key={option} value={option}>
                {enumLabel(option)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ))}
      {Boolean(controls.sort?.length) && (
        <Select
          items={{
            DEFAULT: t("defaultOrder"),
            ...Object.fromEntries(
              (controls.sort ?? []).flatMap((field) => [
                [field, `${fieldLabel(entity, field)} ↑`],
                [`-${field}`, `${fieldLabel(entity, field)} ↓`],
              ]),
            ),
          }}
          value={state.get("sort") ?? "DEFAULT"}
          onValueChange={(value) => state.set({ sort: value === "DEFAULT" || value === null ? null : String(value) })}
        >
          <SelectTrigger className="w-44" aria-label="Sort">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="DEFAULT">{t("defaultOrder")}</SelectItem>
            {(controls.sort ?? []).flatMap((field) => [
              <SelectItem key={field} value={field}>
                {fieldLabel(entity, field)} ↑
              </SelectItem>,
              <SelectItem key={`-${field}`} value={`-${field}`}>
                {fieldLabel(entity, field)} ↓
              </SelectItem>,
            ])}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}

function Pager({ page, total, size, onPage }: { page: number; total: number; size: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages <= 1) return null;
  return (
    <nav className="flex items-center justify-between gap-2 text-sm text-muted-foreground" aria-label="Pages">
      <span>
        {(page - 1) * size + 1}–{Math.min(page * size, total)} of {total}
      </span>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="icon-sm" onClick={() => onPage(page - 1)} disabled={page <= 1} aria-label={t("previousPage")}>
          <ChevronLeft aria-hidden />
        </Button>
        <span className="px-2 tabular-nums">
          {page} / {pages}
        </span>
        <Button variant="outline" size="icon-sm" onClick={() => onPage(page + 1)} disabled={page >= pages} aria-label={t("nextPage")}>
          <ChevronRight aria-hidden />
        </Button>
      </div>
    </nav>
  );
}

function CreateLink({ section }: { section: TAppSection }) {
  const route = (useParams() ?? {}) as TRouteParams;
  const session = useSession();
  const create = section.content?.create;
  // Story 22.7: no "New" for who may not create (signed out, or a role the policy leaves out)
  if (!create || !canUse(pageOperation(create.page), session)) return null;
  return (
    <Link
      href={pageHref(create.page, resolveParams(create.params, route), route)}
      className={cn(buttonVariants({ size: "sm" }))}
      data-bga-action="create"
    >
      <Plus aria-hidden />
      {create.label}
    </Link>
  );
}

function Rows({ section, entity, records, home = false }: { section: TAppSection; entity?: TAppEntity; records: TRecord[]; home?: boolean }) {
  const layout = useLayout();
  // Epic 23: the layout's view of this entity (an area may show it another way); Epic 30: the view is a plugin
  const design = entityDesign(layout, section.content?.entity);
  if (section.content?.variant === "recent") {
    // a dashboard's recent list: plain cards only when the layout says cards (or, without a layout entry, the outline)
    const designed = Boolean(layout.entities?.[section.content?.entity ?? ""]);
    const cards = design.view === "cards" || (!designed && (section.content?.style ?? entity?.listStyle) === "cards");
    return cards ? <PlainCards section={section} entity={entity} records={records} design={design} /> : <TableRows section={section} entity={entity} records={records} design={design} />;
  }
  return <RecordsView section={section} entity={entity} records={records} design={design} home={home} homeView={layout.homeView} listHref={entity?.list ?? undefined} />;
}

export function ListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <Empty className="border border-destructive/30">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <TriangleAlert aria-hidden />
        </EmptyMedia>
        <EmptyTitle>{t("couldNotLoad")}</EmptyTitle>
        <EmptyDescription>{t("checkConnection")}</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t("tryAgain")}
        </Button>
      </EmptyContent>
    </Empty>
  );
}

function ListBody({ section, heading, hideTitle, pageId }: ListProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const state = useListState(section.id);
  const layout = useLayout();
  const entity = app.entities[section.content?.entity ?? ""];
  const recent = section.content?.variant === "recent";
  const controls = section.content?.controls ?? {};
  const design = entityDesign(layout, section.content?.entity);
  const home = pageId === "home" && !section.content?.tab;
  // Epic 23: a calendar (or the agenda home) asks for its dates itself; a board and a catalogue home load at once
  const dated = !recent && design.view === "calendar" && Boolean(design.dateField);
  const agenda = dated && home && layout.homeView === "agenda";
  const whole = !recent && (designRegistry.whole.includes(design.view) || (home && Boolean(designRegistry.homes[layout.homeView])));
  const page = Math.max(1, Number(state.get("page") ?? 1) || 1);
  const size = recent ? RECENT : whole ? (controls.maxLimit ?? 100) : PAGE_SIZE;
  const params: Record<string, unknown> = { ...resolveParams(section.data?.params, route) };
  if (!recent) {
    if (controls.search && state.get("q")) params.q = state.get("q");
    for (const name of controls.filters ?? []) if (state.get(name)) params[name] = state.get(name);
    if (state.get("sort")) params.sort = state.get("sort");
    else if (design.view === "feed") {
      // a feed reads newest first (its date sort is added by code, Story 23.3)
      const dateSort = (controls.sort ?? []).find((field) => ["date", "datetime"].includes(entity?.fields?.[field]?.type ?? ""));
      if (dateSort) params.sort = `-${dateSort}`;
    }
  }
  const base = { ...params };
  if (!recent && section.data?.action === "list") Object.assign(params, { limit: size, offset: whole ? 0 : (page - 1) * size });
  const query = useOperationQuery(dated ? undefined : section.data?.operationId, params);
  const { records, total } = listOf(query.data);
  const title = section.content?.title ?? entity?.plural ?? "Records";
  const Heading = heading;
  const filtered = Boolean(state.get("q")) || (controls.filters ?? []).some((name) => state.get(name));
  // Story 23.9: a restricted caller is told what they may see (the backend narrowed the list, the kit only explains)
  const session = useSession();
  const rule = entity?.visibility;
  const shownOnly =
    rule && (!session.user || rule.roles.includes(String(session.user.role)))
      ? Object.values(rule.where).map((value) => enumLabel(String(value)).toLowerCase()).join(", ")
      : null;

  return (
    <div className="flex flex-col gap-4">
      <div className={cn("flex flex-wrap items-center justify-between gap-3", hideTitle && !section.content?.create && "sr-only")}>
        <Heading
          className={cn(heading === "h1" ? "text-2xl font-semibold tracking-tight" : "text-lg font-semibold", hideTitle && "sr-only")}
        >
          {title}
        </Heading>
        <CreateLink section={section} />
      </div>
      {!recent && design.filtersStyle !== "facets" && <Controls section={section} entity={entity} state={state} style={design.filtersStyle} />}
      <div className={cn(!recent && design.filtersStyle === "facets" && "grid gap-6 lg:has-[>aside]:grid-cols-[14rem_minmax(0,1fr)]")}>
      {!recent && design.filtersStyle === "facets" && <Controls section={section} entity={entity} state={state} style="facets" />}
      <div className="flex min-w-0 flex-col gap-4">
      {dated ? (
        <Calendar section={section} entity={entity} params={base} design={design} agenda={agenda} />
      ) : query.isLoading ? (
        <ListSkeleton rows={recent ? 3 : 5} />
      ) : query.error ? (
        <LoadError onRetry={() => query.refetch()} />
      ) : records.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Inbox aria-hidden />
            </EmptyMedia>
            <EmptyTitle>{filtered ? t("nothingMatches") : t("noneYet", { name: inSentence(title) })}</EmptyTitle>
            <EmptyDescription>
              {filtered
                ? t("tryAnother")
                : shownOnly
                  ? t("onlyShown", { where: shownOnly, name: inSentence(title) })
                  : section.content?.create
                    ? t("addFirst")
                    : t("appearOnceAdded")}
            </EmptyDescription>
          </EmptyHeader>
          {!filtered && section.content?.create && (
            <EmptyContent>
              <CreateLink section={section} />
            </EmptyContent>
          )}
        </Empty>
      ) : (
        <>
          <Rows section={section} entity={entity} records={records} home={home} />
          {!recent && !whole && section.data?.action === "list" && (
            <Pager page={page} total={total} size={size} onPage={(next) => state.set({ page: String(next) })} />
          )}
        </>
      )}
      </div>
      </div>
    </div>
  );
}

/** The records of an entity (Story 22.4): a table (or cards) bound to its list operation, with search, filters, sort
 *  and pages on the server, row actions in a menu, and loading, empty and error states. */
export function AppList(props: ListProps) {
  return (
    <Suspense fallback={<ListSkeleton />}>
      <ListBody {...props} />
    </Suspense>
  );
}
