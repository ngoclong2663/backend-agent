"use client";

// A home design plugin (Epic 30): takes the main list's rendering over on the home page (the records, the entity's
// design and the route of the whole list for "See all").
import Link from "next/link";
import type { THomeProps } from "@/components/app/design-types";
import { t } from "@/components/app/messages";
import { RoleCards } from "@/components/app/views";

export function {{Name}}({ section, entity, records, design, listHref }: THomeProps) {
  return (
    <div className="flex flex-col gap-6" data-bga-view="{{name}}">
      <RoleCards section={section} entity={entity} records={records.slice(0, 6)} design={design} />
      {listHref && (
        <Link href={listHref} className="self-end text-sm font-medium text-muted-foreground underline-offset-4 hover:underline">
          {t("seeAll")}
        </Link>
      )}
    </div>
  );
}
