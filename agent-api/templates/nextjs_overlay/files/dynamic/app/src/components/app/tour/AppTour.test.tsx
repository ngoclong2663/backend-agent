// Stories 28.1–28.3 on the generated app this kit was copied into: a form submit sends one `operation` signal, a
// refused one sends none; "Fill with an example" fills the empty fields and never submits; step kinds per role.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MOCK_API_BASE } from "@/lib/api/client";
import { storeToken } from "@/lib/auth/token";
import { server } from "@/mocks/server";
import { app, canUse } from "../app";
import { AppFormBody } from "../AppForm";
import { formMethods, isBlank } from "../form/registry";
import { onSignal, type TSignal } from "../signals";
import { effectiveKind, fillExample } from "./AppTour";

vi.mock("next/navigation", () => ({
  useParams: () => ({}),
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

/** The first create form with an example and no required upload, picker or parent from the route (the test mocks an
 *  empty route); every generated app has one. */
const formId = Object.entries(app.forms).find(
  ([, form]) =>
    form.example &&
    !form.load &&
    form.operationId.endsWith(".create") &&
    !form.fields.some((field) => field.hidden || (field.required && (field.upload || field.reference))),
)?.[0];

/** Story 22.7: an app with sign-in answers its writes to a signed-in demo user whose role the operation allows. */
async function signInFor(operationId: string): Promise<void> {
  const auth = app.auth;
  if (!auth) return;
  const user = auth.demoUsers.find((candidate) => canUse(operationId, { enabled: true, ready: true, user: { role: candidate.role } })) ?? auth.demoUsers[0];
  if (!user) return;
  const response = await fetch(`http://localhost${MOCK_API_BASE}${auth.login.path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ [auth.loginField]: user.login, password: auth.password }),
  });
  const token = ((await response.json()) as { accessToken?: string }).accessToken;
  if (token) storeToken(token);
}

function mount(id: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AppFormBody formId={id} />
    </QueryClientProvider>,
  );
}

function submit(container: HTMLElement): HTMLElement {
  return container.querySelector<HTMLElement>('[data-bga-action="submit"]')!;
}

/** A value of the field's kind for a required field the example left empty. */
function sample(type: string, values?: string[]): unknown {
  if (type === "boolean") return true;
  if (type === "enum") return values?.[0];
  if (type === "integer" || type === "number" || type === "decimal") return 1;
  if (type === "date") return "2026-01-01";
  if (type === "datetime") return "2026-01-01T10:00:00Z";
  if (type === "email") return "tour@example.com";
  if (type === "url") return "https://example.com";
  return "Example";
}

describe("a form in the tour", () => {
  it.skipIf(!formId)("fills the empty fields from the example, leaves typed values, and does not submit", async () => {
    mount(formId!);
    await waitFor(() => expect(formMethods(formId!)).toBeDefined());
    const form = app.forms[formId!];
    const typed = form.fields.find((field) => !field.hidden && field.type === "string" && !field.reference && !field.upload);
    if (typed) formMethods(formId!)!.setValue(typed.name, "Typed by the user", { shouldDirty: true });
    const seen: TSignal[] = [];
    const stop = onSignal((received) => seen.push(received));
    await fillExample(formId!);
    const values = formMethods(formId!)!.getValues();
    for (const [name, value] of Object.entries(form.example ?? {})) {
      if (typed && name === typed.name) expect(values[name]).toBe("Typed by the user");
      else expect(values[name]).toEqual(value);
    }
    expect(seen.filter((received) => received.kind === "operation")).toEqual([]);
    stop();
  });

  it.skipIf(!formId)("sends exactly one operation signal on success and none on a refused submit", async () => {
    await signInFor(app.forms[formId!].operationId);
    const seen: TSignal[] = [];
    const stop = onSignal((received) => seen.push(received));
    const { container } = mount(formId!);
    await waitFor(() => expect(formMethods(formId!)).toBeDefined());
    await fillExample(formId!);
    const form = app.forms[formId!];
    for (const field of form.fields) {
      if (!field.hidden && field.required && isBlank(formMethods(formId!)!.getValues()[field.name])) {
        formMethods(formId!)!.setValue(field.name, sample(field.type, field.values), { shouldDirty: true });
      }
    }
    fireEvent.click(submit(container));
    await waitFor(() => expect(seen.some((received) => received.kind === "operation"), JSON.stringify(seen)).toBe(true), { timeout: 8000 });
    expect(seen.filter((received) => received.kind === "operation")).toHaveLength(1);
    expect(seen.find((received) => received.kind === "operation")?.operationId).toBe(form.operationId);

    // the same submit, refused by the API: no operation signal, an error signal
    seen.length = 0;
    server.use(http.post("*", () => HttpResponse.json({ error: { code: "CONFLICT", message: "no" } }, { status: 409 })));
    server.use(http.put("*", () => HttpResponse.json({ error: { code: "CONFLICT", message: "no" } }, { status: 409 })));
    server.use(http.patch("*", () => HttpResponse.json({ error: { code: "CONFLICT", message: "no" } }, { status: 409 })));
    fireEvent.click(submit(container));
    await waitFor(() => expect(seen.some((received) => received.kind === "error")).toBe(true), { timeout: 8000 });
    expect(seen.filter((received) => received.kind === "operation")).toEqual([]);
    stop();
  }, 25000);
});

describe("step kinds for the signed-in role", () => {
  const step = { id: "close", role: "staff", actor: "Staff", title: "Close", target: { section: "detail", action: "close" }, kind: "do" as const };
  it("is the binding's kind for the step's own role and a note for another role", () => {
    expect(effectiveKind(step, "staff")).toBe("do");
    expect(effectiveKind(step, "member")).toBe("note");
    expect(effectiveKind({ ...step, kind: undefined, target: { section: "detail", action: null } }, "staff")).toBe("look");
    expect(effectiveKind({ ...step, kind: undefined, automatic: true }, "staff")).toBe("note");
  });
});
