import { http, HttpResponse, type HttpHandler } from "msw";
import { MOCK_API_BASE } from "@/lib/api/client";
import columnDefaults from "./defaults.json";
import entities from "./entities.json";
import fixtures from "./fixtures.json";
import operations from "./operations.json";
import {
  actionsFor,
  currentUser,
  denied,
  fileUrls,
  gate,
  knowParents,
  pluginOperation,
  resetSessions,
  ruleRefusal,
  scope,
  stamp,
  uploadHandlers,
  type TPluginOperation,
} from "./plugins";

/** Generic mock API built from the contract (operations.json) and its example records (fixtures.json): lists
 *  honour limit, offset, sort, filters and q; writes change an in-memory store until the page reloads. */
type TMockOperation = {
  operationId: string;
  method: string;
  path: string;
  entity: string | null;
  action: string | null;
  mock?: "record" | "records" | "merge" | "create" | "sample" | "aggregate" | null;
  sample?: unknown;
  /** Epic 21: an aggregate operation, computed here from the fixtures as the backend computes it from its table. */
  aggregate?: { fn: string; field?: string; groupBy?: string; period?: string; dateField?: string; filters?: Record<string, unknown> } | null;
  envelope?: boolean;
  primaryKey: string;
  status: number;
  filters: string[];
  /** Story 23.4: a range's parameters (`<field>From`, `<field>To`) → the field and the bound. */
  ranges?: Record<string, { field: string; bound: "gte" | "lte" }>;
  sort: string[];
  search: boolean;
  defaultLimit: number;
  maxLimit: number;
  /** Story 22.4: the request's required fields and its references (field → parent entity), checked as the API does. */
  required?: string[];
  references?: Record<string, string>;
  /** Story 22.7: behind sign-in, the policy (role, ownership) and the contract's errors (codes, messages, fields). */
  secured?: boolean;
  policy?: TPluginOperation["policy"];
  errors?: TPluginOperation["errors"];
};

type TRecord = Record<string, unknown>;

/** Story 10.0b: what the API adds to a stored record (`x-bga.entities` of the contract). */
type TEntityInfo = {
  primaryKey: string;
  labelField: string | null;
  references?: { field: string; apiName: string; entity: string; labelField: string | null }[];
  // Story 10.11: a one-to-one child, shown in its parent's record as a summary
  children?: { field: string; apiName: string; entity: string; labelField: string | null; primaryKeyField: string }[];
  allowedActions?: string[];
  secretFields?: string[];
  // Story 22.7: who may do which action (role, owner, a state), and the owner's field
  actionPolicies?: Record<string, { roles?: string[]; ownerField?: string; bypassRoles?: string[]; unless?: Record<string, unknown> }>;
  ownerField?: string;
};

const presentation = entities as unknown as Record<string, TEntityInfo>;

const seed = fixtures as Record<string, TRecord[]>;
/** Story 22.7: in the browser the mock database lasts the tab's session, not one page load (a record created on one
 *  page is there on the next; a signed-in user stays signed in), keyed to this app's example data. */
const SAVED = `bga.mock-store.${JSON.stringify(seed).length}`;

function loadStore(): Record<string, TRecord[]> {
  try {
    const saved = typeof sessionStorage === "undefined" ? null : sessionStorage.getItem(SAVED);
    if (saved) return JSON.parse(saved) as Record<string, TRecord[]>;
  } catch {
    // no storage (tests, a private window): from the example data
  }
  return structuredClone(seed);
}

let store: Record<string, TRecord[]> = loadStore();

function saveStore() {
  try {
    if (typeof sessionStorage !== "undefined") sessionStorage.setItem(SAVED, JSON.stringify(store));
  } catch {
    // full or blocked: the data lasts this page load
  }
}

export function resetMockStore() {
  store = structuredClone(seed);
  resetSessions();
  try {
    if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(SAVED);
  } catch {
    // nothing saved
  }
}

/** Story 30.3: the design plugin check's state switch (`localStorage["bga-mock-state"]`): `empty` answers reads with
 *  no records, `error` with a 500, `slow` after a delay (the loading state). Dev tool only; unset in real use. */
function mockState(): "empty" | "error" | "slow" | null {
  try {
    const value = typeof localStorage === "undefined" ? null : localStorage.getItem("bga-mock-state");
    return value === "empty" || value === "error" || value === "slow" ? value : null;
  } catch {
    return null;
  }
}

async function staged(request: Request): Promise<Response | null> {
  const state = mockState();
  if (!state || request.method !== "GET") return null;
  if (state === "slow") await new Promise((resolve) => setTimeout(resolve, 4000));
  if (state === "error") {
    return HttpResponse.json({ error: { code: "INTERNAL_ERROR", message: "The mock API is set to fail", details: null } }, { status: 500 });
  }
  return null;
}

function records(entity: string | null): TRecord[] {
  if (!entity) return [];
  if (mockState() === "empty") return [];
  store[entity] ??= [];
  return store[entity];
}

/** A record as the API answers it: each parent as `{id, label}`, and what can be done to it (Story 10.0b). */
function present(entity: string | null, record: TRecord, user: TRecord | null = null): TRecord {
  const info = entity ? presentation[entity] : undefined;
  if (!info) return record;
  if (!info.allowedActions) {
    const out: TRecord = { ...record };
    for (const field of info.secretFields ?? []) delete out[field]; // a password hash never leaves the backend
    return out;
  }
  // Story 22.7: what this user may do to this record (policies, rules), as the backend computes it
  const out: TRecord = { ...record, allowedActions: actionsFor(entity, info, record, user) };
  fileUrls(entity, record, out, records);
  for (const field of info.secretFields ?? []) delete out[field]; // a password hash never leaves the backend
  for (const ref of info.references ?? []) {
    const id = record[ref.field];
    const key = presentation[ref.entity]?.primaryKey ?? "id";
    const parent = records(ref.entity).find((item) => String(item[key]) === String(id));
    out[ref.apiName] = id === null || id === undefined ? null : { id, label: parent && ref.labelField ? (parent[ref.labelField] ?? null) : null };
  }
  const own = record[info.primaryKey ?? "id"];
  for (const child of info.children ?? []) {
    const row = records(child.entity).find((item) => String(item[child.field]) === String(own));
    out[child.apiName] = row ? { id: row[child.primaryKeyField], label: child.labelField ? (row[child.labelField] ?? null) : null } : null;
  }
  return out;
}

function notFound(entity: string | null) {
  return HttpResponse.json({ error: { code: "NOT_FOUND", message: `${entity ?? "Record"} not found`, details: null } }, { status: 404 });
}

/** A request the API would refuse: a required field missing (422, by field), a parent that does not exist (400). */
function refused(op: TMockOperation, body: TRecord, creating: boolean): Response | null {
  const missing = creating ? (op.required ?? []).filter((name) => body[name] === undefined || body[name] === null) : [];
  if (missing.length > 0) {
    const details = missing.map((name) => ({ loc: ["body", name], msg: "Field required", type: "missing" }));
    return HttpResponse.json({ error: { code: "VALIDATION_ERROR", message: "Request validation failed", details } }, { status: 422 });
  }
  for (const [field, entity] of Object.entries(op.references ?? {})) {
    const value = body[field];
    if (value === undefined || value === null) continue;
    const key = presentation[entity]?.primaryKey ?? "id";
    if (!records(entity).some((item) => String(item[key]) === String(value))) {
      return HttpResponse.json({ error: { code: "REFERENCE_NOT_FOUND", message: `${entity} not found`, details: { field } } }, { status: 400 });
    }
  }
  return null;
}

function compare(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

function list(op: TMockOperation, url: URL, params: Record<string, unknown> = {}, user: TRecord | null = null) {
  let items = scope(op, user, [...records(op.entity)]);
  // A list scoped by its path (`/fields/:fieldId/reviews`) keeps the records of that parent.
  for (const [name, value] of Object.entries(params)) {
    if (typeof value === "string" && items.some((it) => name in it)) items = items.filter((item) => String(item[name]) === value);
  }
  for (const [name, value] of url.searchParams.entries()) {
    if (!value || ["limit", "offset", "sort", "q"].includes(name)) continue;
    const range = op.ranges?.[name];
    if (range) {
      // Story 23.4: a date range, inclusive; a date bound covers its whole day for a datetime value
      items = items.filter((item) => {
        const v = item[range.field];
        if (v === undefined || v === null) return false;
        const text = String(v);
        return range.bound === "gte" ? text >= value : text.slice(0, value.length) <= value;
      });
    } else if (name.endsWith("Before")) {
      const field = name.slice(0, -"Before".length);
      items = items.filter((item) => {
        const v = item[field];
        return v !== undefined && v !== null && String(v) <= value;
      });
    } else if (name.endsWith("After")) {
      const field = name.slice(0, -"After".length);
      items = items.filter((item) => {
        const v = item[field];
        return v !== undefined && v !== null && String(v) >= value;
      });
    } else if (op.filters.includes(name) || items.some((it) => name in it)) {
      items = items.filter((item) => String(item[name]) === value);
    }
  }
  const query = url.searchParams.get("q");
  if (op.search && query) {
    const needle = query.toLowerCase();
    items = items.filter((item) => Object.values(item).some((value) => typeof value === "string" && value.toLowerCase().includes(needle)));
  }
  const sort = url.searchParams.get("sort");
  if (sort) {
    const field = sort.replace(/^-/, "");
    if (!op.sort.includes(field)) {
      return HttpResponse.json({ error: { code: "VALIDATION_ERROR", message: `Cannot sort by ${field}`, details: null } }, { status: 422 });
    }
    const direction = sort.startsWith("-") ? -1 : 1;
    items.sort((a, b) => direction * compare(a[field], b[field]));
  }
  const limit = Math.min(Number(url.searchParams.get("limit") ?? op.defaultLimit) || op.defaultLimit, op.maxLimit);
  const offset = Number(url.searchParams.get("offset") ?? 0) || 0;
  const paged = items.slice(offset, offset + limit).map((item) => present(op.entity, item, user));
  if (op.envelope === false) {
    return HttpResponse.json(paged);
  }
  return HttpResponse.json({ items: paged, total: items.length, limit, offset });
}

/** `fn` of `field` over `rows` (count needs none), optionally grouped and limited to the current period. */
function aggregate(
  spec: NonNullable<TMockOperation["aggregate"]>,
  rows: TRecord[],
): { value: number } | { key: string; value: number }[] {
  const now = new Date();
  const since: Record<string, Date> = {
    day: new Date(now.getFullYear(), now.getMonth(), now.getDate()),
    week: new Date(now.getTime() - 7 * 86_400_000),
    month: new Date(now.getFullYear(), now.getMonth(), 1),
    year: new Date(now.getFullYear(), 0, 1),
  };
  let items = rows.filter((row) => Object.entries(spec.filters ?? {}).every(([name, value]) => String(row[name]) === String(value)));
  if (spec.period && since[spec.period]) {
    const dateField = spec.dateField ?? Object.keys(items[0] ?? {}).find((key) => /date|at$/i.test(key));
    if (dateField) items = items.filter((row) => new Date(String(row[dateField])) >= since[spec.period as string]);
  }
  const measure = (group: TRecord[]): number => {
    if (spec.fn === "count") return group.length;
    const values = group.map((row) => Number(row[spec.field ?? ""])).filter((value) => Number.isFinite(value));
    if (values.length === 0) return 0;
    if (spec.fn === "sum") return values.reduce((a, b) => a + b, 0);
    if (spec.fn === "avg") return values.reduce((a, b) => a + b, 0) / values.length;
    if (spec.fn === "min") return Math.min(...values);
    return Math.max(...values);
  };
  if (!spec.groupBy) return { value: measure(items) };
  const groups = new Map<string, TRecord[]>();
  for (const row of items) {
    const key = String(row[spec.groupBy] ?? "—");
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return Array.from(groups, ([key, group]) => ({ key, value: measure(group) }));
}

/** Story 22.7: the values a new record starts with when the request leaves them out (`status: PENDING`), as the
 *  backend's columns default them (`defaults.json`, from the contract's create requests). */
function defaults(entity: string | null): TRecord {
  return entity ? { ...((columnDefaults as Record<string, TRecord>)[entity] ?? {}) } : {};
}

function newId(entity: string | null, primaryKey: string): string | number {
  const existing = records(entity);
  const numeric = existing.length > 0 && typeof existing[0][primaryKey] === "number";
  return numeric ? Math.max(0, ...existing.map((item) => Number(item[primaryKey]))) + 1 : crypto.randomUUID();
}

function handler(op: TMockOperation): HttpHandler {
  const route = `*${MOCK_API_BASE}${op.path}`;
  const method = op.method.toLowerCase() as "get" | "post" | "put" | "patch" | "delete";
  return http[method](route, async ({ request, params }) => {
    try {
    const url = new URL(request.url);
    const id = params.id ?? params[op.primaryKey];
    const find = () => records(op.entity).find((item) => String(item[op.primaryKey]) === String(id));
    // Story 22.7: the session, the policy, then a plugin's own operation (auth, presign, checkout, links)
    const user = currentUser(request, records);
    const blocked = gate(op, user);
    if (blocked) return blocked;
    const stagedResponse = await staged(request);
    if (stagedResponse) return stagedResponse;
    const own = await pluginOperation(op, request, params as Record<string, unknown>, records);
    if (own) return own;
    if (op.mock === "aggregate" && op.aggregate) return HttpResponse.json(aggregate(op.aggregate, records(op.entity)));
    const sample = op.sample;
    if (op.action === "list" && op.mock === "sample" && Array.isArray(sample)) {
      // A custom list with its own record shape: the entity's records (when it has any) over the sample's fields.
      const rows = records(op.entity);
      const first = (sample[0] ?? {}) as Record<string, unknown>;
      return HttpResponse.json(rows.length ? rows.map((row) => ({ ...first, ...row })) : sample);
    }
    if (op.action === "list" || op.mock === "records") return list(op, url, op.action === "list" ? params : {}, user);
    if (op.action === "get" || op.mock === "record") {
      const found = find();
      if (!found) return notFound(op.entity);
      return denied(op, user, found) ?? HttpResponse.json(present(op.entity, found, user));
    }
    if (op.action === "create" || op.mock === "create") {
      const body = ((await request.json().catch(() => ({}))) || {}) as TRecord;
      // the rules see the owner the server sets from the session, as the backend's do (a pair with the signed-in user)
      const owned = { ...body };
      stamp(op.entity, op.entity ? presentation[op.entity] : undefined, user, owned);
      const refusal = refused(op, body, true) ?? ruleRefusal(op, null, owned, records);
      if (refusal) return refusal;
      const created = { [op.primaryKey]: newId(op.entity, op.primaryKey), createdAt: new Date().toISOString(), ...defaults(op.entity), ...body };
      stamp(op.entity, op.entity ? presentation[op.entity] : undefined, user, created);
      records(op.entity).push(created);
      return HttpResponse.json(present(op.entity, created, user), { status: op.status });
    }
    if (op.action === "update") {
      const current = find();
      if (!current) return notFound(op.entity);
      const forbidden = denied(op, user, current);
      if (forbidden) return forbidden;
      const changes = ((await request.json().catch(() => ({}))) || {}) as TRecord;
      const refusal = refused(op, changes, false) ?? ruleRefusal(op, current, changes, records);
      if (refusal) return refusal;
      Object.assign(current, changes);
      return HttpResponse.json(present(op.entity, current, user));
    }
    if (op.mock === "merge") {
      const current = find();
      if (!current) return notFound(op.entity);
      const body = ((await request.json().catch(() => ({}))) || {}) as TRecord;
      for (const [k, v] of Object.entries(body)) {
        if (v !== undefined) {
          current[k] = v;
        }
      }
      return HttpResponse.json(present(op.entity, current), { status: op.status });
    }
    if (op.mock === "sample") {
      if (op.status === 204) return new HttpResponse(null, { status: 204 });
      return HttpResponse.json(op.sample ?? {}, { status: op.status });
    }
    if (op.action === "delete") {
      const current = find();
      if (!current) return notFound(op.entity);
      const refusal = denied(op, user, current) ?? ruleRefusal(op, current, {}, records);
      if (refusal) return refusal;
      store[op.entity as string] = records(op.entity).filter((item) => item !== current);
      return new HttpResponse(null, { status: 204 });
    }
    console.warn(`[MSW] ${op.operationId} has no mock plan`);
    return HttpResponse.json({ error: { code: "NOT_IMPLEMENTED", message: `${op.operationId} has no mock`, details: null } }, { status: 501 });
    } finally {
      if (method !== "get") saveStore(); // a write lasts across page loads (Story 22.7)
    }
  });
}

for (const op of operations as TMockOperation[]) knowParents(op.references ?? {});

export const handlers: HttpHandler[] = [...uploadHandlers(records, saveStore), ...(operations as TMockOperation[]).map(handler)];
