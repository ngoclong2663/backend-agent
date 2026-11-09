import data from "@/content/app.json";

/** One action of a section (Story 22.3): a link to a page, or a mutation (with a confirm, or a form in a dialog). */
export type TAppAction = {
  id: string;
  label: string;
  /** Story 22.7: `pay` starts the payments plugin's checkout. */
  kind: "link" | "mutation" | "pay";
  page?: string;
  params?: Record<string, unknown>;
  operationId?: string;
  form?: string;
  confirm?: string | boolean;
  /** Story 22.7: a fixed request body (a transition: `{status: "CONFIRMED"}`) and the `allowedActions` entry it needs. */
  body?: Record<string, unknown>;
  allow?: string;
  variant?: "default" | "outline" | "secondary" | "ghost" | "destructive";
  onSuccess?: { toast?: string; navigate?: string };
};

export type TAppLink = { page: string; label: string; params?: Record<string, unknown> };

export type TListControls = {
  search?: boolean;
  filters?: string[];
  sort?: string[];
  /** Story 23.4: a date range per date field (`<field>From`, `<field>To`) and what one call may load. */
  ranges?: { field: string; from: string; to: string }[];
  maxLimit?: number;
};

/** A section's content as the screen planner writes it; each component reads its part. */
export type TAppContent = {
  entity?: string;
  title?: string;
  label?: string;
  style?: "table" | "cards";
  controls?: TListControls;
  actions?: TAppAction[];
  create?: TAppLink;
  tab?: string;
  variant?: "recent" | "summary" | "signIn" | "signUp" | "success" | "cancel";
  /** Story 22.7 (`AppLinks`): link a record (a picker on the linked entity's list) and unlink one. */
  add?: { operationId: string; field: string; reference: NonNullable<TFormField["reference"]> };
  remove?: { operationId: string; param: string };
  kind?: "figure" | "bar" | "line" | "area" | "pie";
  groupBy?: string;
  fn?: string;
  field?: string;
};

/** One app section as the screen planner wrote it (Epic 22): its binding is in `data`, `form` and `content`. */
export type TAppSection = {
  id: string;
  component: string;
  content?: TAppContent;
  data?: {
    kind: "operation";
    operationId: string;
    action: string | null;
    params: Record<string, unknown>;
    fields: string[];
  };
  form?: string;
};

export type TAppPage = { title: string; route: string; sections: TAppSection[] };

export type TAppNavItem = { label: string; href: string; icon: string };

export type TFieldType =
  | "string"
  | "text"
  | "integer"
  | "number"
  | "boolean"
  | "date"
  | "datetime"
  | "enum"
  | "reference"
  | "summary"
  | "list"
  | "object"
  | "image"
  | "file"
  | "video"
  | "audio"
  | "subtitles";

export type TAppEntity = {
  label: string;
  plural: string;
  displayField?: string;
  listFields: string[];
  listStyle: "table" | "cards";
  detailFields: string[];
  fieldLabels: Record<string, string>;
  help: Record<string, string>;
  fields: Record<string, { type: TFieldType; values?: string[]; urlField?: string }>;
  /** Epic 29 (D3): a media field's subtitle tracks: the record's own `subtitles` fields, or a child entity's records. */
  tracks?: Record<string, TTrackSpec[]>;
  references: Record<string, { summary: string; entity: string; href?: string | null }>;
  detail?: string | null;
  list?: string | null;
  /** The list operation that names this entity's records (a parent's name in a chart, a picker in 22.6). */
  listOperation?: string | null;
  /** Story 23.9: `roles` (and signed-out callers) see only the records where `where` holds; the backend decides. */
  visibility?: { roles: string[]; where: Record<string, unknown> };
};

export type TTrackSpec = {
  shape: "field" | "child";
  entity: string;
  field: string;
  parent?: string;
  language?: string | null;
  label?: string | null;
  listOperation?: string | null;
};

export type TFormField = {
  name: string;
  type: string;
  label?: string;
  required?: boolean;
  hidden?: boolean;
  value?: unknown;
  values?: string[];
  min?: number;
  max?: number;
  maxLength?: number;
  placeholder?: string;
  /** A hint under the field (the outline's `help`). */
  help?: string;
  /** A number's currency (ISO 4217; shown as a prefix) or unit (a suffix). */
  currency?: string;
  unit?: string;
  /** A reference picked by its name from the parent's list (Story 22.6); the form sends the record's id. */
  reference?: {
    entity: string;
    listOperation: string;
    detailOperation?: string;
    labelField?: string;
    searchParam?: string;
    limitParam?: string;
    pageSize?: number;
  };
  /** Story 22.7: a file or image uploaded through the storage plugin's presigned URL; the form sends its key. */
  upload?: { presign: string; entity: string; field: string; kind?: "file" | "image" | "video" | "audio" | "subtitles"; accept?: string[]; maxSize?: number };
  /** Story 22.7: an enum limited to the states the record may move to (`transition:<STATE>` in `allowedActions`). */
  transition?: boolean;
};

export type TAppForm = {
  operationId: string;
  params?: Record<string, unknown>;
  load?: { operationId: string; params?: Record<string, unknown> };
  fields: TFormField[];
  submitLabel?: string;
  onSuccess?: { toast?: string; navigate?: string };
  /** Story 28.3: values "Fill with an example" types in (the contract's success scenario, by field). */
  example?: Record<string, unknown>;
};

export type TAppError = { status: number; code: string; message: string; fields?: string[] };

/** Story 22.7: how the app signs in (auth-jwt). */
export type TAppAuth = {
  login: { operationId: string; path: string };
  register: { operationId: string; path: string | null };
  me: { operationId: string; path: string };
  loginField: string;
  signIn: string;
  signUp: string | null;
  demoUsers: { login: string; role: string }[];
  password: string | null;
};

/** Story 22.7: who may call an operation: signed in, and the roles of a role policy. */
export type TAccess = { secured: boolean; roles?: string[] };

/** Epic 23: which field plays which part on a card or a row. */
export type TFieldRoles = {
  media?: string;
  title?: string;
  subtitle?: string;
  meta?: string[];
  badge?: string;
  stat?: string;
  price?: string;
  avatar?: string;
  /** Epic 29: a number of seconds (or a `video` / `audio` field's own length), shown as m:ss on cards. */
  duration?: string;
};

/** Epic 30: a list-view plugin's name (`templates/design/list-view/*`); the generated `design-registry.ts` maps it. */
export type TListView = string;
export type TCardAspect = "wide" | "portrait" | "square" | "auto";

/** Epic 23: how one entity's records are shown. Epic 30: every value names a design plugin of its kind. */
export type TEntityDesign = {
  view: TListView;
  roles: TFieldRoles;
  detailView?: string;
  filtersStyle?: string;
  /** Story 30.4: the anatomy of one record in grid views, its media's aspect and the grid's columns on wide screens. */
  card?: string;
  aspect?: TCardAspect;
  columns?: number;
  groupBy?: string;
  dateField?: string;
  endField?: string;
};

/** Epic 23: one layout (the app's, or an area's): the frame, the home and the entities' views. */
export type TDesign = {
  archetype: string;
  shell: string;
  mobileNav: "drawer" | "bottom-tabs";
  frame: "narrow" | "standard" | "wide" | "full";
  density?: "compact" | "comfortable" | "spacious";
  homeView: string;
  mainEntity: string | null;
  entities: Record<string, TEntityDesign>;
  looks: { recipe: string; reason?: string }[];
  recipe?: string;
  /** Story 30.6: the font pairing plugin the theme was set with (informative; the CSS already carries it). */
  fontPairing?: string;
};

/** Story 23.10: a group of roles with its own routes (`prefix`) and layout. */
export type TArea = { id: string; label: string; roles: string[]; prefix: string; design: Partial<TDesign> };

export type TPhotoCredit = { name: string; profileUrl: string; sourceUrl: string };
export type TVideoCredit = { provider: "youtube" | "pixabay"; name: string; profileUrl?: string; sourceUrl: string; title?: string };

/** Epic 27: the credit of a seeded stock photo, by its URL (none for an upload or an outside link). */
export function photoCredit(url: string | null | undefined): TPhotoCredit | null {
  return (url && app.photoCredits?.[url]) || null;
}

/** Epic 31: the credit of a seeded sample video, by its URL (none for an upload). */
export function videoCredit(url: string | null | undefined): TVideoCredit | null {
  return (url && app.videoCredits?.[url]) || null;
}

/** Epic 31: the id of a YouTube link (`youtube.com/watch?v=`, `youtu.be/`, an embed), else null. */
export function youtubeId(url: string | null | undefined): string | null {
  if (!url) return null;
  const match = /(?:youtube\.com\/watch\?(?:.*&)?v=|youtu\.be\/|youtube(?:-nocookie)?\.com\/embed\/)([A-Za-z0-9_-]{6,})/.exec(url);
  return match ? match[1] : null;
}

export type TApp = {
  name: string;
  tagline: string | null;
  icon: string;
  home: string;
  density: "compact" | "comfortable" | "spacious";
  locale: string;
  nav: TAppNavItem[];
  pages: Record<string, TAppPage>;
  routes: Record<string, string>;
  entities: Record<string, TAppEntity>;
  forms: Record<string, TAppForm>;
  errors: Record<string, TAppError[]>;
  auth: TAppAuth | null;
  access: Record<string, TAccess>;
  design: TDesign;
  areas: TArea[];
  /** Story 26.4: the guided tour of the core business workflows (none: no tour). */
  workflows?: TWorkflows | null;
  /** Epic 27: seeded stock photos by URL and who took them (shown with the photo). */
  photoCredits?: Record<string, TPhotoCredit>;
  /** Epic 29: which media kinds the app has (the shell adds the listening bar for audio). */
  media?: { video: boolean; audio: boolean; subtitles: boolean };
  /** Epic 31: seeded sample videos by URL and their provider's credit (shown under the player). */
  videoCredits?: Record<string, TVideoCredit>;
};

/** Story 26.4: one step of a workflow tour: who does it, where, and the action that performs it. Epic 28: its
 *  `kind` (`do`: the user performs the operation and the tour waits; `look`: a section to read, Next; `note`: the app
 *  does it, or another role), the business record it acts on and what makes a record ready for it (`needs`). */
export type TTourStepKind = "do" | "look" | "note";
export type TTourStep = {
  id: string;
  role: string | null;
  actor: string;
  title: string;
  operationId?: string | null;
  page?: string;
  route?: string;
  target?: { section: string; action: string | null };
  automatic?: boolean;
  skip?: string;
  kind?: TTourStepKind;
  record?: string;
  statusAfter?: string;
  needs?: { step: string; role?: string | null; status?: string };
};

export type TTour = { id: string; name: string; outcome?: string; roles: string[]; steps: TTourStep[] };
export type TWorkflows = { version: string; tours: TTour[] };

export type TRecord = Record<string, unknown> & { id?: unknown; allowedActions?: string[] };
export type TRouteParams = Record<string, string | string[] | undefined>;

/** The app's screens (`src/content/app.json`, generated from the FrontendSpec). */
export const app = data as unknown as TApp;

/** `$route.<name>`, `$record.<field>` and `$query.<name>` become the route's parameter, the record's value and the
 *  address's query parameter. */
export function resolveValue(value: unknown, route: TRouteParams, record?: TRecord): unknown {
  if (typeof value !== "string") return value;
  if (value.startsWith("$query.")) {
    return typeof window === "undefined" ? undefined : (new URLSearchParams(window.location.search).get(value.slice(7)) ?? undefined);
  }
  if (value.startsWith("$route.")) {
    const found = route[value.slice("$route.".length)];
    return Array.isArray(found) ? found[0] : found;
  }
  if (value.startsWith("$record.") && record) return record[value.slice("$record.".length)];
  return value;
}

export function resolveParams(
  params: Record<string, unknown> | undefined,
  route: TRouteParams,
  record?: TRecord,
): Record<string, unknown> {
  return Object.fromEntries(Object.entries(params ?? {}).map(([name, value]) => [name, resolveValue(value, route, record)]));
}

/** A page's href: its route with `[param]` filled from the params (and `[id]` from the record or the route). */
export function pageHref(page: string, params: Record<string, unknown> = {}, route: TRouteParams = {}): string {
  const pattern = app.routes[page] ?? page;
  return pattern.replace(/\[([A-Za-z0-9_]+)\]/g, (_, name: string) => {
    const value = params[name] ?? resolveValue(`$route.${name}`, route);
    return encodeURIComponent(String(value ?? ""));
  });
}

/** Whether a record allows an action (Story 10.0b `allowedActions`): the backend decides, the kit only reads. Links
 *  that only show a record are always allowed; records without the list allow everything. */
export function allowed(record: TRecord | undefined, action: TAppAction): boolean {
  const list = record?.allowedActions;
  if (!Array.isArray(list)) return !action.allow; // a transition or a payment needs the record to allow it
  if (action.allow) return list.includes(action.allow);
  if (action.kind === "link") return action.id !== "edit" || list.includes("update");
  if (action.id === "delete") return list.includes("delete");
  return action.operationId ? list.includes(action.operationId) || list.includes(action.id) : true;
}

/** An enum value as a label: `in_progress` → `In progress`. */
export function enumLabel(value: string): string {
  const words = value.replace(/_/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The signed-in user as the kit sees them (Story 22.7; `enabled: false` without the auth plugin). */
export type TSession = {
  enabled: boolean;
  ready: boolean;
  user: (TRecord & { role?: string }) | null;
};

/** Whether this user may call an operation (Story 22.7): anyone without auth or for an open operation; a signed-in
 *  user for a secured one; one of its roles for a role policy. The backend decides again; this only hides. */
export function canUse(operationId: string | undefined, session: TSession): boolean {
  const rule = operationId ? app.access?.[operationId] : undefined;
  if (!rule || !session.enabled) return true;
  if (!session.user) return false;
  return !rule.roles?.length || rule.roles.includes(String(session.user.role));
}

/** The operation a page stands on: its first section's binding or form. */
export function pageOperation(pageId: string): string | undefined {
  const section = app.pages[pageId]?.sections[0];
  return section?.data?.operationId ?? (section?.form ? app.forms[section.form]?.operationId : undefined);
}

export function fieldLabel(entity: TAppEntity | undefined, field: string): string {
  const label = entity?.fieldLabels?.[field];
  if (label) return label;
  const words = field.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase();
}

/** The name of a record: its display field, else its id. */
export function recordTitle(entity: TAppEntity | undefined, record: TRecord | undefined): string {
  if (!record) return "";
  const value = entity?.displayField ? record[entity.displayField] : undefined;
  return value === undefined || value === null || value === "" ? String(record.id ?? "") : String(value);
}

/** The records of a list response (`{items, total}`, or an array) and the total. */
export function listOf(response: unknown): { records: TRecord[]; total: number } {
  if (Array.isArray(response)) return { records: response as TRecord[], total: response.length };
  if (response && typeof response === "object" && Array.isArray((response as { items?: unknown }).items)) {
    const { items, total } = response as { items: TRecord[]; total?: number };
    return { records: items, total: typeof total === "number" ? total : items.length };
  }
  return { records: [], total: 0 };
}
