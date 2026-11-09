// An action that does not address a record by id (a collection action, a child created from the record with one
// click) is gated by the operation's access, not by the record's `allowedActions`; a body resolves the record.
import { afterEach, describe, expect, it } from "vitest";
import { allowed, app, resolveParams, type TAppAction, type TSession } from "./app";

const like: TAppAction = {
  id: "add-likes",
  label: "Like",
  kind: "mutation",
  operationId: "like.create",
  body: { videoId: "$record.id" },
};
const viewer: TSession = { enabled: true, ready: true, user: { id: "v1", role: "Viewer" } };
const creator: TSession = { enabled: true, ready: true, user: { id: "c1", role: "Creator" } };
const video = { id: "vid-1", allowedActions: ["update", "delete"] };
const access = app.access;

describe("allowed", () => {
  afterEach(() => {
    app.access = access;
  });

  it("gates a one-click child create by the operation's roles, whatever the record allows", () => {
    app.access = { "like.create": { secured: true, roles: ["Viewer"] } };
    expect(allowed(video, like, viewer)).toBe(true);
    expect(allowed(video, like, creator)).toBe(false);
    expect(allowed(video, like, { enabled: true, ready: true, user: null })).toBe(false);
  });

  it("shows it to anyone without auth, and without a session to check", () => {
    app.access = {};
    expect(allowed(video, like, { enabled: false, ready: true, user: null })).toBe(true);
    expect(allowed(video, like)).toBe(true);
  });

  it("still asks the record for its own actions", () => {
    const view: TAppAction = { id: "view", label: "View", kind: "mutation", operationId: "video.view", params: { id: "$record.id" } };
    expect(allowed(video, view, viewer)).toBe(false);
    expect(allowed({ ...video, allowedActions: ["video.view"] }, view, viewer)).toBe(true);
  });
});

describe("resolveParams on a body", () => {
  it("names the record from the row or the route", () => {
    expect(resolveParams(like.body, {}, video)).toEqual({ videoId: "vid-1" });
    expect(resolveParams({ videoId: "$route.id" }, { id: "vid-2" })).toEqual({ videoId: "vid-2" });
    expect(resolveParams({ status: "PUBLISHED" }, {})).toEqual({ status: "PUBLISHED" });
  });
});
