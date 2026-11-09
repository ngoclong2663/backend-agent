"use client";

// Card plugin `stacked` (Epic 30, Story 30.4): the media on top, then the title, subtitle, meta and badge — today's
// card. `boxed` (the `cards` view) draws it inside a bordered card; free-standing (the `media-grid` view) the text sits
// under the picture.
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { TCardProps } from "@/components/app/design-types";
import { RowActions } from "@/components/app/RecordActions";
import { Avatar, Figure, Media, Meta, Title, aspectClass, durationText, mediaKind, plain } from "@/components/app/views";

export function StackedCard({ entity, record, roles, design, title, href, actions, boxed = false }: TCardProps) {
  const badge = plain(entity, record, roles.badge);
  const subtitle = plain(entity, record, roles.subtitle);
  const duration = durationText(entity, record, roles);
  if (boxed) {
    return (
      <Card className="h-full gap-0 overflow-hidden p-0" data-bga-card="stacked">
        {roles.media && <Media entity={entity} record={record} field={roles.media} title={title} className={`${aspectClass(design)} w-full`} />}
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
              {duration && <span className="text-xs tabular-nums text-muted-foreground" data-bga-duration>{duration}</span>}
              <Figure entity={entity} record={record} field={roles.price ?? roles.stat} />
            </span>
          </div>
        </div>
      </Card>
    );
  }
  return (
    <div className="group flex flex-col gap-3" data-bga-card="stacked">
      <Card className="relative gap-0 overflow-hidden p-0" data-bga-media>
        <Media entity={entity} record={record} field={roles.media} title={title} className={`${aspectClass(design)} w-full transition-transform duration-300 group-hover:scale-[1.02] motion-reduce:transition-none`} />
        {badge && (
          <Badge className="absolute top-2 left-2" variant="secondary">
            {badge}
          </Badge>
        )}
        {duration && (
          <span className="absolute right-2 bottom-2 rounded bg-black/70 px-1.5 py-0.5 text-xs tabular-nums text-white" data-bga-duration>
            {duration}
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
    </div>
  );
}
