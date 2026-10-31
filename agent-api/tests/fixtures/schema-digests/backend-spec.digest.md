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
  seed?: Seed[];
  x-frontendBindings?: FrontendBinding[];
};

type Auth = {
  type: string;
  userEntity?: string;
  loginField?: string;
  roles?: string[];
};

type BackgroundJob = {
  name: string;
  trigger: string | Record<string, unknown>;
  description?: string | null;
};

type Entity = {
  name: string;
  table?: string | null;
  description?: string | null;
  fields: FieldDef[];
  indexes?: IndexDef[];
  uniqueConstraints?: string[][];
};

type FieldDef = {
  name: string;
  type: "uuid" | "string" | "text" | "integer" | "float" | "decimal" | "boolean" | "date" | "datetime" | "enum" | "json";
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

type Operation = {
  operationId: string;
  type: "crud" | "custom";
  action?: "create" | "get" | "list" | "update" | "delete" | null;
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
};

type Policy = {
  name: string;
  type: "role" | "ownership";
  roles?: string[];
  ownerField?: string | null;
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
  kind: "transition" | "immutableAfter" | "ownerOnly" | "sumEquals" | "custom";
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
