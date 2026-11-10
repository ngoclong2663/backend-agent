# BackendSpec Schema Digest

type BackendSpec = {
  specVersion: string;
  project: Project;
  stack: Stack;
  entities?: Entity[];
  relationships?: Relationship[];
  operations?: Operation[];
  auth?: Auth | null;
  policies?: Policy[];
  rules?: Rule[];
  integrations?: Integration[];
  backgroundJobs?: BackgroundJob[];
  emails?: Email[];
  webhooks?: Webhooks | null;
  payments?: Payments | null;
  seed?: Seed[];
  features?: FeatureAttachment[];
  x-frontendBindings?: FrontendBinding[];
};

// Epic 21: a figure computed from an entity's records, written from templates like CRUD (no engine): `fn` of `field` (count needs none), optionally grouped by a field, limited to the current period of a date field, and filtered by equality.
type Aggregate = {
  fn: "count" | "sum" | "avg" | "min" | "max";
  field?: string | null;
  groupBy?: string | null;
  period?: "day" | "week" | "month" | "year" | null;
  dateField?: string | null;
  filters?: Record<string, unknown>;
};

type Auth = {
  type: string;
  userEntity?: string;
  loginField?: string;
  roles?: string[];
  emailVerification?: boolean;
  passwordReset?: boolean;
};

type BackgroundJob = {
  name: string;
  trigger: string | JobTrigger;
  action?: "log" | "custom";
  maxAttempts?: number;
  description?: string | null;
};

// Story 10.7: an email sent through a job when its trigger fires.
type Email = {
  name: string;
  trigger: string | JobTrigger;
  to: string;
  subject: string;
  body: string;
};

type Entity = {
  name: string;
  table?: string | null;
  description?: string | null;
  fields: FieldDef[];
  indexes?: IndexDef[];
  uniqueConstraints?: string[][];
  displayField?: string | null;
};

// Epic 33: a feature plugin attached to an entity (`reactions` on `Clip`).
type FeatureAttachment = {
  feature: string;
  on: string;
  options?: Record<string, unknown>;
  entities?: string[];
  computed?: FeatureComputedField[];
};

// Epic 33: a read-only field a feature adds to its target's responses (`likeCount`, `myLikeId`).
type FeatureComputedField = {
  field: string;
  kind: "count" | "mine";
  entity: string;
  key: string;
  where?: Record<string, unknown>;
  owner?: string | null;
};

type FieldDef = {
  name: string;
  type: "uuid" | "string" | "text" | "integer" | "float" | "decimal" | "boolean" | "date" | "datetime" | "enum" | "json" | "file" | "image" | "video" | "audio" | "subtitles";
  primary?: boolean;
  required?: boolean;
  nullable?: boolean | null;
  unique?: boolean;
  index?: boolean;
  default?: unknown;
  values?: string[] | null;
  maxLength?: number | null;
  min?: number | null;
  max?: number | null;
  description?: string | null;
  accept?: string[] | null;
  maxSize?: number | null;
};

type FrontendBinding = {
  page: string;
  componentPath: string;
  component: string;
  operationId: string;
  params?: Record<string, unknown>;
};

type IndexDef = {
  fields: string[];
  unique?: boolean;
  name?: string | null;
};

type Integration = {
  name: string;
  description?: string | null;
  config?: Record<string, unknown>;
};

// Story 10.6: exactly one of an event (`task.created`, `<entity>.<custom>`), an operation id, a cron expression.
type JobTrigger = {
  event?: string | null;
  operation?: string | null;
  cron?: string | null;
};

type Operation = {
  operationId: string;
  type: "crud" | "custom" | "aggregate";
  action?: "create" | "get" | "list" | "update" | "delete" | null;
  aggregate?: Aggregate | null;
  entity?: string | null;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  summary?: string | null;
  description?: string | null;
  auth?: "none" | "jwt" | null;
  policy?: string | null;
  request?: PayloadSchema | null;
  response?: PayloadSchema | null;
  pagination?: boolean | Pagination | null;
  filters?: string[];
  sort?: string[];
  search?: string[];
  ranges?: string[];
  rules?: string[];
};

type Pagination = {
  defaultLimit?: number;
  maxLimit?: number;
};

type PayloadSchema = {
  entity?: string | null;
  fields?: string[] | null;
  properties?: FieldDef[] | null;
  type?: "object" | "array" | null;
};

// Story 10.9: one entity is paid for.
type Payments = {
  provider?: string;
  entity: string;
  amountField?: string | null;
  currency?: string | null;
  currencyField?: string | null;
  statusField: string;
  paidStatus: string;
  failedStatus?: string | null;
};

type Policy = {
  name: string;
  type: "role" | "ownership" | "visibility";
  roles?: string[];
  ownerField?: string | null;
  bypassRoles?: string[];
  denyStatus?: 403 | 404;
  entity?: string | null;
  where?: Record<string, unknown>;
};

type Project = {
  name: string;
  description?: string | null;
  slug?: string | null;
};

type Relationship = {
  name: string;
  type: "one-to-one" | "one-to-many" | "many-to-many";
  from: string;
  to: string;
  foreignKey?: string | null;
  onDelete?: "CASCADE" | "SET NULL" | "RESTRICT" | null;
  through?: string | null;
};

type Rule = {
  id: string;
  kind: "transition" | "immutableAfter" | "ownerOnly" | "sumEquals" | "custom" | "capacity" | "noOverlap" | "uniqueTogether";
  entity: string;
  params?: Record<string, unknown>;
  description?: string | null;
};

type Seed = {
  entity: string;
  records: Record<string, unknown>[];
};

type Stack = {
  framework: string;
  database: string;
  orm: "sqlalchemy" | "sqlmodel";
  migration: string;
};

// Story 10.8: a system that posts signed events to `POST /webhooks/<source>`; each event type it sends is a job (`log`, built in, or `custom`, the engine's).
type WebhookSource = {
  source: string;
  secretEnv: string;
  events: string[];
  action?: "log" | "custom";
  description?: string | null;
};

type Webhooks = {
  outgoing?: WebhooksOutgoing | null;
  incoming?: WebhookSource[];
};

// Story 10.8: the events (10.6 names) other systems may subscribe to.
type WebhooksOutgoing = {
  events: string[];
};
