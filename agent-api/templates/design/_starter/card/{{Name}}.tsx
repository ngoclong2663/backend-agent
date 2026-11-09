"use client";

// A card design plugin (Epic 30, Story 30.4): the anatomy of one record in a grid view. The grid decides the columns;
// the card draws the record's roles (media, title, subtitle, meta, badge, figure) and keeps its actions.
import { Card } from "@/components/ui/card";
import type { TCardProps } from "@/components/app/design-types";
import { RowActions } from "@/components/app/RecordActions";
import { Media, Meta, Title } from "@/components/app/views";

export function {{Name}}({ entity, record, roles, title, href, actions }: TCardProps) {
  return (
    <Card className="h-full gap-0 overflow-hidden p-0" data-bga-card="{{name}}">
      {roles.media && <Media entity={entity} record={record} field={roles.media} title={title} className="aspect-video w-full" />}
      <div className="flex flex-col gap-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <Title href={href} title={title} className="line-clamp-2" />
          <RowActions actions={actions} record={record} label={title} />
        </div>
        <Meta entity={entity} record={record} roles={roles} />
      </div>
    </Card>
  );
}
