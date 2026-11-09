"use client";

// Card plugin `side` (Epic 30, Story 30.4): the media on the left, the text on the right; one column on phones
// (listings, people, products with details to read).
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { TCardProps } from "@/components/app/design-types";
import { RowActions } from "@/components/app/RecordActions";
import { Figure, Media, Meta, Title, aspectClass, durationText, plain } from "@/components/app/views";

export function SideCard({ entity, record, roles, design, title, href, actions }: TCardProps) {
  const badge = plain(entity, record, roles.badge);
  const subtitle = plain(entity, record, roles.subtitle);
  const duration = durationText(entity, record, roles);
  return (
    <Card className="h-full gap-0 overflow-hidden p-0 sm:flex-row" data-bga-card="side">
      {roles.media && (
        <Media entity={entity} record={record} field={roles.media} title={title} className={`${aspectClass(design)} w-full shrink-0 sm:aspect-auto sm:w-44 sm:self-stretch`} />
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <Title href={href} title={title} className="line-clamp-2" />
          <RowActions actions={actions} record={record} label={title} />
        </div>
        {subtitle && <p className="line-clamp-3 text-sm text-muted-foreground">{subtitle}</p>}
        <Meta entity={entity} record={record} roles={roles} />
        <div className="mt-auto flex items-center justify-between gap-2 pt-1">
          {badge ? <Badge variant="secondary">{badge}</Badge> : <span />}
          <span className="flex items-center gap-3">
            {duration && <span className="text-xs tabular-nums text-muted-foreground" data-bga-duration>{duration}</span>}
            <Figure entity={entity} record={record} field={roles.price ?? roles.stat} />
          </span>
        </div>
      </div>
    </Card>
  );
}
