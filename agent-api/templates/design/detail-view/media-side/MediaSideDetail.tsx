"use client";

// Detail-view plugin `media-side` (Epic 30, Story 30.4): the image or the player on the left, the title and fields on
// the right on wide screens; one column on phones.
import type { TDetailProps } from "@/components/app/design-types";
import { DetailHeading, FieldGrid, audioFieldOf } from "@/components/app/details";
import { FileValue } from "@/components/app/plugins";
import { Media, mediaKind } from "@/components/app/views";

export function MediaSideDetail(props: TDetailProps) {
  const { entity, record, design, fields, title } = props;
  const media = design.roles.media;
  const kind = mediaKind(entity, media);
  const audioField = audioFieldOf(entity, media);
  const shown = fields.filter((field) => field !== media && field !== audioField);
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start" data-bga-detail="media-side">
      <div className="flex flex-col gap-3 lg:sticky lg:top-20">
        {media && kind === "video" && (
          <div data-bga-detail-media="video">
            <FileValue entity={entity} field={media} record={record} />
          </div>
        )}
        {media && !kind && <Media entity={entity} record={record} field={media} title={title} className="aspect-[4/3] w-full rounded-xl" />}
        {audioField && (
          <div data-bga-detail-media="audio">
            <FileValue entity={entity} field={audioField} record={record} />
          </div>
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-6">
        <DetailHeading {...props} />
        <FieldGrid entity={entity} record={record} fields={shown} />
      </div>
    </div>
  );
}
