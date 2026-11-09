"use client";

// A detail-view design plugin (Epic 30): one record's title, fields and actions, arranged another way.
import type { TDetailProps } from "@/components/app/design-types";
import { DetailHeading, FieldGrid } from "@/components/app/details";

export function {{Name}}(props: TDetailProps) {
  const { entity, record, fields } = props;
  return (
    <div className="flex flex-col gap-6" data-bga-detail="{{name}}">
      <DetailHeading {...props} />
      <FieldGrid entity={entity} record={record} fields={fields} />
    </div>
  );
}
