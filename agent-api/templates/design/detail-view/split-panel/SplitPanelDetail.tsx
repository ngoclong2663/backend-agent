"use client";

// Detail-view plugin `split-panel` (Epic 30, Story 30.4): the fields on the left, a side panel on the right with the
// record's parents (their summaries, linked) and its status, dates and figures; one column on phones. The record's
// children stay in the page's tabs under it.
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fieldLabel } from "@/components/app/app";
import type { TDetailProps } from "@/components/app/design-types";
import { DetailHeading, FieldGrid } from "@/components/app/details";
import { FieldValue } from "@/components/app/FieldValue";

const ASIDE_TYPES = new Set(["enum", "date", "datetime", "integer", "number", "decimal", "boolean"]);

export function SplitPanelDetail(props: TDetailProps) {
  const { entity, record, fields } = props;
  const parents = Object.keys(entity?.references ?? {}).filter((field) => fields.includes(field) && record[field] != null);
  const facts = fields.filter((field) => !parents.includes(field) && ASIDE_TYPES.has(entity?.fields?.[field]?.type ?? ""));
  const aside = [...parents, ...facts];
  const main = fields.filter((field) => !aside.includes(field));
  return (
    <div className="flex flex-col gap-6" data-bga-detail="split-panel">
      <DetailHeading {...props} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
        <FieldGrid entity={entity} record={record} fields={main} />
        {aside.length > 0 && (
          <Card size="sm" className="lg:sticky lg:top-20" data-bga-side-panel>
            <CardHeader>
              <CardTitle className="text-sm">{entity?.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="flex flex-col gap-3 text-sm">
                {aside.map((field) => {
                  const parent = entity?.references?.[field];
                  const value = record[field] as { id?: unknown; label?: string } | null;
                  return (
                    <div key={field} className="flex flex-col gap-0.5">
                      <dt className="text-xs text-muted-foreground">{fieldLabel(entity, field)}</dt>
                      <dd className="min-w-0 break-words">
                        {parent && parent.href && value && typeof value === "object" && value.label ? (
                          <Link href={parent.href.replace("[id]", String(value.id))} className="font-medium underline-offset-4 hover:underline">
                            {value.label}
                          </Link>
                        ) : (
                          <FieldValue entity={entity} field={field} record={record} />
                        )}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
