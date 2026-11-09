import type { TUsageRollup } from "@/types/usage";

export type TGenerationStatus =
  | "PENDING"
  | "RUNNING"
  | "VALIDATING"
  | "REPAIRING"
  | "COMPLETED"
  | "COMPLETED_WITH_WARNINGS"
  | "FAILED"
  | "CANCELLED"
  | "DRAFTING"
  | "NEEDS_REVIEW";

export type TGenerationMode = "backend" | "static" | "dynamic";

export type TLane = "backend" | "frontend" | "integration";

export type TLaneStatus = "PENDING" | "RUNNING" | "VALIDATING" | "REPAIRING" | "COMPLETED" | "FAILED" | "SKIPPED";

export type TLanes = Partial<Record<TLane, TLaneStatus>>;

export type TEngineName =
  | "claude_code"
  | "antigravity"
  | "antigravity_json"
  | "claude_code_json"
  | "gemini_api"
  | "fake";

export type TDraftSpeed = "fast" | "thorough";

export type TGenerationOptions = {
  maxRepairAttempts: number;
  runTests: boolean;
  generateDockerfile: boolean;
  deployPreview: boolean;
  engine?: TEngineName | null;
  /** Story 18.10: the engine that drafts the specs of a one-click generation. */
  draftEngine?: TEngineName | null;
  /** How the one-click draft thinks: fast (the provider's fast model) or thorough; empty: the server's DRAFT_SPEED. */
  draftSpeed?: TDraftSpeed | null;
  timeoutSeconds?: number | null;
  draftId?: string | null;
  autoGenerate?: boolean | null;
  frontend?: { runTests: boolean; generatePreview: boolean; mockApi: boolean } | null;
};

export type TGeneration = {
  generationId: string;
  mode: TGenerationMode;
  projectName: string | null;
  status: TGenerationStatus;
  lanes: TLanes;
  currentStep: string | null;
  engine: string;
  repairAttempts: number;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  frontendPreview?: TPreview | null;
};

export type TGenerationPage = {
  items: TGeneration[];
  nextCursor: string | null;
};

export type TEngineInvocation = {
  id: string;
  nodeRunId: string | null;
  engine: string;
  purpose: string;
  status: string;
  exitCode: number | null;
  durationMs: number | null;
  turns: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  costUsd: number | null;
  createdAt: string | null;
};

export type TStepRunStatus = "running" | "succeeded" | "failed" | "skipped" | "cancelled" | "abandoned";

export type TStepRun = {
  id: string;
  node: string;
  attempt: number;
  status: TStepRunStatus;
  summary: Record<string, unknown>;
  startedAt: string | null;
  finishedAt: string | null;
  invocations: TEngineInvocation[];
};

export type TUsageTotals = {
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
};

export type TGenerationDetail = TGeneration & {
  specId: string | null;
  frontendSpecId: string | null;
  options: TGenerationOptions;
  resumeCount: number;
  cancelRequested: boolean;
  validation: Record<string, string>;
  steps: TStepRun[];
  usage: TUsageTotals;
  trace: { traceId: string | null; langsmithUrl: string | null };
  artifacts: TArtifact[];
  preview: TPreview | null;
  frontendPreview: TPreview | null;
  error: string | null;
};

export type TCreateGenerationPayload = {
  mode?: TGenerationMode;
  requirement?: { text?: string | null; format?: string | null; fileName?: string | null } | null;
  backendSpec?: unknown;
  specId?: string;
  frontendSpec?: unknown;
  frontendSpecId?: string;
  /** The requirement draft the specs came from (Stories 2.4, 12.4); its requirement becomes an artifact. */
  draftId?: string;
  options: TGenerationOptions;
};

export type TCreateGenerationResult = {
  generationId: string;
  status: TGenerationStatus;
  createdAt: string | null;
};

export type TGenerationEventType =
  | "status.changed"
  | "job.started"
  | "job.resumed"
  | "step.started"
  | "step.finished"
  | "engine.started"
  | "engine.event"
  | "engine.finished"
  | "engine.retry"
  | (string & {});

export type TGenerationEvent = {
  id: number;
  ts: string | null;
  generationId: string;
  type: TGenerationEventType;
  step: string | null;
  status: string | null;
  lane?: TLane | null;
  payload: Record<string, unknown>;
};

export type TWorkflowGraph = {
  mode?: TGenerationMode;
  nodes: { id: string; label: string; status?: string; lane?: TLane | null }[];
  edges: { source: string; target: string; conditional: boolean; label: string | null }[];
};

export type TListFilters = {
  status?: TGenerationStatus;
  cursor?: string;
};

export type TDetailTab = "steps" | "trace" | "results" | "api" | "app" | "business";

/** Story 26.6: one checked expectation of the business evaluation, with its evidence. */
export type TEvaluationLine = {
  workflow: string;
  path: string;
  step: string;
  kind: "does" | "refused" | "premature" | "status" | "visible" | "hidden" | "effect";
  actor: string;
  expect: string;
  result: "pass" | "fail" | "blocked" | "unbound" | "n/a";
  evidence: { call?: string | null; as?: string | null; status?: number | null; detail?: string; error?: string; response?: string };
  scored: boolean;
};

export type TEvaluationScore = {
  met: number;
  total: number;
  percent: number;
  decided: number;
  decidedPercent: number;
  counts: Record<"pass" | "fail" | "blocked" | "unbound", number>;
  byKind: Record<string, { pass: number; total: number }>;
};

export type TEvaluationReport = {
  score: TEvaluationScore;
  lines: TEvaluationLine[];
  paths: { workflow: string; path: string; completed: boolean; stopped: string | null; notes: string[] }[];
  binding: { problems: { what: string; reason: string }[]; steps: number };
  judged: { workflow: string; path: string; step?: string; outcome?: string; file: string; canDo?: string; shows?: string; issue?: string; note?: string; control?: string; clarity?: number }[];
  summary: { summary: string; values: { id: string; delivered: string; evidence: string }[]; gaps: string[]; improvements: string[] } | null;
  business: { app?: { name: string; purpose: string }; values?: { id: string; value: string }[]; workflows?: { id: string; name: string; priority?: string }[] };
  screenshots: boolean;
  /** Story 28.6: each role's guided tour, played by the walker on the mocks (information only). */
  tour?: TTourPlay[];
};

export type TTourPlayStep = {
  id: string;
  title?: string;
  role?: string | null;
  kind: "do" | "look" | "note";
  result: "completed" | "skipped" | "stuck" | "not reached";
  reason?: string;
  ms?: number;
  file?: string;
};

export type TTourPlay = {
  role: string | null;
  login: string | null;
  error?: string;
  tours: { id: string; name?: string; completed: boolean; steps: TTourPlayStep[] }[];
};

/** Story 26.6: the latest business evaluation of a generation (information only, never its status). */
export type TEvaluation = {
  evaluationId: string;
  status: "PENDING" | "RUNNING" | "DONE" | "FAILED";
  trigger: "auto" | "manual";
  provider: string | null;
  /** Story 26.7: the generation whose expectations this app was checked against (null: its own). */
  expectationsFrom: string | null;
  progress: string | null;
  score: TEvaluationScore | null;
  report: TEvaluationReport | null;
  usage: { costUsd?: number; inputTokens?: number; outputTokens?: number; calls?: unknown[] } | null;
  error: string | null;
  createdAt: string | null;
  finishedAt: string | null;
};

/** Story 26.6: what `GET …/evaluation` answers for a generation with bound workflows: its latest run, or none yet. */
export type TEvaluationState = TEvaluation | { status: "NONE"; generationId: string };

// -- results (Story 9.5) ------------------------------------------------------------------------------------------

export type TArtifact = {
  artifactId: string;
  kind: string;
  name: string;
  size: number;
  sha256: string;
  contentType: string;
  createdAt: string | null;
};

// "warning": failed without blocking (lint, conventions, migration details; Story 18.11), never repaired.
export type TCheckStatus = "passed" | "failed" | "warning" | "skipped" | "not_run";

export type TCheckItem = {
  file?: string;
  line?: number;
  code?: string;
  rule?: string;
  test?: string;
  table?: string;
  operation?: string;
  message?: string;
  hint?: string;
  excerpt?: string;
  status?: string;
  durationMs?: number;
  live?: boolean;
  selector?: string;
  screenshot?: string;
};

export type TCheckRun = {
  attempt: number;
  status: TCheckStatus;
  durationMs: number | null;
  summary: string | null;
  items: TCheckItem[];
  output: string | null;
};

export type TValidationHistory = {
  attempts: number;
  checks: { check: string; runs: TCheckRun[] }[];
};

export type TManifestOperation = {
  operationId: string;
  method: string;
  path: string;
  auth: string;
  policy?: string;
  requestSchema?: string;
  responseSchema?: string;
  statusCodes: number[];
};

export type TFrontendBinding = {
  page: string;
  componentPath: string;
  component: string;
  operationId: string;
  params?: Record<string, unknown>;
};

/** Story 10.2: how to sign in to a generated API, and its seeded demo users. */
export type TManifestAuth = {
  type: string;
  tokenType: string;
  login?: { operationId: string; path: string; loginField: string };
  register?: { operationId: string; path: string };
  me?: { operationId: string; path: string };
  roles?: string[];
  demoUsers?: { login: string; password: string; role: string }[];
};

/** Story 10.7: where a preview's emails land (the shared Mailpit, filtered to this generation). */
export type TManifestEmail = {
  inbox: string;
  emails: string[];
};

export type TManifest = {
  manifestVersion: string;
  generationId: string;
  generatorVersion: string;
  templateRef: string | null;
  architecture: string;
  framework: string;
  engine: string;
  project: { name: string; slug: string } | null;
  /** Absent in static generations (no backend). */
  api?: { openapiArtifactId: string | null; basePath: string; source: "openapi" | "plan" };
  operations: TManifestOperation[];
  contractProblems: { operation: string; message: string }[];
  env: { name: string; required: boolean; secret: boolean; description: string | null }[];
  auth?: TManifestAuth;
  email?: TManifestEmail;
  modules: { name: string; entity: string; path: string }[];
  frontendBindings?: TFrontendBinding[];
  unresolved: { kind?: string; ref?: string; specPath?: string; message?: string; reason?: string }[];
  assumptions: unknown[];
  frontend?: { assets?: TManifestAsset[] };
};

/** A FrontendSpec asset in the manifest (Epic 15): how it ended up rendered, its file and hash. */
export type TManifestAsset = {
  id: string;
  source: string;
  render: "svg-component" | "public-file" | "remote" | "icon" | "placeholder";
  file: string | null;
  sha256: string | null;
  cached?: boolean;
  fallback?: string;
};

export type TFileEntry = { name: string; path: string; type: "dir" | "file"; size: number | null };

export type TFileNode =
  | { path: string; type: "dir"; entries: TFileEntry[] }
  | { path: string; type: "file"; size: number; content: string };

// -- preview (Story 9.6) ------------------------------------------------------------------------------------------

export type TPreviewStatus = "STARTING" | "RUNNING" | "STOPPED" | "FAILED";

export type TPreview = {
  generationId: string;
  kind: "backend" | "frontend";
  status: TPreviewStatus;
  url: string | null;
  openapiUrl: string | null;
  docsUrl: string | null;
  hostPort: number | null;
  startedAt: string | null;
  lastAccessedAt: string | null;
  expiresAt: string | null;
  error: string | null;
  mockApi?: boolean | null;
};

export type TPreviewAction = "start" | "stop" | "restart" | "reset-db" | "touch";

export type TPreviewRequest = {
  ts: string;
  method: string;
  path: string;
  route: string | null;
  operationId: string | null;
  status: number;
  durationMs: number | null;
};

// -- trace (Stories 8.3, 9.4) -------------------------------------------------------------------------------------

export type TSpanKind = "generation" | "lane" | "node" | "engine" | "llm" | "tool" | "check" | "sandbox";

export type TTraceSpan = {
  spanId: string;
  parentId: string | null;
  kind: TSpanKind;
  name: string;
  lane: string;
  status: string;
  error: boolean;
  startedAt: string | null;
  endedAt: string | null;
  durationMs: number | null;
  attrs: Record<string, unknown>;
  refs: { stdout?: string; stderr?: string; patch?: string; output?: string };
};

export type TTrace = {
  generationId: string;
  status: TGenerationStatus;
  traceId: string | null;
  langsmithUrl: string | null;
  spans: TTraceSpan[];
  usage: TUsageRollup;
};

export type TSpanStream = "stdout" | "stderr";

export type TSpanOutput = {
  spanId: string;
  stream: TSpanStream | "patch";
  text: string;
  truncated: boolean;
};
