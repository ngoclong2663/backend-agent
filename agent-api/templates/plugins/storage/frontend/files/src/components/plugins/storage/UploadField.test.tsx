// Story 29.3: a media upload shows its progress, can be cancelled, and fills the form's duration field.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { app, type TFormField } from "@/components/app/app";
import { registerForm } from "@/components/app/form/registry";
import { server } from "@/mocks/server";
import { UploadField } from "./UploadField";

vi.mock("next/navigation", () => ({
  useParams: () => ({}),
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

/** The first media upload field of a form in this app (the suite is skipped in an app without one). */
const found = Object.entries(app.forms)
  .flatMap(([formId, form]) => form.fields.map((field) => ({ formId, field })))
  .find(({ field }) => field.upload && (field.upload.kind === "video" || field.upload.kind === "audio"));

class FakeXhr {
  static instances: FakeXhr[] = [];
  upload = { onprogress: null as ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 200;
  aborted = false;
  constructor() {
    FakeXhr.instances.push(this);
  }
  open() {}
  setRequestHeader() {}
  send() {
    setTimeout(() => this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 }), 0);
  }
  finish() {
    this.onload?.();
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
}

function mount(field: TFormField, formId: string, onChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const result = render(
    <QueryClientProvider client={client}>
      <UploadField field={field} id={`${formId}-${field.name}`} value={undefined} onChange={onChange} invalid={false} />
    </QueryClientProvider>,
  );
  return { ...result, onChange };
}

describe("a media upload", () => {
  it.skipIf(!found)("shows its progress, can be cancelled, and sends the key when it finishes", { timeout: 25000 }, async () => {
    FakeXhr.instances = [];
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    server.use(
      http.post("*/files/presign", () => HttpResponse.json({ key: "lesson/video/mock/1/clip.mp4", uploadUrl: "http://localhost/mock-api/__uploads/x", method: "PUT", headers: {}, expiresIn: 60 })),
    );
    const { field, formId } = found!;
    const { container, onChange } = mount(field, formId);
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    const file = new File([new Uint8Array(16)], "clip.mp4", { type: field.upload!.kind === "audio" ? "audio/mpeg" : "video/mp4" });
    // the duration is read from the file's metadata; jsdom never loads media, so the player answers with an error
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(FakeXhr.instances).toHaveLength(1), { timeout: 8000 });
    await waitFor(() => expect(screen.getByText(/Uploading… 50%/)).toBeInTheDocument());
    fireEvent.click(screen.getByText("Cancel"));
    expect(FakeXhr.instances[0].aborted).toBe(true);
    await waitFor(() => expect(screen.queryByText(/Uploading…/)).not.toBeInTheDocument());
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(FakeXhr.instances).toHaveLength(2), { timeout: 8000 });
    FakeXhr.instances[1].finish();
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("lesson/video/mock/1/clip.mp4"));
  });

  it.skipIf(!found)("fills the form's empty duration field from the file's length", async () => {
    const { field, formId } = found!;
    const form = app.forms[formId];
    const durationField = form.fields.find((candidate) => /duration|runtime|length/i.test(candidate.name) && ["integer", "number", "decimal"].includes(candidate.type));
    if (!durationField) return;
    const values: Record<string, unknown> = {};
    const setValue = vi.fn((name: string, value: unknown) => {
      values[name] = value;
    });
    const stop = registerForm(formId, { getValues: () => values, setValue, trigger: async () => true });
    // the metadata of a media element in jsdom: stubbed with a known length
    const proto = window.HTMLMediaElement.prototype as unknown as { duration: number };
    Object.defineProperty(proto, "duration", { configurable: true, get: () => 372 });
    const created = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string, options?: ElementCreationOptions) => {
      const element = created(tag, options);
      if (tag === "video" || tag === "audio") setTimeout(() => (element as HTMLMediaElement).onloadedmetadata?.(new Event("loadedmetadata")), 0);
      return element;
    });
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    server.use(http.post("*/files/presign", () => HttpResponse.json({ key: "k", uploadUrl: "http://localhost/u", method: "PUT", headers: {}, expiresIn: 60 })));
    const { container } = mount(field, formId);
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [new File([new Uint8Array(8)], "clip.mp4", { type: "video/mp4" })] } });
    await waitFor(() => expect(setValue).toHaveBeenCalled(), { timeout: 4000 });
    const expected = /min/i.test(durationField.name) || durationField.unit === "min" ? 6 : 372;
    expect(values[durationField.name]).toBe(expected);
    stop();
  });
});
