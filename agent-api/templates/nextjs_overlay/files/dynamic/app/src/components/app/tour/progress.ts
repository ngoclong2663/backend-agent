import type { TWorkflows } from "../app";

/** Story 28.5 (Epic 28 D6): a user's progress through the tours, per step, in `localStorage`. Leaving and coming
 *  back continues where the user stopped. A new tour version keeps the steps whose id and operation did not change,
 *  so a redraft that only reworded a step does not start the user over. */

export type TStepState = "done" | "skipped";
export type TProgress = {
  version: string;
  /** `<tour>/<step>` → its state. */
  steps: Record<string, TStepState>;
  /** `<tour>/<step>` → the operation the step had when it was done (what a new version is compared with). */
  ops: Record<string, string | null>;
  current: { tour: string; step: string } | null;
  doneTours: string[];
};

const STORE = "bga-tour-progress";
/** Story 26.4: a browser that must see the screens without the tour (the agent's evaluation) sets this. */
export const TOUR_OFF = "bga-tour-off";
/** Story 28.5: the step a "Continue as <role>" hands over to the next account (this browser session only). */
export const HANDOFF = "bga-tour-handoff";

export function stepKey(tour: string, step: string): string {
  return `${tour}/${step}`;
}

function empty(version: string): TProgress {
  return { version, steps: {}, ops: {}, current: null, doneTours: [] };
}

function operations(workflows: TWorkflows): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const tour of workflows.tours) for (const step of tour.steps) out[stepKey(tour.id, step.id)] = step.operationId ?? null;
  return out;
}

export function tourOff(): boolean {
  try {
    return window.localStorage.getItem(TOUR_OFF) === "1";
  } catch {
    return true; // no storage (private mode): never start on its own
  }
}

export function loadProgress(user: string, workflows: TWorkflows): TProgress {
  const fresh = empty(workflows.version);
  let stored: TProgress | null = null;
  try {
    const raw = window.localStorage.getItem(`${STORE}:${user}`);
    stored = raw ? (JSON.parse(raw) as TProgress) : null;
  } catch {
    return fresh;
  }
  if (!stored || typeof stored !== "object" || !stored.steps) return fresh;
  if (stored.version === workflows.version) return { ...fresh, ...stored, doneTours: stored.doneTours ?? [] };
  // another version: keep what did not change (same step id, same operation)
  const now = operations(workflows);
  const kept: TProgress = { ...fresh, current: null };
  for (const [key, state] of Object.entries(stored.steps)) {
    if (key in now && now[key] === (stored.ops ?? {})[key]) {
      kept.steps[key] = state;
      kept.ops[key] = now[key];
    }
  }
  return kept;
}

export function saveProgress(user: string, progress: TProgress): void {
  try {
    window.localStorage.setItem(`${STORE}:${user}`, JSON.stringify(progress));
  } catch {
    // the progress lives for this page only
  }
}

export function markStep(progress: TProgress, tour: string, step: string, operationId: string | null | undefined, state: TStepState): TProgress {
  const key = stepKey(tour, step);
  return { ...progress, steps: { ...progress.steps, [key]: state }, ops: { ...progress.ops, [key]: operationId ?? null } };
}

export function setCurrent(progress: TProgress, current: TProgress["current"]): TProgress {
  return { ...progress, current };
}

export function markTourDone(progress: TProgress, tour: string): TProgress {
  return { ...progress, doneTours: progress.doneTours.includes(tour) ? progress.doneTours : [...progress.doneTours, tour], current: null };
}

export function resetTour(progress: TProgress, tour: string): TProgress {
  const steps = Object.fromEntries(Object.entries(progress.steps).filter(([key]) => !key.startsWith(`${tour}/`)));
  return { ...progress, steps, doneTours: progress.doneTours.filter((id) => id !== tour), current: null };
}

export function stepState(progress: TProgress, tour: string, step: string): TStepState | undefined {
  return progress.steps[stepKey(tour, step)];
}

/** The index of the first step of a tour that is neither done nor skipped (its length when every step is). */
export function firstOpenStep(progress: TProgress, tour: { id: string; steps: { id: string }[] }): number {
  const index = tour.steps.findIndex((step) => !stepState(progress, tour.id, step.id));
  return index < 0 ? tour.steps.length : index;
}

export function readHandoff(): { tour: string; step: string } | null {
  try {
    const raw = window.sessionStorage.getItem(HANDOFF);
    return raw ? (JSON.parse(raw) as { tour: string; step: string }) : null;
  } catch {
    return null;
  }
}

export function writeHandoff(value: { tour: string; step: string } | null): void {
  try {
    if (value) window.sessionStorage.setItem(HANDOFF, JSON.stringify(value));
    else window.sessionStorage.removeItem(HANDOFF);
  } catch {
    // the next account starts its tour from the beginning
  }
}
