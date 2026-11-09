"use client";

// List-view plugin `shelves` (Epic 30, Story 30.5): media records in rows by group (a category or a parent), each a
// horizontal strip with snap points, arrow buttons on wide screens and keyboard scrolling; "See all" opens the list
// filtered to the group. Cards come from the entity's card plugin.
import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { enumLabel, type TRecord, type TRouteParams } from "@/components/app/app";
import type { TViewProps } from "@/components/app/design-types";
import { t } from "@/components/app/messages";
import { CardOf, MediaGrid, aspectClass, plain, titleOf, viewHref } from "@/components/app/views";

const WIDTH: Record<string, string> = { "aspect-[2/3]": "w-40 sm:w-44", "aspect-square": "w-44 sm:w-52", "aspect-video": "w-64 sm:w-72" };

export function Shelves({ section, entity, records, design, listHref }: TViewProps & { listHref?: string }) {
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  const field = design.groupBy;
  const groups = new Map<string, TRecord[]>();
  for (const record of records) {
    const key = field ? plain(entity, record, field) || t("other") : t("all");
    groups.set(key, [...(groups.get(key) ?? []), record]);
  }
  if (!field || groups.size <= 1) return <MediaGrid section={section} entity={entity} records={records} design={design} />;
  const href = listHref ?? entity?.list ?? undefined;
  return (
    <div className="flex flex-col gap-8" data-bga-view="shelves">
      {[...groups.entries()].map(([label, items]) => {
        const value = items[0]?.[field];
        const parent = entity?.references?.[field] && value && typeof value === "object" ? (value as { id?: unknown }).id : value;
        const seeAll = href && parent !== undefined ? `${href}?${encodeURIComponent(`${section.id}.${field}`)}=${encodeURIComponent(String(parent))}` : href;
        return <Shelf key={label} label={entity?.fields?.[field]?.type === "enum" ? enumLabel(label) : label} items={items} seeAll={seeAll} entity={entity} design={design} actions={actions} route={route} />;
      })}
    </div>
  );
}

function Shelf({ label, items, seeAll, entity, design, actions, route }: { label: string; items: TRecord[]; seeAll?: string; entity: TViewProps["entity"]; design: TViewProps["design"]; actions: NonNullable<TViewProps["section"]["content"]>["actions"] & object; route: TRouteParams }) {
  const strip = useRef<HTMLUListElement>(null);
  const roles = design.roles;
  const step = (direction: 1 | -1) => strip.current?.scrollBy({ left: direction * strip.current.clientWidth * 0.8, behavior: "smooth" });
  const onKey = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      step(event.key === "ArrowRight" ? 1 : -1);
    }
  };
  const width = WIDTH[aspectClass(design)] ?? WIDTH["aspect-video"];
  return (
    <section className="flex flex-col gap-3" data-bga-shelf={label}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold">{label}</h2>
        <span className="flex items-center gap-1">
          {seeAll && (
            <Link href={seeAll} className="text-sm font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
              {t("seeAll")}
            </Link>
          )}
          <Button variant="ghost" size="icon-sm" className="hidden md:inline-flex" aria-label={`${label}: ${t("previous")}`} onClick={() => step(-1)}>
            <ChevronLeft aria-hidden />
          </Button>
          <Button variant="ghost" size="icon-sm" className="hidden md:inline-flex" aria-label={`${label}: ${t("next")}`} onClick={() => step(1)}>
            <ChevronRight aria-hidden />
          </Button>
        </span>
      </div>
      <ul
        ref={strip}
        tabIndex={0}
        onKeyDown={onKey}
        aria-label={label}
        className="-mx-1 flex snap-x snap-mandatory gap-4 overflow-x-auto scroll-smooth px-1 pb-2 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none motion-reduce:scroll-auto"
      >
        {items.map((record) => {
          const title = titleOf(entity, record, roles);
          return (
            <li key={String(record.id)} className={cn("shrink-0 snap-start", width)}>
              <CardOf design={design} entity={entity} record={record} roles={roles} title={title} href={viewHref(actions ?? [], record, route)} actions={actions ?? []} boxed={false} size="sm" />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
