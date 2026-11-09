"use client";

import { Briefcase, CircleCheck, CircleDashed, CircleX, Info, RotateCw } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Stack } from "@/components/layout/Stack";
import { evaluationShotUrl } from "../../api/generations-api";
import { useEvaluation } from "../../hooks/use-evaluation";
import type { TEvaluationLine, TEvaluationReport, TTourPlayStep } from "../../types";

const RESULT_STYLE: Record<TEvaluationLine["result"], { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  pass: { label: "Met", variant: "default" },
  fail: { label: "Not met", variant: "destructive" },
  blocked: { label: "Blocked", variant: "secondary" },
  unbound: { label: "Not checked", variant: "outline" },
  "n/a": { label: "n/a", variant: "outline" },
};

const TOUR_RESULT: Record<TTourPlayStep["result"], { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  completed: { label: "Completed", variant: "default" },
  skipped: { label: "Skipped", variant: "secondary" },
  stuck: { label: "Stuck", variant: "destructive" },
  "not reached": { label: "Not reached", variant: "outline" },
};

const KIND_LABEL: Record<string, string> = {
  does: "Can do it",
  refused: "Wrong role refused",
  premature: "Not too early",
  status: "Status after",
  visible: "Can see it",
  hidden: "Hidden from others",
  effect: "Effect",
};

/** Story 26.6: the business evaluation of a generation, as information for the user (never its status, D4). */
export function BusinessTab({ id }: { id: string }) {
  const { evaluation, run } = useEvaluation(id);
  const state = evaluation.data;
  const data = state && state.status !== "NONE" ? state : null;
  if (evaluation.isPending) return <Skeleton className="h-64 w-full" />;
  const running = data?.status === "PENDING" || data?.status === "RUNNING";
  return (
    <Stack gap="lg">
      <Alert>
        <Info />
        <AlertTitle>Information only</AlertTitle>
        <AlertDescription>
          The app is checked against the business workflows written down before it was generated, as each role&apos;s demo
          user. The result never changes the generation&apos;s status and triggers no repair.
        </AlertDescription>
      </Alert>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => run.mutate()} disabled={run.isPending || running} data-bga-evaluation-run>
          {running || run.isPending ? <Spinner data-icon="inline-start" /> : <RotateCw data-icon="inline-start" />}
          {data ? "Run again" : "Run the evaluation"}
        </Button>
        {data && (
          <span className="text-sm text-muted-foreground">
            {data.status === "DONE" && data.finishedAt ? `Checked ${new Date(data.finishedAt).toLocaleString()}` : null}
            {running ? `Running${data.progress ? `: ${data.progress}` : "…"}` : null}
            {data.provider ? ` · ${data.provider}` : null}
          </span>
        )}
      </div>
      {data?.expectationsFrom && (
        <p className="text-sm text-muted-foreground" data-bga-evaluation-source>
          Checked against the workflows and expectations written for{" "}
          <Link href={`/generations/${data.expectationsFrom}?tab=business`} className="underline">
            {data.expectationsFrom}
          </Link>
          , bound to this app&apos;s own screens and API.
        </p>
      )}
      {!data && (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Briefcase />
            </EmptyMedia>
            <EmptyTitle>No evaluation yet</EmptyTitle>
            <EmptyDescription>
              It starts by itself once the previews are up, for apps drafted with business workflows.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      {data?.status === "FAILED" && (
        <Alert variant="destructive">
          <AlertTitle>The evaluation could not finish</AlertTitle>
          <AlertDescription>{data.error}</AlertDescription>
        </Alert>
      )}
      {data?.report && <Report id={id} report={data.report} />}
    </Stack>
  );
}

function Report({ id, report }: { id: string; report: TEvaluationReport }) {
  const score = report.score;
  const groups = useMemo(() => {
    const out = new Map<string, TEvaluationLine[]>();
    for (const line of report.lines.filter((item) => item.scored)) {
      const key = `${line.workflow} / ${line.path}`;
      out.set(key, [...(out.get(key) ?? []), line]);
    }
    return [...out.entries()];
  }, [report.lines]);
  const workflows = new Map((report.business.workflows ?? []).map((workflow) => [workflow.id, workflow.name]));
  return (
    <Stack gap="lg">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Figure label="Expectations met (of decided)" value={`${score.decidedPercent}%`} detail={`${score.met} of ${score.decided} decided`} />
        <Figure label="Not met" value={String(score.counts.fail)} detail="a checked expectation the app failed" />
        <Figure label="Not decided" value={String(score.counts.blocked + score.counts.unbound)} detail="blocked by an earlier step, or nothing to check it with" />
        <Figure
          label="Workflow paths completed"
          value={`${report.paths.filter((path) => path.completed).length} / ${report.paths.length}`}
          detail="end to end through the API"
        />
      </div>
      {report.summary?.summary && (
        <Card>
          <CardHeader>
            <CardTitle>Summary</CardTitle>
            <CardDescription>Written for the business owner from the checked results.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 text-sm">
            <p>{report.summary.summary}</p>
            {report.summary.values.length > 0 && (
              <ul className="flex flex-col gap-2">
                {report.summary.values.map((value) => (
                  <li key={value.id} className="flex gap-2">
                    <Badge variant={value.delivered === "yes" ? "default" : value.delivered === "partly" ? "secondary" : "destructive"}>
                      {value.delivered}
                    </Badge>
                    <span>
                      <strong>{report.business.values?.find((item) => item.id === value.id)?.value ?? value.id}</strong>: {value.evidence}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <TwoLists gaps={report.summary.gaps} improvements={report.summary.improvements} />
          </CardContent>
        </Card>
      )}
      {report.binding.problems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Review first: what could not be bound to the app</CardTitle>
            <CardDescription>Steps the app has nothing for, or names the draft got wrong.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-1 text-sm">
              {report.binding.problems.map((problem, index) => (
                <li key={index}>
                  <strong>{problem.what}</strong>: {problem.reason}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      {groups.map(([key, lines]) => {
        const [workflow, path] = key.split(" / ");
        const info = report.paths.find((item) => item.workflow === workflow && item.path === path);
        return (
          <Card key={key} data-bga-evaluation-path={key}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {info?.completed ? <CircleCheck className="text-primary" /> : <CircleX className="text-destructive" />}
                {workflows.get(workflow) ?? workflow}
                {path !== "main" && <span className="text-muted-foreground">({path})</span>}
              </CardTitle>
              {info?.stopped && <CardDescription>Stopped at {info.stopped}</CardDescription>}
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {lines.map((line, index) => (
                <details key={index} className="rounded-md border px-3 py-2 text-sm">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2">
                    <Badge variant={RESULT_STYLE[line.result].variant}>{RESULT_STYLE[line.result].label}</Badge>
                    <span className="text-muted-foreground">{KIND_LABEL[line.kind] ?? line.kind}</span>
                    <span>{line.expect}</span>
                  </summary>
                  <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    {line.evidence.call && (<><dt>Call</dt><dd className="font-mono">{line.evidence.call}</dd></>)}
                    {line.evidence.as && (<><dt>As</dt><dd>{line.evidence.as}</dd></>)}
                    {line.evidence.status != null && (<><dt>Answer</dt><dd>{line.evidence.status}</dd></>)}
                    {line.evidence.detail && (<><dt>Detail</dt><dd>{line.evidence.detail}</dd></>)}
                    {line.evidence.error && (<><dt>Error</dt><dd>{line.evidence.error}</dd></>)}
                    {line.evidence.response && (<><dt>Response</dt><dd className="font-mono break-all">{line.evidence.response}</dd></>)}
                  </dl>
                </details>
              ))}
            </CardContent>
          </Card>
        );
      })}
      {(report.tour ?? []).length > 0 && (
        <Card data-bga-evaluation-tour>
          <CardHeader>
            <CardTitle>The guided tour, played</CardTitle>
            <CardDescription>
              Each role&apos;s tour on the mock API: a step is completed when the walker did it as a user would, skipped
              when the tour itself skipped it, stuck when it could not be finished. Not part of the score.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            {(report.tour ?? []).map((play) => (
              <div key={play.login ?? play.role ?? "everyone"} className="flex flex-col gap-3">
                <h3 className="text-sm font-semibold">
                  {play.role ? `As ${play.role}` : "As everyone"}
                  {play.login && <span className="ml-1 font-mono text-xs font-normal text-muted-foreground">{play.login}</span>}
                </h3>
                {play.error && <p className="text-sm text-destructive">{play.error}</p>}
                {play.tours.map((tour) => (
                  <div key={tour.id} className="flex flex-col gap-2 rounded-md border p-3" data-bga-tour-play={`${play.role ?? "everyone"}/${tour.id}`}>
                    <div className="flex items-center gap-2 text-sm">
                      {tour.completed ? <CircleCheck className="size-4 text-primary" /> : <CircleDashed className="size-4 text-muted-foreground" />}
                      <strong>{tour.name ?? tour.id}</strong>
                      <span className="text-muted-foreground">
                        {tour.steps.filter((step) => step.result === "completed").length} / {tour.steps.length} steps
                      </span>
                    </div>
                    <ol className="flex flex-col gap-1.5 text-sm">
                      {tour.steps.map((step) => (
                        <li key={step.id} className="flex flex-col gap-1">
                          <span className="flex flex-wrap items-center gap-2">
                            <Badge variant={TOUR_RESULT[step.result]?.variant ?? "outline"}>{TOUR_RESULT[step.result]?.label ?? step.result}</Badge>
                            <span className="text-xs text-muted-foreground">{step.kind}</span>
                            <span>{step.title ?? step.id}</span>
                            {step.role && <span className="text-xs text-muted-foreground">({step.role})</span>}
                            {typeof step.ms === "number" && <span className="text-xs tabular-nums text-muted-foreground">{(step.ms / 1000).toFixed(1)} s</span>}
                          </span>
                          {step.reason && <span className="text-xs text-muted-foreground">{step.reason}</span>}
                          {step.file && (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img src={evaluationShotUrl(id, step.file.replace(/^shots\//, ""))} alt={`Stuck at ${step.title ?? step.id}`} className="max-w-md rounded-md border" loading="lazy" />
                          )}
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      {report.judged.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>The screens, step by step</CardTitle>
            <CardDescription>Opinions on each screen; they are not part of the score.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {report.judged.map((item) => (
              <figure key={item.file} className="flex flex-col gap-2 text-sm">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={evaluationShotUrl(id, item.file)} alt={`Screen for ${item.step ?? item.outcome}`} className="rounded-md border" loading="lazy" />
                <figcaption className="flex flex-col gap-1">
                  <span className="flex items-center gap-2">
                    {item.canDo || item.shows ? (
                      <Badge variant={(item.canDo ?? item.shows) === "yes" ? "default" : "secondary"}>{item.canDo ?? item.shows}</Badge>
                    ) : (
                      <CircleDashed className="size-4" />
                    )}
                    <strong>{item.step ?? `outcome for ${item.outcome}`}</strong>
                  </span>
                  {item.control && <span>Control: {item.control}</span>}
                  {(item.issue || item.note) && <span className="text-muted-foreground">{item.issue || item.note}</span>}
                </figcaption>
              </figure>
            ))}
          </CardContent>
        </Card>
      )}
    </Stack>
  );
}

function Figure({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-3xl tabular-nums">{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">{detail}</CardContent>
    </Card>
  );
}

function TwoLists({ gaps, improvements }: { gaps: string[]; improvements: string[] }) {
  if (gaps.length === 0 && improvements.length === 0) return null;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <h3 className="mb-1 font-medium">Gaps</h3>
        <ul className="list-disc pl-5">{gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>
      </div>
      <div>
        <h3 className="mb-1 font-medium">What the generator could do better</h3>
        <ul className="list-disc pl-5">{improvements.map((item, index) => <li key={index}>{item}</li>)}</ul>
      </div>
    </div>
  );
}
