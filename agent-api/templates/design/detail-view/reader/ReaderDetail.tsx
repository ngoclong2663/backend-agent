"use client";

// Detail-view plugin `reader` (Epic 30, Story 30.4): a narrow reading column for records with long text (articles,
// notes, lessons' descriptions): the text first as prose, the other fields in a compact list under it.
import { fieldLabel } from "@/components/app/app";
import type { TDetailProps } from "@/components/app/design-types";
import { DetailHeading } from "@/components/app/details";
import { FieldValue } from "@/components/app/FieldValue";
import { Media } from "@/components/app/views";

export function ReaderDetail(props: TDetailProps) {
  const { entity, record, design, fields, title } = props;
  const texts = fields.filter((field) => entity?.fields?.[field]?.type === "text" && record[field]);
  const media = design.roles.media && entity?.fields?.[design.roles.media]?.type === "image" ? design.roles.media : undefined;
  const rest = fields.filter((field) => !texts.includes(field) && field !== media);
  return (
    <article className="mx-auto flex w-full max-w-prose flex-col gap-6" data-bga-detail="reader">
      <DetailHeading {...props} />
      {media && <Media entity={entity} record={record} field={media} title={title} className="aspect-[3/2] w-full rounded-xl" />}
      {texts.map((field) => (
        <section key={field} className="flex flex-col gap-2">
          {texts.length > 1 && <h2 className="text-sm font-semibold text-muted-foreground">{fieldLabel(entity, field)}</h2>}
          <div className="text-lg leading-relaxed whitespace-pre-line">
            <FieldValue entity={entity} field={field} record={record} />
          </div>
        </section>
      ))}
      {rest.length > 0 && (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2 border-t pt-4 text-sm">
          {rest.map((field) => (
            <div key={field} className="contents">
              <dt className="text-muted-foreground">{fieldLabel(entity, field)}</dt>
              <dd className="min-w-0 break-words">
                <FieldValue entity={entity} field={field} record={record} />
              </dd>
            </div>
          ))}
        </dl>
      )}
    </article>
  );
}
