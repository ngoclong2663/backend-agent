/** Story 28.1 (Epic 28 D1): one signal for what just happened in the kit, so the guided tour can complete a step on
 *  the user's action instead of a Next button. `signal` dispatches a `bga:done` event on `window`; `onSignal`
 *  listens. No dependency, nothing happens when nobody listens, and a signal never carries a field's value. */

export type TSignalKind = "operation" | "page" | "dialog" | "field" | "error";

export type TSignal = {
  kind: TSignalKind;
  /** The operation that succeeded (`operation`), or the one a dialog's form submits (`dialog`). */
  operationId?: string;
  /** The page that rendered its sections (`page`). */
  page?: string;
  section?: string;
  /** The form (its id) a dialog opened or a field belongs to. */
  form?: string;
  /** The field that changed from empty to a valid value (`field`). */
  field?: string;
  /** The id of the record the operation created or changed, when the response or the call named one. */
  record?: unknown;
  /** The fields a refused submit marked (`error`; Story 28.2: the tour points at the first one). */
  fields?: string[];
};

export const SIGNAL_EVENT = "bga:done";

export function signal(kind: TSignalKind, detail: Omit<TSignal, "kind"> = {}): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<TSignal>(SIGNAL_EVENT, { detail: { kind, ...detail } }));
}

/** Listens to every signal; returns the unsubscribe. */
export function onSignal(handler: (signal: TSignal) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const listener = (event: Event) => handler((event as CustomEvent<TSignal>).detail);
  window.addEventListener(SIGNAL_EVENT, listener);
  return () => window.removeEventListener(SIGNAL_EVENT, listener);
}

/** The id of the record an operation worked on: the one its call named, else the one its response returned. */
export function recordOf(params: Record<string, unknown> | undefined, result: unknown): unknown {
  const named = params?.id ?? params?.recordId;
  if (named !== undefined && named !== null) return named;
  const returned = result && typeof result === "object" ? (result as { id?: unknown }).id : undefined;
  return returned ?? undefined;
}
