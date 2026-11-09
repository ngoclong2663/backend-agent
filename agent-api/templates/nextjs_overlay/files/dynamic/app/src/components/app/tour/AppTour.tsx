"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Compass } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ACTIONS, EVENTS, Joyride, STATUS, type Controls, type EventData, type Step } from "react-joyride";
import { Button } from "@/components/ui/button";
import { loadRuntimeConfig } from "@/lib/runtime-config";
import { app, listOf, type TAppForm, type TTour, type TTourStep, type TTourStepKind } from "../app";
import { fetchOperation } from "../bindings";
import { formMethods, isBlank, onForms } from "../form/registry";
import { t } from "../messages";
import { signInDemo, useSession } from "../plugins";
import { onSignal, type TSignal } from "../signals";
import { Checklist } from "./Checklist";
import {
  firstOpenStep,
  loadProgress,
  markStep,
  markTourDone,
  readHandoff,
  resetTour,
  saveProgress,
  setCurrent,
  tourOff,
  writeHandoff,
  type TProgress,
} from "./progress";
import { readyRecord, stepPlace } from "./records";

/** Story 26.4 gave every app with business workflows a guided tour. Epic 28 makes it a tour the user **does**:
 *  - a `do` step lets the user use the highlighted control and completes on the kit's signal that its operation
 *    succeeded (Story 28.2), never on Next; it can always be skipped, and the app is never blocked (D7);
 *  - on a form it walks the required fields and offers "Fill with an example" from the contract (28.3), but the user
 *    presses the submit button (D3: the tour never submits or performs anything);
 *  - a step on a record opens one whose allowed actions include the step's (28.4), else names the step that makes one;
 *  - progress is a checklist per user and step (28.5); in a demo, "Continue as <role>" follows a workflow across roles.
 *  `look` steps (a section that shows data) and `note` steps (another role, or done by the app) keep Next, as 26.4. */

const LIVE_NOTED = "bga-tour-live-noted";
const MARK = "data-bga-tour-current";

function pattern(route: string): RegExp {
  const body = route
    .split("/")
    .map((part) => (part.startsWith("[") ? "[^/]+" : part.replace(/[.*+?^${}()|\\]/g, "\\$&")))
    .join("/");
  return new RegExp(`^${body}/?$`);
}

export function tourTarget(step: TTourStep): HTMLElement | null {
  if (!step.target || typeof document === "undefined") return null;
  const section = `[data-bga-section="${step.page}/${step.target.section}"]`;
  const action = step.target.action ? document.querySelector<HTMLElement>(`${section} [data-bga-action="${step.target.action}"]`) : null;
  return action ?? document.querySelector<HTMLElement>(section);
}

async function waitFor<T>(find: () => T | null | undefined, ms = 6000): Promise<T | null> {
  const started = Date.now();
  let found = find();
  while (!found && Date.now() - started < ms) {
    await new Promise((resolve) => setTimeout(resolve, 150));
    found = find();
  }
  return found ?? null;
}

/** A link on the page to one record under `prefix`: the id of the first one, as the kit's lists render their rows. */
function recordLink(prefix: string): string | null {
  const base = prefix === "/" ? "" : prefix;
  for (const anchor of Array.from(document.querySelectorAll<HTMLAnchorElement>("a[href]"))) {
    const path = new URL(anchor.href, window.location.origin).pathname;
    if (!path.startsWith(`${base}/`)) continue;
    const rest = path.slice(base.length + 1);
    if (rest && !rest.includes("/") && rest !== "new") return rest;
  }
  return null;
}

/** The kind of a step for the signed-in user: another role's step is a note for them (28.1 D2, decided here). */
export function effectiveKind(step: TTourStep, role: string | null): TTourStepKind {
  if (role && step.role && step.role !== role) return "note";
  if (step.kind) return step.kind;
  if (step.automatic || step.skip || !step.target) return "note";
  return step.target.action ? "do" : "look";
}

/** The form a step submits, when its target is a form's submit button. */
function stepForm(step: TTourStep): string | undefined {
  if (step.target?.action !== "submit" || !step.page) return undefined;
  return app.pages[step.page]?.sections.find((section) => section.id === step.target?.section)?.form;
}

function fieldElement(formId: string, name: string): HTMLElement | null {
  const control = document.getElementById(`${formId}-${name}`);
  return control?.closest<HTMLElement>('[data-slot="field"]') ?? control;
}

function submitButton(formId: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`form[data-bga-form="${formId}"] [data-bga-action="submit"]`);
}

function onScreen(formId: string): boolean {
  return Boolean(document.querySelector(`form[data-bga-form="${formId}"]`));
}

type TWalk = { form: string; required: string[]; index: number; errorField?: string };

function requiredFields(form: TAppForm): string[] {
  return form.fields.filter((field) => !field.hidden && field.required && field.value === undefined).map((field) => field.name);
}

/** Story 28.3: fills the empty fields of a form from its example, picks the first option of each required picker and
 *  leaves uploads to the user. Never overwrites what the user typed, never submits. Returns the upload fields left. */
export async function fillExample(formId: string): Promise<string[]> {
  const form = app.forms[formId];
  const methods = formMethods(formId);
  if (!form || !methods) return [];
  const values = methods.getValues();
  const uploads: string[] = [];
  for (const field of form.fields) {
    if (field.hidden || !isBlank(values[field.name])) continue;
    if (field.upload) {
      if (field.required) uploads.push(field.name);
      continue;
    }
    if (field.reference) {
      if (!field.required) continue;
      try {
        const params: Record<string, unknown> = field.reference.limitParam ? { [field.reference.limitParam]: field.reference.pageSize ?? 50 } : {};
        const first = listOf(await fetchOperation(field.reference.listOperation, params)).records[0];
        if (first?.id !== undefined) methods.setValue(field.name, first.id, { shouldValidate: true, shouldDirty: true });
      } catch {
        // the picker stays for the user
      }
      continue;
    }
    const example = form.example?.[field.name];
    if (example !== undefined) methods.setValue(field.name, example, { shouldValidate: true, shouldDirty: true });
  }
  return uploads;
}

type TStepContentProps = {
  tour: TTour;
  step: TTourStep;
  kind: TTourStepKind;
  blocked?: string;
  walk: TWalk | null;
  live: boolean;
  needsTitle?: { title: string; actor: string; role: string | null; index: number };
  demoLogin?: string;
  continueFailed?: string | null;
  onSkip: () => void;
  onNextField: () => void;
  onFill: () => void;
  onGoTo: (index: number) => void;
  onContinueAs: (role: string, login: string) => void;
};

function StepContent(props: TStepContentProps) {
  const { tour, step, kind, blocked, walk, live, needsTitle, demoLogin, continueFailed } = props;
  const form = walk ? app.forms[walk.form] : undefined;
  const field = walk && form ? form.fields.find((candidate) => candidate.name === (walk.errorField ?? walk.required[walk.index])) : undefined;
  const otherRole = Boolean(step.role) && kind === "note" && !step.automatic && !step.skip && !blocked;
  return (
    <div
      className="flex flex-col gap-2 text-left"
      data-bga-tour-step={step.id}
      data-bga-tour-kind={blocked ? "note" : kind}
      data-bga-tour-tour={tour.id}
      data-bga-tour-blocked={blocked || undefined}
    >
      {step.automatic ? (
        <p>{t("tourAutomatic", { action: step.title })}</p>
      ) : otherRole ? (
        <p>{t("tourOtherRole", { actor: step.actor, action: step.title })}</p>
      ) : (
        <p>{step.title}</p>
      )}
      {blocked && !needsTitle && <p className="text-xs opacity-80">{t("tourTargetMissing", { reason: blocked })}</p>}
      {needsTitle && (
        <p className="text-xs opacity-80">
          {needsTitle.role && step.role && needsTitle.role !== step.role
            ? t("tourReadyAfterRole", { actor: needsTitle.actor, step: needsTitle.title })
            : t("tourReadyAfter", { step: needsTitle.title })}
        </p>
      )}
      {kind === "do" && !blocked && (
        <>
          {live && <p className="text-xs font-medium" data-bga-tour-live>{t("tourLiveNotice")}</p>}
          {walk && field && (
            <p className="text-sm">
              <strong>{field.label ?? field.name}</strong>
              {field.help ? ` — ${field.help}` : ""}
              {walk.errorField ? ` ${t("tourFixField")}` : ""}
            </p>
          )}
          {walk && !field && walk.index >= walk.required.length && (
            <p className="text-sm">
              {t("tourOptionalFields")} {t("tourThenSubmit", { label: form?.submitLabel ?? t("save") })}
            </p>
          )}
          <p className="text-xs font-medium uppercase tracking-wide opacity-70">{t("tourYourTurn")}</p>
          <div className="flex flex-wrap items-center gap-2">
            {walk && (
              <Button type="button" size="sm" variant="secondary" onClick={props.onFill} data-bga-tour-fill>
                {t("tourFillExample")}
              </Button>
            )}
            {walk && field && !walk.errorField && (
              <Button type="button" size="sm" variant="ghost" onClick={props.onNextField} data-bga-tour-next-field>
                {t("tourNextField")}
              </Button>
            )}
            <button type="button" className="text-xs underline underline-offset-4 opacity-80 hover:opacity-100" onClick={props.onSkip} data-bga-tour-skip>
              {t("tourSkipStep")}
            </button>
          </div>
        </>
      )}
      {needsTitle && (
        <div className="flex flex-wrap items-center gap-2">
          {(!needsTitle.role || needsTitle.role === step.role) && (
            <Button type="button" size="sm" variant="secondary" onClick={() => props.onGoTo(needsTitle.index)} data-bga-tour-goto={needsTitle.index}>
              {t("tourGoToStep")}
            </Button>
          )}
        </div>
      )}
      {(otherRole || (needsTitle?.role && needsTitle.role !== step.role)) && demoLogin && (
        <div className="flex flex-col gap-1">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => props.onContinueAs((needsTitle?.role && needsTitle.role !== step.role ? needsTitle.role : step.role) ?? "", demoLogin)}
            data-bga-tour-continue-as={(needsTitle?.role && needsTitle.role !== step.role ? needsTitle.role : step.role) ?? ""}
          >
            {t("tourContinueAs", { role: (needsTitle?.role && needsTitle.role !== step.role ? needsTitle.role : step.role) ?? "" })}
          </Button>
          {continueFailed && <p className="text-xs text-destructive">{continueFailed}</p>}
        </div>
      )}
    </div>
  );
}

export default function AppTour() {
  const workflows = app.workflows;
  const session = useSession();
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const role = session.enabled ? ((session.user?.role as string | undefined) ?? null) : null;
  const signedIn = !session.enabled || Boolean(session.user);
  const tours = useMemo(
    () => (workflows?.tours ?? []).filter((tour) => !role || tour.roles.length === 0 || tour.roles.includes(role)),
    [workflows, role],
  );
  const who = `${role ?? "everyone"}:${String(session.user?.id ?? "")}`;
  const [tourIndex, setTourIndex] = useState(0);
  const [stepIndex, setStepIndex] = useState(0);
  const [run, setRun] = useState(false);
  const [checklist, setChecklist] = useState(false);
  const [progress, setProgressState] = useState<TProgress | null>(null);
  const [blocked, setBlocked] = useState<Record<string, string>>({});
  const [needs, setNeeds] = useState<Record<string, boolean>>({});
  const [walk, setWalk] = useState<TWalk | null>(null);
  const [live, setLive] = useState(false);
  const [continueFailed, setContinueFailed] = useState<string | null>(null);
  const focus = useRef<HTMLElement | null>(null);
  const controls = useRef<Controls | null>(null);
  const lastRecord = useRef<Record<string, unknown>>({});
  const stepRef = useRef<{ tour: TTour; step: TTourStep; kind: TTourStepKind; index: number } | null>(null);
  const walkRef = useRef<TWalk | null>(null);
  walkRef.current = walk;

  const tour = tours[tourIndex % Math.max(tours.length, 1)];

  // -- progress ---------------------------------------------------------------------------------------------------

  useEffect(() => {
    if (!workflows || !session.ready) return;
    setProgressState(loadProgress(who, workflows));
  }, [workflows, who, session.ready]);

  const setProgress = useCallback(
    (next: (progress: TProgress) => TProgress) => {
      setProgressState((current) => {
        if (!current) return current;
        const updated = next(current);
        saveProgress(who, updated);
        return updated;
      });
    },
    [who],
  );

  useEffect(() => {
    loadRuntimeConfig().then((config) => setLive(!config.mockApi));
  }, []);

  // -- starting -----------------------------------------------------------------------------------------------------

  const start = useCallback(
    (index: number, at?: number) => {
      const chosen = tours[index];
      if (!chosen || !progress) return;
      const from = at ?? firstOpenStep(progress, chosen);
      setTourIndex(index);
      setStepIndex(Math.min(from, chosen.steps.length));
      setBlocked({});
      setNeeds({});
      setWalk(null);
      focus.current = null;
      setChecklist(false);
      setRun(false);
      setTimeout(() => setRun(true), 50);
    },
    [tours, progress],
  );

  useEffect(() => {
    // first sign-in of this user and role: once, from the first step not done, never on the sign-in pages themselves
    if (!session.ready || !signedIn || tours.length === 0 || run || !progress) return;
    if (pathname?.startsWith("/login") || pathname?.startsWith("/register")) return;
    if (tourOff()) return;
    const handoff = readHandoff();
    if (handoff) {
      const index = tours.findIndex((candidate) => candidate.id === handoff.tour);
      const at = index >= 0 ? tours[index].steps.findIndex((step) => step.id === handoff.step) : -1;
      writeHandoff(null);
      if (index >= 0 && at >= 0) {
        const timer = setTimeout(() => start(index, at), 800);
        return () => clearTimeout(timer);
      }
    }
    const open = tours.findIndex((candidate) => !progress.doneTours.includes(candidate.id) && firstOpenStep(progress, candidate) < candidate.steps.length);
    if (open < 0 || progress.current) return; // every tour done, or the user already started one (the Guide continues)
    const timer = setTimeout(() => start(open), 800);
    return () => clearTimeout(timer);
  }, [session.ready, signedIn, tours, pathname, run, progress, start]);

  // -- the steps ----------------------------------------------------------------------------------------------------

  const push = useCallback((href: string) => router.push(href), [router]);

  const advance = useCallback(
    (delta = 1) => {
      setWalk(null);
      focus.current = null;
      setStepIndex((index) => Math.max(0, index + delta));
    },
    [],
  );

  const finish = useCallback(() => {
    if (tour) setProgress((current) => markTourDone(current, tour.id));
    setRun(false);
  }, [tour, setProgress]);

  const skipStep = useCallback(() => {
    const current = stepRef.current;
    if (!current) return;
    setProgress((progress) => markStep(progress, current.tour.id, current.step.id, current.step.operationId, "skipped"));
    advance();
  }, [setProgress, advance]);

  const completeStep = useCallback(
    (record?: unknown) => {
      const current = stepRef.current;
      if (!current) return;
      const { entity } = stepPlace(current.step);
      if (entity && record !== undefined && record !== null) lastRecord.current[entity] = record;
      setProgress((progress) => markStep(progress, current.tour.id, current.step.id, current.step.operationId, "done"));
      setTimeout(() => advance(), 500); // the page settles (a toast, a navigation) before the next step shows
    },
    [setProgress, advance],
  );

  const startWalk = useCallback((formId: string) => {
    const form = app.forms[formId];
    if (!form) return;
    const required = requiredFields(form);
    const next: TWalk = { form: formId, required, index: 0 };
    walkRef.current = next;
    setWalk(next);
    focus.current = required.length ? fieldElement(formId, required[0]) : submitButton(formId);
    controls.current?.replay();
  }, []);

  const nextField = useCallback(() => {
    const current = walkRef.current;
    if (!current) return;
    const index = Math.min(current.index + 1, current.required.length);
    const next = { ...current, index, errorField: undefined };
    walkRef.current = next;
    setWalk(next);
    focus.current = index < current.required.length ? fieldElement(current.form, current.required[index]) : submitButton(current.form);
    controls.current?.replay();
  }, []);

  const fill = useCallback(async () => {
    const current = walkRef.current;
    if (!current) return;
    const uploads = await fillExample(current.form);
    const next = { ...current, index: current.required.length, errorField: uploads[0] };
    walkRef.current = next;
    setWalk(next);
    focus.current = uploads[0] ? fieldElement(current.form, uploads[0]) : submitButton(current.form);
    controls.current?.replay();
  }, []);

  const goTo = useCallback((index: number) => {
    setWalk(null);
    focus.current = null;
    setStepIndex(index);
  }, []);

  const continueAs = useCallback(
    async (nextRole: string, login: string) => {
      const current = stepRef.current;
      if (!current) return;
      setContinueFailed(null);
      writeHandoff({ tour: current.tour.id, step: current.step.id });
      setRun(false);
      const ok = await signInDemo(login, queryClient);
      if (!ok) {
        writeHandoff(null);
        setContinueFailed(t("tourContinueAsFailed", { role: nextRole }));
        setTimeout(() => setRun(true), 50);
      }
    },
    [queryClient],
  );

  // Story 28.2: the kit's signals complete a `do` step, move the spotlight into a dialog, walk the fields
  useEffect(() => {
    if (!run) return;
    return onSignal((received: TSignal) => {
      const current = stepRef.current;
      if (!current || current.kind !== "do") return;
      const step = current.step;
      if (received.kind === "operation" && received.operationId && received.operationId === step.operationId) {
        completeStep(received.record);
      } else if (received.kind === "dialog" && received.operationId === step.operationId && received.form) {
        const formId = received.form;
        waitFor(() => (onScreen(formId) ? true : null), 3000).then((shown) => {
          if (shown && stepRef.current?.step.id === step.id) startWalk(formId);
        });
      } else if (received.kind === "field" && walkRef.current && received.form === walkRef.current.form) {
        const active = walkRef.current;
        if (!active.errorField && received.field === active.required[active.index]) nextField();
      } else if (received.kind === "error" && received.operationId === step.operationId) {
        const active = walkRef.current;
        const formId = received.form ?? active?.form;
        const first = received.fields?.[0];
        if (formId && first) {
          const next: TWalk = { form: formId, required: active?.required ?? [], index: active?.required.length ?? 0, errorField: first };
          walkRef.current = next;
          setWalk(next);
          focus.current = fieldElement(formId, first);
          controls.current?.replay();
        }
      }
    });
  }, [run, completeStep, startWalk, nextField]);

  const demoLoginOf = useCallback(
    (wanted: string | null | undefined) => (wanted ? app.auth?.demoUsers.find((user) => user.role === wanted)?.login : undefined),
    [],
  );

  const steps: Step[] = useMemo(() => {
    if (!tour) return [];
    const out: Step[] = tour.steps.map((step, index) => {
      const kind = effectiveKind(step, role);
      const reason = blocked[step.id];
      const needsStep = needs[step.id] && step.needs ? tour.steps.findIndex((candidate) => candidate.id === step.needs?.step) : -1;
      const needsTitle =
        needsStep >= 0
          ? { title: tour.steps[needsStep].title, actor: tour.steps[needsStep].actor, role: tour.steps[needsStep].role, index: needsStep }
          : undefined;
      const otherRole = kind === "note" && Boolean(step.role) && !step.automatic && !step.skip;
      const demoLogin = demoLoginOf(needsTitle && needsTitle.role !== step.role ? needsTitle.role : otherRole ? step.role : null);
      const content = (
        <StepContent
          tour={tour}
          step={step}
          kind={kind}
          blocked={reason}
          walk={walk && stepRef.current?.step.id === step.id ? walk : null}
          live={live}
          needsTitle={needsTitle}
          demoLogin={demoLogin}
          continueFailed={continueFailed}
          onSkip={skipStep}
          onNextField={nextField}
          onFill={() => void fill()}
          onGoTo={goTo}
          onContinueAs={(nextRole, login) => void continueAs(nextRole, login)}
        />
      );
      const centered = kind === "note" || Boolean(reason);
      if (centered) {
        return { id: step.id, target: "body", placement: "center" as const, content, buttons: ["back", "skip", "primary"] };
      }
      return {
        id: step.id,
        title: step.actor,
        content,
        target: () => focus.current ?? tourTarget(step) ?? document.body,
        placement: "auto" as const,
        buttons: kind === "do" ? ["back"] : ["back", "skip", "primary"],
        blockTargetInteraction: false,
        before: async () => {
          const route = step.route;
          if (route && !pattern(route).test(window.location.pathname)) {
            const opened = await openRoute(route, step, kind, push, lastRecord.current, (why) => {
              setBlocked((current) => ({ ...current, [step.id]: why }));
            });
            if (!opened) {
              if (step.needs) setNeeds((current) => ({ ...current, [step.id]: true }));
              return;
            }
          } else if (route && kind === "do" && route.includes("[") && step.needs) {
            // on a record page already: check that this record allows the step, else look for one that does
            const here = window.location.pathname.split("/").filter(Boolean).pop();
            const ready = await readyRecord(step, [lastRecord.current[stepPlace(step).entity ?? ""], here]);
            if ("none" in ready) {
              setBlocked((current) => ({ ...current, [step.id]: t("tourNotFound") }));
              setNeeds((current) => ({ ...current, [step.id]: true }));
              return;
            }
            if (ready.id !== here) {
              push(route.replace(/\[[A-Za-z0-9_]+\]$/, ready.id));
            }
          }
          const found = await waitFor(() => tourTarget(step));
          if (!found) {
            setBlocked((current) => ({ ...current, [step.id]: t("tourNotFound") }));
            return;
          }
          const formId = stepForm(step);
          if (kind === "do" && formId && onScreen(formId) && walkRef.current?.form !== formId) {
            const form = app.forms[formId];
            const required = form ? requiredFields(form) : [];
            const next: TWalk = { form: formId, required, index: 0 };
            walkRef.current = next;
            setWalk(next);
            focus.current = required.length ? fieldElement(formId, required[0]) : submitButton(formId);
          }
        },
      };
    });
    if (tour.outcome) {
      out.push({ target: "body", placement: "center", id: "outcome", content: <span data-bga-tour-step="outcome" data-bga-tour-kind="look">{t("tourDoneWhen", { outcome: tour.outcome })}</span>, buttons: ["back", "primary"] });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `walk` is read through its ref in the hooks
  }, [tour, role, blocked, needs, walk, live, continueFailed, push, skipStep, nextField, fill, goTo, continueAs, demoLoginOf]);

  // the step on screen, for the signals and the markers
  useEffect(() => {
    if (!tour || !run) {
      stepRef.current = null;
      return;
    }
    const step = tour.steps[stepIndex];
    if (!step) {
      stepRef.current = null;
      return;
    }
    stepRef.current = { tour, step, kind: effectiveKind(step, role), index: stepIndex };
    setProgress((current) => setCurrent(current, { tour: tour.id, step: step.id }));
  }, [tour, run, stepIndex, role, setProgress]);

  // Story 28.6: the control a `do` step points at carries a marker (the evaluation's walker clicks it)
  useEffect(() => {
    if (!run) return;
    const timer = setInterval(() => {
      const current = stepRef.current;
      const wanted = current && current.kind === "do" && !blocked[current.step.id] ? (focus.current ?? tourTarget(current.step)) : null;
      for (const marked of Array.from(document.querySelectorAll(`[${MARK}]`))) if (marked !== wanted) marked.removeAttribute(MARK);
      wanted?.setAttribute(MARK, "");
    }, 300);
    return () => {
      clearInterval(timer);
      for (const marked of Array.from(document.querySelectorAll(`[${MARK}]`))) marked.removeAttribute(MARK);
    };
  }, [run, blocked, stepIndex, walk]);

  const onEvent = useCallback(
    (data: EventData, joyride: Controls) => {
      controls.current = joyride;
      if (data.type === EVENTS.STEP_AFTER) {
        if (data.action === ACTIONS.NEXT) {
          const current = stepRef.current;
          if (current && current.kind !== "do") {
            setProgress((progress) => markStep(progress, current.tour.id, current.step.id, current.step.operationId, "done"));
          }
          if (data.index + 1 >= steps.length) finish();
          else advance();
        } else if (data.action === ACTIONS.PREV) advance(-1);
      } else if (data.type === EVENTS.TARGET_NOT_FOUND) {
        const current = stepRef.current;
        if (current) setBlocked((state) => ({ ...state, [current.step.id]: t("tourNotFound") }));
      } else if (data.type === EVENTS.TOUR_END || data.status === STATUS.SKIPPED || data.status === STATUS.FINISHED) {
        if (data.status === STATUS.FINISHED && data.index + 1 >= steps.length) finish();
        else if (run) {
          setRun(false);
          setChecklist(true); // closed halfway: the checklist shows what is left
        }
      }
    },
    [steps.length, advance, finish, setProgress, run],
  );

  if (!workflows || tours.length === 0 || !signedIn || !progress) return null;
  const counts = tour ? tour.steps.filter((step) => !step.automatic && !step.skip && (!role || !step.role || step.role === role)) : [];
  const done = counts.filter((step) => progress.steps[`${tour.id}/${step.id}`]).length;
  return (
    <>
      <Joyride
        run={run}
        stepIndex={stepIndex}
        steps={steps}
        continuous
        scrollToFirstStep
        onEvent={onEvent}
        options={{
          showProgress: true,
          overlayClickAction: false,
          zIndex: 60,
          beforeTimeout: 15000, // a record step opens a list, then a record (`openRoute`)
          skipBeacon: true, // the step itself, not a pulsing dot to click first (a first sign-in saw no tour)
          targetWaitTimeout: 3000,
          disableFocusTrap: true, // a `do` step hands the keyboard to the control it points at
        }}
        locale={{ back: t("tourBack"), next: t("tourNext"), last: t("tourDone"), skip: t("tourSkip") }}
      />
      <Checklist
        open={checklist}
        onOpenChange={setChecklist}
        tours={tours}
        progress={progress}
        role={role}
        current={progress.current}
        onContinue={(chosen, at) => start(tours.indexOf(chosen), at)}
        onRestart={(chosen) => {
          setProgress((current) => resetTour(current, chosen.id));
          start(tours.indexOf(chosen), 0);
        }}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="fixed right-4 bottom-20 z-40 shadow-md md:bottom-4"
        data-bga-guide
        title={tour ? t("guideTitle", { name: tour.name }) : t("guide")}
        onClick={() => {
          setRun(false);
          setChecklist(true);
        }}
      >
        <Compass data-icon="inline-start" aria-hidden />
        {t("guide")}
        {counts.length > 0 && <span className="tabular-nums text-muted-foreground">{t("tourProgress", { done, total: counts.length })}</span>}
      </Button>
    </>
  );
}

/** Opens a page of the route, records included: each `[param]` is a record the step's action is allowed on (Story
 *  28.4: the previous step's record, the one the user is on, else the first in the list that qualifies), else the
 *  first record linked from the list page. False when no record fits (the step then names what makes one). */
async function openRoute(
  route: string,
  step: TTourStep,
  kind: TTourStepKind,
  push: (href: string) => void,
  lastRecord: Record<string, unknown>,
  block: (reason: string) => void,
): Promise<boolean> {
  if (pattern(route).test(window.location.pathname)) return true;
  const parts = route.split("/");
  const resolved: string[] = [];
  for (let index = 0; index < parts.length; index++) {
    const part = parts[index];
    if (!part.startsWith("[")) {
      resolved.push(part);
      continue;
    }
    const prefix = resolved.join("/") || "/";
    const current = window.location.pathname.split("/");
    const here = current.slice(0, index).join("/") === resolved.join("/") ? current[index] : undefined;
    const sameAsHere = here && here !== "new" ? here : null;
    let value: string | null = null;
    if (kind === "do" && index === parts.length - 1) {
      const { entity } = stepPlace(step);
      const ready = await readyRecord(step, [entity ? lastRecord[entity] : undefined, sameAsHere]);
      if ("id" in ready) value = ready.id;
      else if (step.needs) {
        block(t("tourNotFound"));
        return false;
      }
    }
    if (!value) value = sameAsHere;
    if (!value) {
      if (window.location.pathname !== prefix) push(prefix);
      value = await waitFor(() => recordLink(prefix));
    }
    if (!value) {
      block(t("tourNotFound"));
      return false;
    }
    resolved.push(value);
  }
  push(resolved.join("/"));
  return true;
}
