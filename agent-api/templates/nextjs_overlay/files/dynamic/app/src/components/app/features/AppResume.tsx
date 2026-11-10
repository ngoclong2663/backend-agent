"use client";

import Link from "next/link";
import { PlayCircle } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { app, listOf, pageHref, recordTitle, type TAppSection } from "../app";
import { useOperationQuery } from "../bindings";

/** Epic 33 (the enrollment feature's `resume-card`): what the person is in the middle of, with their progress and a
 *  Continue link, first on their home. */
export function AppResume({ section }: { section: TAppSection }) {
  const resume = section.content?.resume;
  const query = useOperationQuery(section.data?.operationId, { ...(section.data?.params ?? {}), limit: 100 });
  if (!resume) return null;
  const mine = listOf(query.data).records.filter((record) => Boolean(record[resume.state]));
  if (query.isLoading || mine.length === 0) return null;
  return (
    <div className="flex flex-col gap-3" data-bga-resume>
      <h2 className="text-base font-semibold">{section.content?.title ?? "Continue"}</h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {mine.slice(0, 4).map((record) => {
          const done = Number(resume.done ? record[resume.done] : 0) || 0;
          const total = Number(resume.total ? record[resume.total] : 0) || 0;
          const share = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
          const entity = section.content?.entity ?? "";
          return (
            <li key={String(record.id)} className="bg-card flex flex-col gap-3 rounded-lg border p-4">
              <span className="font-medium">{recordTitle(app.entities[entity], record)}</span>
              {resume.total && (
                <div className="flex items-center gap-3">
                  <Progress value={share} aria-label="Progress" className="h-2" />
                  <span className="text-muted-foreground text-xs tabular-nums" data-bga-progress>
                    {done}/{total}
                  </span>
                </div>
              )}
              <Link
                href={pageHref(resume.recordPage, { id: record.id }, {})}
                className={cn(buttonVariants({ size: "sm" }), "w-fit gap-1.5")}
                data-bga-action="resume"
              >
                <PlayCircle className="size-4" aria-hidden />
                Continue
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
