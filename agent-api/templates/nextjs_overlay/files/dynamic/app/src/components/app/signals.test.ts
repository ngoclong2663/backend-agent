// Story 28.1: the kit's one signal.
import { describe, expect, it, vi } from "vitest";
import { onSignal, recordOf, signal, type TSignal } from "./signals";

describe("signals", () => {
  it("delivers one event per signal to every listener and stops on unsubscribe", () => {
    const seen: TSignal[] = [];
    const stop = onSignal((received) => seen.push(received));
    signal("operation", { operationId: "task.create", record: "t1" });
    signal("page", { page: "home" });
    stop();
    signal("operation", { operationId: "task.create" });
    expect(seen).toEqual([
      { kind: "operation", operationId: "task.create", record: "t1" },
      { kind: "page", page: "home" },
    ]);
  });

  it("is silent without a listener", () => {
    const spy = vi.spyOn(window, "dispatchEvent");
    signal("field", { form: "task_create", field: "title" });
    expect(spy).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });

  it("names the record from the call first, then from the response", () => {
    expect(recordOf({ id: "a" }, { id: "b" })).toBe("a");
    expect(recordOf({}, { id: "b" })).toBe("b");
    expect(recordOf(undefined, { ok: true })).toBeUndefined();
  });
});
