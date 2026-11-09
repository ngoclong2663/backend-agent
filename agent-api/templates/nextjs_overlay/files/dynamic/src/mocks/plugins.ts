import { http, HttpResponse, type HttpHandler } from "msw";
import { MOCK_API_BASE } from "@/lib/api/client";
import data from "./plugins.json";

/** Story 22.7: what the backend's plugins do, emulated by the mock API from the contract (`src/mocks/plugins.json`,
 *  generated from `x-bga`): sign-up, sign-in and the session (auth-jwt), who may do what (policies), the rules' refusals
 *  (rules, concurrency), uploads (storage), the checkout (payments) and many-to-many links (relations). A contract
 *  without plugins makes every function here a no-op. */

type TRecord = Record<string, unknown>;
type TRecords = (entity: string | null) => TRecord[];

type TError = { status: number; code: string; message: string; fields?: string[] };
type TPolicy =
  | { type: "role"; roles: string[] }
  | { type: "ownership"; ownerField: string; bypassRoles?: string[]; deny?: number }
  | { type?: string; roles?: string[]; ownerField?: string; bypassRoles?: string[]; deny?: number };

export type TPluginOperation = {
  operationId: string;
  entity: string | null;
  action: string | null;
  primaryKey: string;
  secured?: boolean;
  policy?: TPolicy | null;
  errors?: TError[];
  /** Story 23.9: `roles` (and signed-out callers) see only the records where every field equals its value. */
  visibility?: { roles: string[]; where: Record<string, unknown> } | null;
};

type TActionPolicy = { roles?: string[]; ownerField?: string; bypassRoles?: string[]; unless?: Record<string, unknown> };
type TEntityInfo = { primaryKey?: string; allowedActions?: string[]; actionPolicies?: Record<string, TActionPolicy>; ownerField?: string };
type TRule = { id: string; kind: string; entity: string; params: Record<string, unknown>; operations: string[]; status: number; code: string; field?: string; fields?: string[] };
type TLink = { kind: "list" | "add" | "remove"; parent: string; child: string; fixtures: string; parentField: string; childField: string; childLabel: string | null };
type TPlugins = {
  auth?: { login: string; register: string; me: string; loginField: string; userEntity: string; roles: string[]; demoUsers: { login: string; password: string; role: string }[] } | null;
  rules?: TRule[];
  storage?: {
    presign: string;
    fields: Record<string, { accept: string[]; maxSize: number | null; urlField: string; kind?: string }>;
    tracks?: Record<string, unknown>;
  } | null;
  payments?: { checkout: string; status: string; entity: string; statusField: string; paid: string; amountField: string | null } | null;
  links?: Record<string, TLink>;
};

const plugins = data as unknown as TPlugins;

function error(status: number, code: string, message: string, fields?: string[]) {
  return HttpResponse.json({ error: { code, message, details: fields ? { fields } : null } }, { status });
}

function contractError(op: TPluginOperation, code: string, fallback: string, status = 409) {
  const known = op.errors?.find((item) => item.code === code);
  return error(known?.status ?? status, code, known?.message ?? fallback, known?.fields);
}

// -- the session (auth-jwt) -------------------------------------------------------------------------------------------

// A mock token names its user (`mock.<id>`), so a session lasts across page loads as the mock data does; an account
// made here keeps its password on its record (`__password`, never answered).
const TOKEN = "mock.";

export function resetSessions() {
  // sessions live in the tokens and the store; nothing else to clear
}

function users(records: TRecords): TRecord[] {
  return plugins.auth ? records(plugins.auth.userEntity) : [];
}

function passwordOf(user: TRecord, login: string): string | undefined {
  return (user.__password as string | undefined) ?? plugins.auth?.demoUsers.find((demo) => demo.login === login)?.password;
}

/** The signed-in user of a request (its bearer token), or null. */
export function currentUser(request: Request, records: TRecords): TRecord | null {
  const header = request.headers.get("authorization") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!token.startsWith(TOKEN)) return null;
  const id = token.slice(TOKEN.length);
  return users(records).find((user) => String(user.id) === id) ?? null;
}

function account(user: TRecord): TRecord {
  const { passwordHash: _hidden, __password: _secret, ...out } = user; // eslint-disable-line @typescript-eslint/no-unused-vars
  return out;
}

function signIn(user: TRecord) {
  return HttpResponse.json({ accessToken: `${TOKEN}${user.id}`, tokenType: "bearer" });
}

async function body(request: Request): Promise<TRecord> {
  return ((await request.json().catch(() => ({}))) || {}) as TRecord;
}

/** The auth plugin's own operations (register, login, me), or null for any other operation. */
async function authOperation(op: TPluginOperation, request: Request, records: TRecords): Promise<Response | null> {
  const auth = plugins.auth;
  if (!auth) return null;
  if (op.operationId === auth.login) {
    const values = await body(request);
    const login = String(values[auth.loginField] ?? "");
    const user = users(records).find((item) => String(item[auth.loginField]) === login);
    if (!user || passwordOf(user, login) !== values.password) return error(401, "UNAUTHORIZED", "Wrong email or password");
    return signIn(user);
  }
  if (op.operationId === auth.register) {
    const values = await body(request);
    const login = String(values[auth.loginField] ?? "");
    const password = String(values.password ?? "");
    if (!login || password.length < 8) {
      const details = [...(!login ? [auth.loginField] : []), ...(password.length < 8 ? ["password"] : [])].map((name) => ({
        loc: ["body", name],
        msg: name === "password" ? "At least 8 characters" : "Field required",
      }));
      return HttpResponse.json({ error: { code: "VALIDATION_ERROR", message: "Request validation failed", details } }, { status: 422 });
    }
    if (users(records).some((item) => String(item[auth.loginField]) === login)) {
      return contractError(op, "CONFLICT", "An account with this email exists");
    }
    const { password: _secret, ...fields } = values; // eslint-disable-line @typescript-eslint/no-unused-vars
    const user = { ...fields, id: crypto.randomUUID(), role: auth.roles[0] ?? "user", createdAt: new Date().toISOString(), __password: password };
    users(records).push(user);
    return HttpResponse.json(account(user), { status: 201 });
  }
  if (op.operationId === auth.me) {
    const user = currentUser(request, records);
    return user ? HttpResponse.json(account(user)) : error(401, "UNAUTHORIZED", "Sign in to continue");
  }
  return null;
}

// -- who may do what (policies) ---------------------------------------------------------------------------------------

/** A secured operation without a session (401) or with the wrong role (403), or null. */
export function gate(op: TPluginOperation, user: TRecord | null): Response | null {
  if (!op.secured) return null;
  if (!user) return contractError(op, "UNAUTHORIZED", "Sign in to continue", 401);
  const roles = op.policy?.type === "role" ? (op.policy.roles ?? []) : [];
  if (roles.length > 0 && !roles.includes(String(user.role))) return contractError(op, "FORBIDDEN", "Your role cannot do this", 403);
  return null;
}

function bypasses(policy: { bypassRoles?: string[] }, user: TRecord | null): boolean {
  return Boolean(user && policy.bypassRoles?.includes(String(user.role)));
}

/** Story 23.9: whether this caller sees only the visible records (signed out, or a restricted role). */
function restricted(op: TPluginOperation, user: TRecord | null): boolean {
  return Boolean(op.visibility) && (!user || (op.visibility?.roles ?? []).includes(String(user.role)));
}

function visible(op: TPluginOperation, record: TRecord): boolean {
  return Object.entries(op.visibility?.where ?? {}).every(([field, value]) => String(record[field]) === String(value));
}

/** A list under a visibility rule (the visible records for a restricted caller) and an ownership policy (the user's
 *  own records; all of them for a bypass role). */
export function scope(op: TPluginOperation, user: TRecord | null, rows: TRecord[]): TRecord[] {
  if (restricted(op, user)) rows = rows.filter((row) => visible(op, row));
  const policy = op.policy;
  if (policy?.type !== "ownership" || !policy.ownerField || bypasses(policy, user)) return rows;
  return rows.filter((row) => user && String(row[policy.ownerField as string]) === String(user.id));
}

/** Another user's record under an ownership policy: 404 (or the policy's 403), or null. */
export function denied(op: TPluginOperation, user: TRecord | null, record: TRecord): Response | null {
  if (restricted(op, user) && !visible(op, record)) return error(404, "NOT_FOUND", `${op.entity ?? "Record"} not found`);
  const policy = op.policy;
  if (policy?.type !== "ownership" || !policy.ownerField || bypasses(policy, user)) return null;
  if (user && String(record[policy.ownerField]) === String(user.id)) return null;
  return policy.deny === 403
    ? contractError(op, "FORBIDDEN", "This is not yours", 403)
    : error(404, "NOT_FOUND", `${op.entity ?? "Record"} not found`);
}

/** A new record's owner is the signed-in user (`x-bga.source: currentUser`). */
export function stamp(entity: string | null, info: TEntityInfo | undefined, user: TRecord | null, record: TRecord) {
  if (entity && info?.ownerField && user) record[info.ownerField] = user.id;
}

function transitionRule(entity: string | null): TRule | undefined {
  return plugins.rules?.find((rule) => rule.kind === "transition" && rule.entity === entity);
}

function lockRule(entity: string | null): TRule | undefined {
  return plugins.rules?.find((rule) => rule.kind === "immutableAfter" && rule.entity === entity);
}

function locked(entity: string | null, record: TRecord): boolean {
  const rule = lockRule(entity);
  const field = (rule?.params.field as string) ?? "";
  return Boolean(rule && ((rule.params.states as string[]) ?? []).includes(String(record[field])));
}

function nextStates(entity: string | null, record: TRecord): string[] | null {
  const rule = transitionRule(entity);
  if (!rule) return null;
  const flow = (rule.params.transitions as Record<string, string[]>) ?? {};
  return flow[String(record[rule.params.field as string])] ?? [];
}

/** What this user may do to this record (`allowedActions`), as the backend computes it: the entity's actions, each
 *  kept when its policy lets the user (role, owner) and the rules let the record (next states, not locked, unpaid). */
export function actionsFor(entity: string | null, info: TEntityInfo, record: TRecord, user: TRecord | null): string[] {
  const states = nextStates(entity, record);
  const isLocked = locked(entity, record);
  return (info.allowedActions ?? []).filter((action) => {
    const policy = info.actionPolicies?.[action];
    if (policy?.roles && !(user && policy.roles.includes(String(user.role)))) return false;
    if (policy?.ownerField && !bypasses(policy, user) && !(user && String(record[policy.ownerField]) === String(user.id))) return false;
    if (policy?.unless && Object.entries(policy.unless).every(([field, value]) => record[field] === value)) return false;
    if (isLocked && (action === "update" || action === "delete" || action.startsWith("transition:"))) return false;
    if (action.startsWith("transition:") && states && !states.includes(action.slice("transition:".length))) return false;
    if (action === "pay" && plugins.payments && record[plugins.payments.statusField] === plugins.payments.paid) return false;
    return true;
  });
}

// -- the rules' refusals (rules, concurrency) -------------------------------------------------------------------------

function matches(record: TRecord, where: Record<string, unknown> | undefined): boolean {
  return Object.entries(where ?? {}).every(([field, condition]) => {
    if (condition && typeof condition === "object" && "ne" in condition) return record[field] !== (condition as { ne: unknown }).ne;
    if (condition && typeof condition === "object" && "in" in condition) return ((condition as { in: unknown[] }).in ?? []).includes(record[field]);
    return record[field] === condition;
  });
}

/** What the rules refuse: a write's change against the current record (null when creating), as the backend's
 *  templates do (same codes, same messages from the contract). */
export function ruleRefusal(op: TPluginOperation, current: TRecord | null, changes: TRecord, records: TRecords): Response | null {
  for (const rule of plugins.rules ?? []) {
    if (!rule.operations.includes(op.operationId)) continue;
    const params = rule.params;
    if (rule.kind === "immutableAfter" && current && ((params.states as string[]) ?? []).includes(String(current[params.field as string]))) {
      return contractError(op, rule.code, "This record can no longer change", rule.status);
    }
    if (rule.kind === "transition" && current && changes[params.field as string] !== undefined) {
      const from = String(current[params.field as string]);
      const to = changes[params.field as string];
      const flow = (params.transitions as Record<string, string[]>) ?? {};
      if (to !== current[params.field as string] && !(flow[from] ?? []).includes(String(to))) {
        return contractError(op, rule.code, "That state cannot follow the current one", rule.status);
      }
    }
    if (rule.kind === "capacity" && !current) {
      const parentField = params.parent as string;
      const parentId = changes[parentField];
      const parent = findParent(records, parentField, parentId);
      const capacity = Number(parent?.[params.capacityField as string]);
      if (parent && Number.isFinite(capacity)) {
        const taken = records(rule.entity).filter((row) => String(row[parentField]) === String(parentId) && matches(row, params.where as Record<string, unknown>));
        if (taken.length >= capacity) return contractError(op, rule.code, "It is full", rule.status);
      }
    }
    if (rule.kind === "uniqueTogether") {
      const fields = (params.fields as string[]) ?? [];
      const merged = { ...(current ?? {}), ...changes };
      const clash = records(rule.entity).some(
        (row) => row !== current && fields.every((field) => String(row[field]) === String(merged[field])) && matches(row, params.where as Record<string, unknown>),
      );
      if (clash) return contractError(op, rule.code, "This is taken", rule.status);
    }
  }
  // unique fields (the contract's CONFLICT lists each separately unique column: a tag's name, an account's email);
  // each is unique on its own, as the backend's unique indexes are (Story 25.1). Fields unique only together are
  // the uniqueTogether rule above.
  const conflict = op.errors?.find((item) => item.code === "CONFLICT" && item.fields?.length);
  if (conflict && op.entity) {
    const merged = { ...(current ?? {}), ...changes };
    for (const field of conflict.fields as string[]) {
      if (merged[field] === undefined || merged[field] === null) continue;
      const clash = records(op.entity).some((row) => row !== current && String(row[field]) === String(merged[field]));
      if (clash) return error(conflict.status, conflict.code, conflict.message, [field]);
    }
  }
  return null;
}

let parentEntities: Record<string, string> = {};

/** Field → parent entity (from the mock operations' references), so a capacity rule finds the parent record. */
export function knowParents(references: Record<string, string>) {
  parentEntities = { ...parentEntities, ...references };
}

function findParent(records: TRecords, field: string, id: unknown): TRecord | undefined {
  const entity = parentEntities[field];
  return entity ? records(entity).find((row) => String(row.id) === String(id)) : undefined;
}

// -- uploads (storage) ------------------------------------------------------------------------------------------------

const objects = new Map<string, string>(); // object key → a blob URL in this page (a large file)
const OBJECTS = "__objects"; // a small file as a data URL in the mock store, so it shows after a reload
const KEEP_BYTES = 1_500_000;

// Epic 29 (Story 29.2): a seeded media key without an upload of its own plays the kit's sample of its kind
const SAMPLE_BY_KIND: Record<string, string> = { video: "/samples/sample.mp4", audio: "/samples/sample.mp3", subtitles: "/samples/sample.en.vtt" };

/** The sample a seeded media key stands for: a subtitle track's language from its key (`…/1.ja.vtt`). */
export function sampleUrl(kind: string | undefined, key: string): string | null {
  if (!kind || !(kind in SAMPLE_BY_KIND)) return null;
  if (kind === "subtitles") {
    const language = /\.([a-z]{2,3})\.(vtt|srt)$/i.exec(key)?.[1];
    return language ? `/samples/sample.${language}.vtt` : SAMPLE_BY_KIND.subtitles;
  }
  return SAMPLE_BY_KIND[kind];
}

/** A file field's read URL (`<field>Url`): the uploaded file, else the fixture's own; a seed's outside URL (a demo
 *  photo) as it is, as the API reads it; a seeded media key the kind's sample. */
export function fileUrls(entity: string | null, record: TRecord, out: TRecord, records: TRecords) {
  for (const [name, spec] of Object.entries(plugins.storage?.fields ?? {})) {
    const [owner, field] = name.split(".");
    if (owner !== entity) continue;
    const key = record[field];
    if (typeof key === "string" && /^https?:\/\//.test(key)) {
      out[spec.urlField] = key;
      continue;
    }
    const kept = records(OBJECTS).find((row) => row.key === key)?.url;
    const seeded = typeof key === "string" && key.includes("/seed/") ? sampleUrl(spec.kind, key) : null;
    out[spec.urlField] = typeof key === "string" && key ? (objects.get(key) ?? kept ?? seeded ?? record[spec.urlField] ?? null) : null;
  }
}

async function dataUrl(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  return `data:${blob.type || "application/octet-stream"};base64,${btoa(binary)}`;
}

async function presign(op: TPluginOperation, request: Request): Promise<Response | null> {
  const storage = plugins.storage;
  if (!storage || op.operationId !== storage.presign) return null;
  const values = await body(request);
  const spec = storage.fields[`${values.entity}.${values.field}`];
  if (!spec) return error(404, "NOT_FOUND", "No such file field", ["field"]);
  const type = String(values.contentType ?? "");
  const ok = spec.accept.length === 0 || spec.accept.some((pattern) => (pattern.endsWith("/*") ? type.startsWith(pattern.slice(0, -1)) : pattern === type));
  if (!ok) return contractError(op, "FILE_TYPE_NOT_ALLOWED", "This type of file is not accepted", 422);
  if (spec.maxSize && Number(values.size) > spec.maxSize) return contractError(op, "FILE_TOO_LARGE", "The file is too large", 422);
  const key = `${String(values.entity).toLowerCase()}/${values.field}/mock/${crypto.randomUUID().slice(0, 8)}/${values.filename}`;
  const origin = new URL(request.url).origin;
  return HttpResponse.json({
    key,
    uploadUrl: `${origin}${MOCK_API_BASE}/__uploads/${encodeURIComponent(key)}`,
    method: "PUT",
    headers: { "Content-Type": type },
    expiresIn: 900,
  });
}

/** The presigned upload's `PUT`: a small file kept in the mock store (it shows after a reload), a large one for
 *  this page load. */
export function uploadHandlers(records: TRecords, save: () => void): HttpHandler[] {
  return [
    http.put(`*${MOCK_API_BASE}/__uploads/:key`, async ({ request, params }) => {
      const key = decodeURIComponent(String(params.key));
      const blob = await request.blob();
      if (blob.size <= KEEP_BYTES) {
        records(OBJECTS).push({ key, url: await dataUrl(blob) });
        save();
      } else objects.set(key, URL.createObjectURL(blob));
      return new HttpResponse(null, { status: 200 });
    }),
  ];
}

// -- the checkout (payments) ------------------------------------------------------------------------------------------

const PAYMENTS = "__payments"; // kept in the mock store, so the return page finds the payment after the checkout

async function payment(op: TPluginOperation, request: Request, params: Record<string, unknown>, records: TRecords): Promise<Response | null> {
  const spec = plugins.payments;
  if (!spec) return null;
  if (op.operationId === spec.checkout) {
    const record = records(spec.entity).find((row) => String(row.id) === String(params.recordId));
    if (!record) return error(404, "NOT_FOUND", `${spec.entity} not found`);
    if (record[spec.statusField] === spec.paid) return contractError(op, "ALREADY_PAID", "This is paid already");
    const amount = spec.amountField ? Number(record[spec.amountField]) : 1;
    if (!(amount > 0)) return contractError(op, "NOTHING_TO_PAY", "There is nothing to pay", 422);
    const values = await body(request);
    const paymentId = `pay_${crypto.randomUUID().slice(0, 12)}`;
    // the mock checkout succeeds at once: the record is paid, the success page shows it
    record[spec.statusField] = spec.paid;
    const paid = { paymentId, status: "paid", amount, currency: "EUR", recordId: record.id, checkoutUrl: null };
    records(PAYMENTS).push(paid);
    const success = typeof values.successUrl === "string" ? values.successUrl : `${new URL(request.url).origin}/payments/success`;
    const checkoutUrl = `${success}${success.includes("?") ? "&" : "?"}payment=${paymentId}`;
    return HttpResponse.json({ ...paid, status: "pending", checkoutUrl }, { status: 201 });
  }
  if (op.operationId === spec.status) {
    const found = records(PAYMENTS).find((row) => row.paymentId === String(params.paymentId));
    return found ? HttpResponse.json(found) : error(404, "NOT_FOUND", "Payment not found");
  }
  return null;
}

// -- many-to-many links (relations) -----------------------------------------------------------------------------------

async function links(op: TPluginOperation, request: Request, params: Record<string, unknown>, url: URL, records: TRecords): Promise<Response | null> {
  const link = plugins.links?.[op.operationId];
  if (!link) return null;
  const parentId = String(params.id);
  if (!records(link.parent).some((row) => String(row.id) === parentId)) return error(404, "NOT_FOUND", `${link.parent} not found`);
  const rows = records(link.fixtures);
  const children = records(link.child);
  const summary = (id: unknown) => {
    const child = children.find((row) => String(row.id) === String(id));
    return { id, label: child && link.childLabel ? (child[link.childLabel] ?? null) : null };
  };
  if (link.kind === "list") {
    const items = rows.filter((row) => String(row[link.parentField]) === parentId).map((row) => summary(row[link.childField]));
    items.sort((a, b) => String(a.label ?? "").localeCompare(String(b.label ?? "")));
    const limit = Number(url.searchParams.get("limit") ?? 20) || 20;
    const offset = Number(url.searchParams.get("offset") ?? 0) || 0;
    return HttpResponse.json({ items: items.slice(offset, offset + limit), total: items.length, limit, offset });
  }
  if (link.kind === "add") {
    const childId = (await body(request))[link.childField];
    if (!children.some((row) => String(row.id) === String(childId))) return contractError(op, "REFERENCE_NOT_FOUND", `${link.child} not found`, 400);
    if (rows.some((row) => String(row[link.parentField]) === parentId && String(row[link.childField]) === String(childId))) {
      return contractError(op, "DUPLICATE", "Already related");
    }
    rows.push({ [link.parentField]: params.id, [link.childField]: childId });
    return HttpResponse.json(summary(childId), { status: 201 });
  }
  const childId = String(params[link.childField] ?? "");
  const index = rows.findIndex((row) => String(row[link.parentField]) === parentId && String(row[link.childField]) === childId);
  if (index < 0) return error(404, "NOT_FOUND", "Not related");
  rows.splice(index, 1);
  return new HttpResponse(null, { status: 204 });
}

/** A plugin's own operation (auth, presign, checkout, links), answered here; null for every other operation. */
export async function pluginOperation(
  op: TPluginOperation,
  request: Request,
  params: Record<string, unknown>,
  records: TRecords,
): Promise<Response | null> {
  const url = new URL(request.url);
  return (
    (await authOperation(op, request, records)) ??
    (await presign(op, request)) ??
    (await payment(op, request, params, records)) ??
    (await links(op, request, params, url, records))
  );
}
