"use client";

// A list-view design plugin (Epic 30): the same AppList section (operation, parameters, row actions, allowedActions),
// another presentation. Theme tokens and the kit's primitives only; every record keeps its actions.
import { useParams } from "next/navigation";
import { Card } from "@/components/ui/card";
import type { TRouteParams } from "@/components/app/app";
import type { TViewProps } from "@/components/app/design-types";
import { CardBody, viewHref } from "@/components/app/views";

export function {{Name}}({ section, entity, records, design }: TViewProps) {
  const route = (useParams() ?? {}) as TRouteParams;
  const actions = section.content?.actions ?? [];
  return (
    <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-bga-view="{{name}}">
      {records.map((record) => (
        <li key={String(record.id)}>
          <Card className="h-full gap-2 p-4">
            <CardBody entity={entity} record={record} roles={design.roles} actions={actions} href={viewHref(actions, record, route)} />
          </Card>
        </li>
      ))}
    </ul>
  );
}
