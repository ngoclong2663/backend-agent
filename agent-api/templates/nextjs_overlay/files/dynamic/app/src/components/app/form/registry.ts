/** Story 28.3: the forms on the screen, by form id, so the guided tour can fill one with an example (`setValue`,
 *  `trigger`). AppForm registers its methods on mount and unregisters on unmount; nothing else reads this. */

export type TFormMethods = {
  getValues: () => Record<string, unknown>;
  setValue: (name: string, value: unknown, options?: { shouldValidate?: boolean; shouldDirty?: boolean }) => void;
  trigger: (name?: string | string[]) => Promise<boolean>;
};

const forms = new Map<string, TFormMethods>();
const listeners = new Set<() => void>();

export function registerForm(id: string, methods: TFormMethods): () => void {
  forms.set(id, methods);
  for (const listener of listeners) listener();
  return () => {
    if (forms.get(id) === methods) forms.delete(id);
    for (const listener of listeners) listener();
  };
}

export function formMethods(id: string): TFormMethods | undefined {
  return forms.get(id);
}

/** Called whenever a form appears or leaves (the tour waits for a dialog's form this way). */
export function onForms(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** An empty value as the form kit sees it: not given, or a blank string. */
export function isBlank(value: unknown): boolean {
  return value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0);
}
