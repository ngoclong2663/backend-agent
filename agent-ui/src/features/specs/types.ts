import type { TDraftSpeed } from "@/features/generations/types";
export type TIssueSeverity = "error" | "warning";

export type TSpecIssue = {
  code: string;
  path: string;
  message: string;
  hint: string | null;
  severity: TIssueSeverity;
  /** Consistency issues only: where the BackendSpec would have to change instead (JSON pointer). */
  backendPath?: string | null;
};

export type TValidationReport = {
  valid: boolean;
  specVersion: string | null;
  errors: TSpecIssue[];
  warnings: TSpecIssue[];
};

/**
 * `checked` is false when a spec is invalid (its own validation says why) or the FrontendSpec is static.
 * `contract` is the BackendSpec's API contract (OpenAPI 3.1) when checked, for the read-only preview.
 */
export type TSpecPairReport = TValidationReport & { checked: boolean; contract?: Record<string, unknown> | null };

export type TImportNote = {
  path: string;
  message: string;
  suggestion: string | null;
};

export type TFrontendBinding = {
  page?: string;
  component?: string;
  componentPath?: string;
  operationId?: string;
  params?: Record<string, unknown>;
  [key: string]: unknown;
};

export type TSeedBlock = {
  entity: string;
  records: Record<string, unknown>[];
};

export type TFrontendImportResult = {
  backendSpec: Record<string, unknown>;
  seed: TSeedBlock[];
  assumptions: TImportNote[];
  unresolved: TImportNote[];
  bindings: TFrontendBinding[];
  validation: TValidationReport;
};

export type TExampleFile = { name: string; path: string };

export type TExampleIndex = {
  specs?: TExampleFile[];
  frontend?: TExampleFile[];
  "frontend-specs"?: TExampleFile[];
  requirements?: TExampleFile[];
};

export type TEngineInfo = {
  name: string;
  available: boolean;
  reason: string | null;
  /** Story 18.10: an API engine drafts specs but writes no code. */
  draftsOnly?: boolean;
  /** Story 22.8: the engine may draft specs (API engines and the fake; CLI engines write code only). */
  drafts?: boolean;
};

export type TEngineList = {
  default: string;
  /** Story 18.10: the engine that drafts specs unless the user picks another. */
  draftDefault?: string | null;
  engines: TEngineInfo[];
  reportedByWorker: boolean;
  reportedAt: string | null;
  /** Epic 27 / 31: the photo provider and the video providers the agent has on. */
  media?: { photos: string; videos: string[] } | null;
};

export type TSpecKind = "backend" | "frontend";

/** Epic 30: one ready design plugin as the registry describes it. */
export type TDesignPlugin = {
  name: string;
  label: string;
  choose: string;
  archetypes: string[];
  needs: string[];
  fallback: string | null;
  family?: "quiet" | "soft" | "bold";
  preview?: string;
};
/** Epic 30: the registry by kind (`shell`, `list-view`, `detail-view`, `home`, `filters`, `card`, `recipe`, `font-pairing`). */
export type TDesignRegistry = Record<string, TDesignPlugin[]>;

export type TSpecTab = "requirement" | "import" | "json" | "frontend" | "contract";

// -- Requirement drafting (Stories 2.4, 12.4) ---------------------------------------------------------------------

export type TDraftMode = "backend" | "static" | "dynamic";

export type TSpecDraftStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "NEEDS_REVIEW" | "FAILED" | "CANCELLED";

export type TDraftNote = TImportNote & { spec: TSpecKind | null };

export type TCreateSpecDraftPayload = {
  mode: TDraftMode;
  requirementText: string;
  requirementFileName?: string | null;
  engine?: string | null;
  draftSpeed?: TDraftSpeed | null;
};

export type TDraftUsage = {
  engineMs?: number;
  modelCalls?: number;
  inputTokens?: number;
  outputTokens?: number;
  costUsd?: number;
  unpriced?: number;
  images?: { count: number; cached: number; costUsd: number };
};

export type THeroLayout = "split" | "centered" | "banner" | "stage" | "type" | "stacked" | "collage" | "vertical";
export type TTone = Record<"energy" | "finish" | "density" | "weight" | "seriousness", number>;

/**
 * A design direction for a drafted site: a direction card the engine wrote, checked and filled by the agent
 * (Story 20.4, `source: "card"`), or one from UI UX Pro Max's data (Story 12.6). Cards also carry the home page
 * they compose from the draft's pool (Story 20.9), section forms and a page rhythm.
 */
export type TDesignDirection = {
  label: string;
  productType: string;
  pattern: string;
  palette: string;
  fontPairing: string;
  source: string;
  style: string;
  photoStyle?: string;
  heroVariant: THeroLayout;
  homeOrder: string[];
  avoid: string[];
  effects: string[];
  name?: string;
  concept?: string;
  engine?: string | null;
  givesUp?: string;
  fit?: number;
  tone?: TTone | null;
  keyVisual?: string | null;
  home?: string[];
  sectionForms?: Record<string, string>;
  rhythm?: "uniform" | "alternate" | "dividers";
  notes?: string[];
  theme: {
    style: string;
    colorScheme: "light" | "dark" | "light-dark";
    colors: Record<string, string>;
    typography: { headingFont: string; bodyFont: string; scale: string } & Record<string, unknown>;
    radius: string;
    density: string;
    direction: Record<string, unknown>;
  } & Record<string, unknown>;
};

/** A section of the drafted home page (the pool directions compose their home pages from, Story 20.9). */
export type TPoolSection = { id: string; component?: string } & Record<string, unknown>;

/**
 * The directions offered with a draft; `selected` is the one the draft was filled from. `pool` holds the drafted
 * home sections, so switching restores sections a direction left out; `seed` reproduces the cards.
 */
export type TDraftDesign = {
  selected: number;
  directions: TDesignDirection[];
  seed?: number;
  pool?: TPoolSection[];
  required?: string[];
};

export type TSpecDraft = {
  draftId: string;
  status: TSpecDraftStatus;
  progress: string | null;
  source: "requirement" | "frontend";
  mode: TDraftMode;
  engine: string;
  attempts: number;
  requirement: { text: string | null; format: "text" | "markdown" | null; fileName: string | null };
  backendSpec: Record<string, unknown> | null;
  frontendSpec: Record<string, unknown> | null;
  assumptions: TDraftNote[];
  unresolved: TDraftNote[];
  design: TDraftDesign | null;
  /** Epic 26: the business workflows found before the draft, their frozen expectations, the binding and the tour. */
  business?: TDraftBusiness | null;
  validation: { backend: TValidationReport | null; frontend: TValidationReport | null; pair: TValidationReport | null };
  usage: TDraftUsage;
  error: string | null;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
};

/** Epic 26 (Stories 26.1-26.3): what the draft knows about the business, read-only in the review. */
export type TDraftBusiness = {
  provider?: string;
  error?: string;
  business?: {
    app?: { name: string; purpose: string };
    values?: { id: string; value: string; measure?: string }[];
    actors?: { id: string; name: string }[];
    workflows?: {
      id: string;
      name: string;
      priority?: "core" | "later";
      trigger?: string;
      outcome?: string;
      steps: { id: string; actor: string; action: string; statusAfter?: string; rule?: string }[];
      branches?: { id: string; after: string; condition: string; steps: { id: string; actor: string; action: string }[] }[];
    }[];
    scope?: { goldenPath?: string; excluded?: string[] };
  };
  texts?: { workflow: string; path: string; step: string; texts: string[] }[];
  binding?: { problems?: { what: string; reason: string }[] };
};
