"use client";

// Card plugin `overlay` (Epic 30, Story 30.4): the media fills the card; the title and meta sit over a scrim at its
// foot (posters, covers). The scrim is black at 85 % under the text, so white text keeps AA contrast on the worst pixel.
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import type { TCardProps } from "@/components/app/design-types";
import { RowActions } from "@/components/app/RecordActions";
import { Media, aspectClass, durationText, plain } from "@/components/app/views";

export function OverlayCard({ entity, record, roles, design, title, href, actions }: TCardProps) {
  const badge = plain(entity, record, roles.badge);
  const subtitle = plain(entity, record, roles.subtitle);
  const duration = durationText(entity, record, roles);
  return (
    <div className={`group relative overflow-hidden rounded-xl bg-muted ${aspectClass(design, "portrait")}`} data-bga-card="overlay">
      <Media entity={entity} record={record} field={roles.media} title={title} className="absolute inset-0 size-full transition-transform duration-300 group-hover:scale-[1.03] motion-reduce:transition-none" />
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/70 to-transparent px-3 pt-12 pb-3 text-white">
        <div className="flex items-end justify-between gap-2">
          <div className="min-w-0 flex-1">
            <h3 className="line-clamp-2 font-semibold leading-snug">
              {href ? (
                <Link href={href} className="after:absolute after:inset-0 focus-visible:underline">
                  {title}
                </Link>
              ) : (
                title
              )}
            </h3>
            {subtitle && <p className="truncate text-xs text-white/90">{subtitle}</p>}
          </div>
          <span className="relative z-10 flex shrink-0 items-center gap-2 text-xs">
            {duration && <span className="rounded bg-black/70 px-1.5 py-0.5 tabular-nums" data-bga-duration>{duration}</span>}
            <RowActions actions={actions} record={record} label={title} />
          </span>
        </div>
      </div>
      {badge && (
        <Badge className="absolute top-2 left-2 z-10" variant="secondary">
          {badge}
        </Badge>
      )}
    </div>
  );
}
