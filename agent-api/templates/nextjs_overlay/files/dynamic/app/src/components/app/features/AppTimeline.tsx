"use client";

import { Check } from "lucide-react";
import { useParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { enumLabel, resolveParams, type TAppSection, type TRecord, type TRouteParams } from "../app";
import { useOperationQuery } from "../bindings";

/** Epic 33 (the tracking feature): a record's status as the steps of its journey, done, current and still to come. */
export function AppTimeline({ section }: { section: TAppSection }) {
  const timeline = section.content?.timeline;
  const route = (useParams() ?? {}) as TRouteParams;
  const params = resolveParams(section.data?.params, route, undefined) ?? {};
  const query = useOperationQuery(section.data?.operationId, params);
  if (!timeline) return null;
  const record = (query.data ?? {}) as TRecord;
  const current = timeline.states.indexOf(String(record[timeline.field] ?? ""));
  return (
    <div className="flex flex-col gap-3" data-bga-timeline>
      <h2 className="text-base font-semibold">{section.content?.title ?? "Progress"}</h2>
      <ol className="flex flex-col">
        {timeline.states.map((state, index) => {
          const done = current >= 0 && index < current;
          const now = index === current;
          return (
            <li key={state} className="flex items-center gap-3 py-1.5" aria-current={now ? "step" : undefined}>
              <span
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full border text-xs",
                  done && "bg-primary text-primary-foreground border-primary",
                  now && "border-primary text-primary border-2 font-semibold",
                )}
              >
                {done ? <Check className="size-3.5" aria-hidden /> : index + 1}
              </span>
              <span className={cn("text-sm", !done && !now && "text-muted-foreground", now && "font-semibold")}>
                {enumLabel(state)}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
