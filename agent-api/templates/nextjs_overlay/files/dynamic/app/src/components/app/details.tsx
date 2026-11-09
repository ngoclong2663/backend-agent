"use client";

// Epic 30 (Story 30.2): the kit's built-in detail-view plugins (`templates/design/detail-view/*`, `builtin: true`),
// dispatched by the generated `design-registry.ts`. Every detail view shows the same record, title, fields and actions.
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fieldLabel, type TAppEntity, type TRecord } from "./app";
import type { TDetailProps } from "./design-types";
import { FieldValue } from "./FieldValue";
import { FileValue } from "./plugins";
import { Media, mediaKind } from "./views";

/** The record's fields in a description grid (shared by the detail views). */
export function FieldGrid({ entity, record, fields, className }: { entity?: TAppEntity; record: TRecord; fields: string[]; className?: string }) {
  return (
    <Card className={className}>
      <CardContent>
        <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
          {fields
            .filter((field) => field !== entity?.displayField)
            .map((field) => (
              <div key={field} className="flex min-w-0 flex-col gap-1">
                <dt className="text-sm text-muted-foreground">{fieldLabel(entity, field)}</dt>
                <dd className="min-w-0 break-words">
                  <FieldValue entity={entity} field={field} record={record} />
                </dd>
              </div>
            ))}
        </dl>
      </CardContent>
    </Card>
  );
}

/** The heading row every detail view shares: the entity, the title (optionally a picture beside it) and the actions. */
export function DetailHeading({ section, entity, record, title, actions, picture }: TDetailProps & { picture?: string }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      {picture && <Media entity={entity} record={record} field={picture} title={title} className="size-20 shrink-0 rounded-full" />}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-sm text-muted-foreground">{section.content?.title ?? entity?.label}</p>
        <h1 className="text-2xl font-semibold tracking-tight break-words">{title}</h1>
      </div>
      {actions}
    </div>
  );
}

/** An audio record's player sits under the title whatever the view (Epic 29). */
export function audioFieldOf(entity: TAppEntity | undefined, media: string | undefined): string | undefined {
  if (mediaKind(entity, media) === "audio") return media;
  return Object.keys(entity?.fields ?? {}).find((name) => entity?.fields?.[name]?.type === "audio");
}

function Body({ props, media, picture, className }: { props: TDetailProps; media?: string; picture?: string; className?: string }) {
  const { entity, record, fields } = props;
  const kind = mediaKind(entity, media);
  const audioField = audioFieldOf(entity, media);
  const shown = fields.filter((field) => field !== media && field !== picture && field !== audioField);
  return (
    <div className={cn("flex flex-col gap-6", className)}>
      {media && kind === "video" && (
        <div data-bga-detail-media="video">
          <FileValue entity={entity} field={media} record={record} />
        </div>
      )}
      {media && !kind && <Media entity={entity} record={record} field={media} title={props.title} className="aspect-[21/9] w-full rounded-xl" />}
      <DetailHeading {...props} picture={picture} />
      {audioField && (
        <div data-bga-detail-media="audio">
          <FileValue entity={entity} field={audioField} record={record} />
        </div>
      )}
      <FieldGrid entity={entity} record={record} fields={shown} />
    </div>
  );
}

/** The fields in a grid under the name and the actions. */
export function RecordDetail(props: TDetailProps) {
  return (
    <div data-bga-detail="record">
      <Body props={props} />
    </div>
  );
}

/** A large image (or the player) first, then the fields (Story 23.3; Epic 29: a video opens on its player). */
export function MediaDetail(props: TDetailProps) {
  return (
    <div data-bga-detail="media">
      <Body props={props} media={props.design.roles.media} />
    </div>
  );
}

/** A picture beside the name, for people and organisations. */
export function ProfileDetail(props: TDetailProps) {
  return (
    <div data-bga-detail="profile">
      <Body props={props} picture={props.design.roles.avatar ?? props.design.roles.media} />
    </div>
  );
}
