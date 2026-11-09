"use client";

import { CircleCheck, CircleDashed, CircleDot, MinusCircle, UserRound } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import type { TTour, TTourStep } from "../app";
import { t } from "../messages";
import { stepState, type TProgress } from "./progress";

export type TChecklistProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tours: TTour[];
  progress: TProgress;
  role: string | null;
  /** The tour that is running (or was last running) and its step. */
  current: { tour: string; step: string } | null;
  onContinue: (tour: TTour, stepIndex: number) => void;
  onRestart: (tour: TTour) => void;
};

export type TStepMark = "done" | "skipped" | "current" | "waiting" | "todo";

/** How a step stands for this user: done, skipped, the current one, waiting for another role, or still to do. */
export function stepMark(progress: TProgress, tour: TTour, step: TTourStep, role: string | null, current: TChecklistProps["current"]): TStepMark {
  const state = stepState(progress, tour.id, step.id);
  if (state) return state;
  if (current && current.tour === tour.id && current.step === step.id) return "current";
  if (role && step.role && step.role !== role) return "waiting";
  return "todo";
}

/** Steps done or skipped, of all the steps the user plays (another role's steps are not theirs to do). */
export function tourCounts(progress: TProgress, tour: TTour, role: string | null): { done: number; total: number } {
  const mine = tour.steps.filter((step) => !step.automatic && !step.skip && (!role || !step.role || step.role === role));
  const done = mine.filter((step) => stepState(progress, tour.id, step.id)).length;
  return { done, total: mine.length };
}

function Mark({ mark }: { mark: TStepMark }) {
  const icon = {
    done: <CircleCheck className="size-4 text-primary" aria-hidden />,
    skipped: <MinusCircle className="size-4 text-muted-foreground" aria-hidden />,
    current: <CircleDot className="size-4 text-primary" aria-hidden />,
    waiting: <UserRound className="size-4 text-muted-foreground" aria-hidden />,
    todo: <CircleDashed className="size-4 text-muted-foreground" aria-hidden />,
  }[mark];
  return icon;
}

function markLabel(mark: TStepMark, step: TTourStep): string {
  if (mark === "done") return t("tourDone2");
  if (mark === "skipped") return t("tourSkipped");
  if (mark === "current") return t("tourCurrent");
  if (mark === "waiting") return t("tourWaitingRole", { role: step.role ?? step.actor });
  return t("tourTodo");
}

/** Story 28.5: the checklist of the user's workflows (a sheet from the "Guide" button; a bottom drawer on phones):
 *  each tour's steps with their state and role, "Continue" from the current step, "Start again". */
export function Checklist({ open, onOpenChange, tours, progress, role, current, onContinue, onRestart }: TChecklistProps) {
  const mobile = useIsMobile();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side={mobile ? "bottom" : "right"} className={cn("overflow-y-auto", mobile && "max-h-[85svh]")} data-bga-checklist>
        <SheetHeader>
          <SheetTitle>{t("tourChecklist")}</SheetTitle>
          <SheetDescription className="sr-only">{t("tourChecklist")}</SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-6 px-4 pb-6">
          {tours.map((tour) => {
            const counts = tourCounts(progress, tour, role);
            const finished = progress.doneTours.includes(tour.id) || (counts.total > 0 && counts.done >= counts.total);
            const firstOpen = tour.steps.findIndex((step) => stepMark(progress, tour, step, role, current) === "todo" || stepMark(progress, tour, step, role, current) === "current");
            const nextRole = tour.steps.find((step) => stepMark(progress, tour, step, role, current) === "waiting")?.role;
            return (
              <section key={tour.id} className="flex flex-col gap-3" data-bga-checklist-tour={tour.id}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold">{tour.name}</h3>
                  <Badge variant={finished ? "default" : "secondary"}>
                    {finished ? t("tourTourDone") : t("tourProgress", { done: counts.done, total: counts.total })}
                  </Badge>
                </div>
                <ol className="flex flex-col gap-1.5">
                  {tour.steps.map((step) => {
                    const mark = stepMark(progress, tour, step, role, current);
                    return (
                      <li
                        key={step.id}
                        className={cn("flex items-start gap-2 rounded-md px-2 py-1.5 text-sm", mark === "current" && "bg-accent")}
                        data-bga-checklist-step={step.id}
                        data-state={mark}
                      >
                        <span className="mt-0.5 shrink-0">
                          <Mark mark={mark} />
                        </span>
                        <span className="flex min-w-0 flex-1 flex-col">
                          <span className={cn(mark === "done" && "text-muted-foreground line-through")}>{step.title}</span>
                          <span className="text-xs text-muted-foreground">
                            {step.actor}
                            {" · "}
                            {markLabel(mark, step)}
                          </span>
                        </span>
                      </li>
                    );
                  })}
                </ol>
                <div className="flex flex-wrap items-center gap-2">
                  {!finished && firstOpen >= 0 && (
                    <Button size="sm" onClick={() => onContinue(tour, firstOpen)} data-bga-checklist-continue={tour.id}>
                      {t("tourContinue")}
                    </Button>
                  )}
                  <Button size="sm" variant="outline" onClick={() => onRestart(tour)} data-bga-checklist-restart={tour.id}>
                    {t("tourStartAgain")}
                  </Button>
                  {!finished && firstOpen < 0 && nextRole && (
                    <span className="text-xs text-muted-foreground">{t("tourNextRole", { role: nextRole })}</span>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      </SheetContent>
    </Sheet>
  );
}
