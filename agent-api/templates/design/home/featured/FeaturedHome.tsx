"use client";

// Home plugin `featured` (Epic 30, Story 30.5): one record across the top (its media large, the title, subtitle and
// the main action), then the rest as shelves (or the entity's own view). The featured record is the first flagged
// `featured`, else the newest by the feed's date (the list loads newest first), else the first.
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ComponentType } from "react";
import { Button } from "@/components/ui/button";
import type { TRecord, TRouteParams } from "@/components/app/app";
import type { THomeProps } from "@/components/app/design-types";
import { designRegistry } from "@/components/app/design-registry";
import { t } from "@/components/app/messages";
import { Media, MediaGrid, Meta, durationText, plain, titleOf, viewHref } from "@/components/app/views";

function pick(records: TRecord[], entity: THomeProps["entity"]): TRecord | undefined {
  const flag = Object.keys(entity?.fields ?? {}).find((name) => entity?.fields?.[name]?.type === "boolean" && /featur/i.test(name));
  return (flag && records.find((record) => record[flag] === true)) || records[0];
}

export function FeaturedHome({ section, entity, records, design, listHref }: THomeProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  const roles = design.roles;
  const featured = pick(records, entity);
  if (!featured) return <MediaGrid section={section} entity={entity} records={records} design={design} />;
  const rest = records.filter((record) => record !== featured);
  const title = titleOf(entity, featured, roles);
  const href = viewHref(actions, featured, route);
  const subtitle = plain(entity, featured, roles.subtitle);
  const badge = plain(entity, featured, roles.badge);
  const duration = durationText(entity, featured, roles);
  // the rest as shelves when the app has them (a home plugin may build on a list-view plugin), else a grid
  const Rest = (designRegistry.listViews.shelves ?? MediaGrid) as ComponentType<THomeProps>;
  return (
    <div className="flex flex-col gap-10" data-bga-view="featured">
      <section className="relative overflow-hidden rounded-2xl bg-muted" data-bga-featured>
        <Media entity={entity} record={featured} field={roles.media} title={title} className="aspect-[16/7] w-full min-h-64" />
        <div className="absolute inset-0 flex flex-col justify-end bg-gradient-to-t from-black/85 via-black/50 to-transparent p-6 text-white sm:p-10">
          <div className="flex max-w-2xl flex-col gap-3">
            {badge && <span className="text-xs font-semibold tracking-wide uppercase text-white/90">{badge}</span>}
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h2>
            {subtitle && <p className="line-clamp-2 text-sm text-white/90 sm:text-base">{subtitle}</p>}
            <div className="flex flex-wrap items-center gap-3 text-sm text-white/90 [&_*]:text-white/90">
              <Meta entity={entity} record={featured} roles={roles} />
              {duration && <span className="tabular-nums" data-bga-duration>{duration}</span>}
            </div>
            {href && (
              <Button size="lg" className="w-fit" render={<Link href={href} />}>
                {t("open")}
              </Button>
            )}
          </div>
        </div>
      </section>
      <Rest section={section} entity={entity} records={rest} design={design} listHref={listHref} />
    </div>
  );
}
