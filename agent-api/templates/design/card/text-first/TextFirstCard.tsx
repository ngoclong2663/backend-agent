"use client";

// Card plugin `text-first` (Epic 30, Story 30.4): no media: a large title, the meta in a row, the badge and a figure
// (records without images).
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { TCardProps } from "@/components/app/design-types";
import { RowActions } from "@/components/app/RecordActions";
import { Avatar, Figure, Meta, Title, plain } from "@/components/app/views";

export function TextFirstCard({ entity, record, roles, title, href, actions }: TCardProps) {
  const badge = plain(entity, record, roles.badge);
  const subtitle = plain(entity, record, roles.subtitle);
  return (
    <Card className="h-full gap-3 p-5" data-bga-card="text-first">
      <div className="flex items-start justify-between gap-3">
        <Title href={href} title={title} className="line-clamp-3 text-lg leading-snug" />
        <RowActions actions={actions} record={record} label={title} />
      </div>
      {subtitle && <p className="line-clamp-3 text-sm text-muted-foreground">{subtitle}</p>}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1">
        <span className="flex min-w-0 items-center gap-2">
          {roles.avatar && <Avatar entity={entity} record={record} field={roles.avatar} label={subtitle || title} />}
          <Meta entity={entity} record={record} roles={roles} />
        </span>
        <span className="flex items-center gap-3">
          {badge && <Badge variant="secondary">{badge}</Badge>}
          <Figure entity={entity} record={record} field={roles.price ?? roles.stat} />
        </span>
      </div>
    </Card>
  );
}
