// Story 28.5: progress per user and step, kept across reloads and across tour versions where the step did not change.
import { beforeEach, describe, expect, it } from "vitest";
import type { TWorkflows } from "../app";
import { firstOpenStep, loadProgress, markStep, markTourDone, resetTour, saveProgress, stepState } from "./progress";

const v1: TWorkflows = {
  version: "v1",
  tours: [
    {
      id: "handle",
      name: "Handle",
      roles: ["member", "staff"],
      steps: [
        { id: "ask", role: "member", actor: "Member", title: "Ask", operationId: "request.create", kind: "do" },
        { id: "close", role: "staff", actor: "Staff", title: "Close", operationId: "request.close", kind: "do" },
      ],
    },
  ],
};

describe("tour progress", () => {
  beforeEach(() => window.localStorage.clear());

  it("survives a reload", () => {
    let progress = loadProgress("member:1", v1);
    progress = markStep(progress, "handle", "ask", "request.create", "done");
    saveProgress("member:1", progress);
    const again = loadProgress("member:1", v1);
    expect(stepState(again, "handle", "ask")).toBe("done");
    expect(firstOpenStep(again, v1.tours[0])).toBe(1);
  });

  it("keeps the steps whose id and operation did not change when the version changes", () => {
    let progress = loadProgress("member:1", v1);
    progress = markStep(progress, "handle", "ask", "request.create", "done");
    progress = markStep(progress, "handle", "close", "request.close", "skipped");
    saveProgress("member:1", progress);
    const v2: TWorkflows = {
      version: "v2",
      tours: [{ ...v1.tours[0], steps: [v1.tours[0].steps[0], { ...v1.tours[0].steps[1], operationId: "request.archive" }] }],
    };
    const next = loadProgress("member:1", v2);
    expect(next.version).toBe("v2");
    expect(stepState(next, "handle", "ask")).toBe("done");
    expect(stepState(next, "handle", "close")).toBeUndefined();
  });

  it("marks a tour done and starts it again on request", () => {
    let progress = loadProgress("member:1", v1);
    progress = markStep(progress, "handle", "ask", "request.create", "done");
    progress = markTourDone(progress, "handle");
    expect(progress.doneTours).toEqual(["handle"]);
    progress = resetTour(progress, "handle");
    expect(progress.doneTours).toEqual([]);
    expect(firstOpenStep(progress, v1.tours[0])).toBe(0);
  });
});
