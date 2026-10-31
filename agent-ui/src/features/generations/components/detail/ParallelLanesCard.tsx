"use client";

import { Activity, Globe, PlugZap, RotateCcw, Server } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Stack } from "@/components/layout/Stack";
import { cn } from "@/lib/utils";
import type { TNodeProgress } from "../../lib/node-states";
import { formatStep } from "../../lib/status";
import type { TGenerationEvent, TGenerationMode, TLane, TLanes, TLaneStatus } from "../../types";

const LANE_META: Record<TLane, { label: string; icon: LucideIcon; description: string }> = {
  backend: {
    label: "Backend Lane",
    icon: Server,
    description: "FastAPI server, PostgreSQL schema, Alembic migrations and API tests",
  },
  frontend: {
    label: "Frontend Lane",
    icon: Globe,
    description: "Next.js UI, Tailwind tokens, MSW mocks and page components",
  },
  integration: {
    label: "Integration Lane",
    icon: PlugZap,
    description: "Contract conformance verification, backend health check and live API switch",
  },
};

const STATUS_VARIANT: Record<TLaneStatus, "default" | "secondary" | "destructive" | "outline"> = {
  PENDING: "outline",
  RUNNING: "default",
  VALIDATING: "default",
  REPAIRING: "secondary",
  COMPLETED: "default",
  FAILED: "destructive",
  SKIPPED: "outline",
};

const STATUS_CLASS: Record<TLaneStatus, string> = {
  PENDING: "border-border text-muted-foreground",
  RUNNING: "bg-info text-info-foreground animate-pulse",
  VALIDATING: "bg-info text-info-foreground",
  REPAIRING: "bg-warning text-warning-foreground",
  COMPLETED: "bg-success text-success-foreground",
  FAILED: "bg-destructive text-destructive-foreground",
  SKIPPED: "border-dashed text-muted-foreground",
};

type ParallelLanesCardProps = {
  mode: TGenerationMode;
  lanes: TLanes;
  events: TGenerationEvent[];
  progress: Record<string, TNodeProgress>;
  repairAttempts: number;
  frontendRepairAttempts: number;
  maxRepairAttempts: number;
  className?: string;
};

export function ParallelLanesCard({
  mode,
  lanes,
  events,
  progress,
  repairAttempts,
  frontendRepairAttempts,
  maxRepairAttempts,
  className,
}: ParallelLanesCardProps) {
  const visibleLanes: TLane[] =
    mode === "dynamic"
      ? ["backend", "frontend", "integration"]
      : mode === "static"
        ? ["frontend"]
        : ["backend"];

  return (
    <Card className={cn("overflow-hidden border bg-card/60 shadow-xs", className)}>
      <CardContent className="p-4">
        <div
          className={cn(
            "grid gap-4",
            visibleLanes.length === 3 ? "grid-cols-1 md:grid-cols-3" : "grid-cols-1",
          )}
        >
          {visibleLanes.map((lane) => {
            const meta = LANE_META[lane];
            const Icon = meta.icon;
            const status = (lanes[lane] as TLaneStatus) ?? "PENDING";

            // Derive lane's current step and details
            let currentStepName: string | null = null;
            let note: string | null = null;

            if (lane === "integration") {
              const liveEvt = events.findLast((e) => e.type === "integration.switched_to_live");
              const keptEvt = events.findLast((e) => e.type === "integration.kept_mocks");
              if (liveEvt) {
                currentStepName = "Switched to live API";
              } else if (keptEvt) {
                currentStepName = "Kept on mock API";
                note = typeof keptEvt.payload.reason === "string" ? keptEvt.payload.reason : null;
              } else if (status === "RUNNING") {
                currentStepName = "Checking backend readiness";
              } else if (status === "COMPLETED") {
                currentStepName = "Integration smoke passed";
              } else if (status === "SKIPPED") {
                currentStepName = "Integration skipped";
                const skipEvt = events.findLast((e) => e.type === "lane.changed" && e.lane === "integration");
                note = typeof skipEvt?.payload.reason === "string" ? skipEvt.payload.reason : "Backend lane incomplete";
              }
            } else {
              // Find active running node in this lane
              const laneEvents = events.filter((e) => e.lane === lane);
              const lastStart = laneEvents.findLast((e) => e.type === "step.started");
              const lastFinish = laneEvents.findLast((e) => e.type === "step.finished");

              if (status === "RUNNING" || status === "VALIDATING" || status === "REPAIRING") {
                // Find currently running nodes in this lane from progress
                const runningNodes = Object.entries(progress)
                  .filter(([node, p]) => {
                    if (p.state !== "running") return false;
                    const eventMatchesLane = events.some((e) => e.step === node && e.lane === lane);
                    return eventMatchesLane || node.includes(lane);
                  })
                  .map(([node]) => node);

                if (runningNodes.length > 1) {
                  currentStepName = runningNodes.map(formatStep).join(" & ");
                } else if (runningNodes.length === 1) {
                  currentStepName = formatStep(runningNodes[0]);
                } else {
                  currentStepName = lastStart?.step ? formatStep(lastStart.step) : "In progress";
                }
              } else if (status === "COMPLETED") {
                currentStepName = "Lane completed";
              } else if (status === "FAILED") {
                currentStepName = lastFinish?.step ? `Failed at ${formatStep(lastFinish.step)}` : "Failed";
              }
            }

            const laneRepairs =
              lane === "backend"
                ? repairAttempts
                : lane === "frontend"
                  ? frontendRepairAttempts
                  : 0;

            return (
              <div
                key={lane}
                className={cn(
                  "flex flex-col justify-between rounded-lg border bg-card p-3 shadow-2xs transition-all",
                  status === "RUNNING" && "border-info/40 bg-info/5 ring-1 ring-info/20",
                )}
              >
                <Stack gap="xs">
                  <Stack direction="row" justify="between" align="center">
                    <Stack direction="row" gap="xs" align="center">
                      <Icon className="size-4 text-muted-foreground" />
                      <span className="text-sm font-semibold tracking-tight">{meta.label}</span>
                    </Stack>
                    <Badge variant={STATUS_VARIANT[status]} className={cn("text-[10px] font-medium", STATUS_CLASS[status])}>
                      {status.toLowerCase()}
                    </Badge>
                  </Stack>
                  <p className="line-clamp-1 text-xs text-muted-foreground">{meta.description}</p>
                </Stack>

                <div className="mt-3 border-t pt-2">
                  <Stack direction="row" justify="between" align="center" className="text-xs">
                    <span className="flex items-center gap-1.5 font-medium truncate">
                      <Activity className={cn("size-3.5 shrink-0", status === "RUNNING" ? "animate-pulse text-info" : "text-muted-foreground")} />
                      <span className="truncate">
                        {currentStepName ? formatStep(currentStepName) : "Pending"}
                      </span>
                    </span>
                    {lane !== "integration" && (
                      <Tooltip>
                        <TooltipTrigger render={<span />}>
                          <span
                            className={cn(
                              "inline-flex items-center gap-1 tabular-nums rounded px-1.5 py-0.5",
                              laneRepairs > 0 ? "bg-warning/15 text-warning font-medium" : "text-muted-foreground",
                            )}
                          >
                            <RotateCcw className="size-3" />
                            {laneRepairs} / {maxRepairAttempts}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>
                          {laneRepairs} repair attempt{laneRepairs === 1 ? "" : "s"} out of {maxRepairAttempts} max
                        </TooltipContent>
                      </Tooltip>
                    )}
                  </Stack>
                  {note && (
                    <p className="mt-1.5 line-clamp-2 rounded bg-muted/60 p-1.5 text-[11px] text-muted-foreground">
                      {note}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
