/**
 * Epic 23: an app draft's design brief, read from and written into the FrontendSpec text (`app.design`). Every edit is
 * presentation only (the look, the shell, an entity's view): the kit reads it; bindings and screens do not change.
 */

// Epic 30 (Story 30.2): the values of each axis come from the design plugin registry (`useDesignPlugins`), never from
// a list kept here; an edit is accepted when the registry offers the value (checked by the caller).

export type TLook = { recipe: string; reason?: string };
/** What the requirement says about the look (`app.design.requested`); code applied it over the design data's pick. */
export type TRequestedLook = { words: string | null; colors: { name: string; value: string }[]; others: string[] };
export type TAppDesign = {
  archetype: string | null;
  shell: string | null;
  homeView: string | null;
  mainEntity: string | null;
  looks: TLook[];
  recipe: string | null;
  views: { entity: string; view: string; detailView: string | null; card: string | null; filtersStyle: string | null }[];
  areas: { id: string; label: string; roles: string[] }[];
  replaced: string[];
  requested: TRequestedLook | null;
};

const REQUESTED_COLORS = ["accent", "background", "text"] as const;
const REQUESTED_OTHERS = ["scheme", "headingFont", "corners", "photos"] as const;

function requestedLook(value: unknown): TRequestedLook | null {
  const raw = obj(value);
  const colors = REQUESTED_COLORS.flatMap((name) => {
    const color = str(raw[name]);
    return color && /^#[0-9a-fA-F]{6}$/.test(color) ? [{ name, value: color }] : [];
  });
  const others = REQUESTED_OTHERS.flatMap((name) => {
    const item = str(raw[name]);
    return item ? [`${name === "headingFont" ? "headings" : name}: ${item}`] : [];
  });
  return colors.length || others.length ? { words: str(raw.words), colors, others } : null;
}

function parse(text: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(text) as unknown;
    return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function obj(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** The brief of an app FrontendSpec, or null for a site, an older app or text that is not JSON. */
export function readAppDesign(text: string): TAppDesign | null {
  const spec = parse(text);
  if (!spec || obj(spec.project).flow !== "app") return null;
  const app = obj(spec.app);
  if (!("design" in app)) return null;
  const design = obj(app.design);
  const looks = (Array.isArray(design.looks) ? design.looks : []).flatMap((look) => {
    const recipe = str(obj(look).recipe);
    return recipe ? [{ recipe, reason: str(obj(look).reason) ?? undefined }] : [];
  });
  return {
    archetype: str(design.archetype),
    shell: str(design.shell),
    homeView: str(design.homeView),
    mainEntity: str(design.mainEntity),
    looks,
    recipe: str(design.recipe) ?? looks[0]?.recipe ?? null,
    views: Object.entries(obj(design.entities)).map(([entity, value]) => ({
      entity,
      view: str(obj(value).view) ?? "table",
      detailView: str(obj(value).detailView),
      card: str(obj(value).card),
      filtersStyle: str(obj(value).filtersStyle),
    })),
    areas: (Array.isArray(app.areas) ? app.areas : []).map((area) => ({
      id: str(obj(area).id) ?? "",
      label: str(obj(area).label) ?? "",
      roles: (Array.isArray(obj(area).roles) ? (obj(area).roles as unknown[]) : []).filter((r): r is string => typeof r === "string"),
    })),
    replaced: (Array.isArray(design.replaced) ? design.replaced : []).filter((line): line is string => typeof line === "string"),
    requested: requestedLook(design.requested),
  };
}

/** The axes of an entity's design a review may switch (Story 30.7), each a design plugin kind. */
export const ENTITY_AXES = [
  { key: "view", kind: "list-view", label: "view" },
  { key: "detailView", kind: "detail-view", label: "detail" },
  { key: "card", kind: "card", label: "card" },
  { key: "filtersStyle", kind: "filters", label: "filters" },
] as const;
export type TEntityAxis = (typeof ENTITY_AXES)[number]["key"];

type TEdit =
  | { recipe: string }
  | { shell: string }
  | { homeView: string }
  | { entity: string; axis: TEntityAxis; value: string }
  | { entity: string; view: string };

/** The text with one design value changed (2-space JSON, as the editor writes), or null when it cannot be applied.
 *  `allowed`: the registry's names for the axis (an unknown value is refused). */
export function editAppDesign(text: string, edit: TEdit, allowed?: readonly string[]): string | null {
  const spec = parse(text);
  if (!spec || obj(spec.project).flow !== "app") return null;
  const value = "recipe" in edit ? edit.recipe : "shell" in edit ? edit.shell : "homeView" in edit ? edit.homeView : "axis" in edit ? edit.value : edit.view;
  if (!value || (allowed && !allowed.includes(value))) return null;
  const app = obj(spec.app);
  const design = { ...obj(app.design) };
  if ("recipe" in edit) design.recipe = value;
  else if ("shell" in edit) design.shell = value;
  else if ("homeView" in edit) design.homeView = value;
  else {
    const axis = "axis" in edit ? edit.axis : "view";
    const entities = { ...obj(design.entities) };
    entities[edit.entity] = { ...obj(entities[edit.entity]), [axis]: value };
    design.entities = entities;
  }
  return JSON.stringify({ ...spec, app: { ...app, design } }, null, 2);
}

/** A short line of the brief for the draft summary. */
export function describeAppDesign(design: TAppDesign): string {
  const parts = [design.archetype, design.shell && `${design.shell} shell`, design.homeView && `opens on ${design.homeView}`];
  return parts.filter(Boolean).join(" · ");
}


/** Story 30.7: "try another layout": a new pick for every layout axis among the registry's candidates for the app's
 *  archetype (the looks stay). The kit falls back where the data lacks what a plugin needs (as `complete_design` would:
 *  a board without a status, shelves without a group), so the result always renders. Returns null for a site. */
export function shuffleAppDesign(text: string, registry: Record<string, { name: string; archetypes: string[] }[]>, random: () => number = Math.random): string | null {
  const spec = parse(text);
  if (!spec || obj(spec.project).flow !== "app") return null;
  const app = obj(spec.app);
  const design = { ...obj(app.design) };
  const archetype = str(design.archetype);
  const pick = (kind: string, current: string | null): string | null => {
    const names = (registry[kind] ?? []).filter((p) => !archetype || p.archetypes.length === 0 || p.archetypes.includes(archetype)).map((p) => p.name);
    const others = names.filter((name) => name !== current);
    if (others.length === 0) return current;
    return others[Math.floor(random() * others.length)] ?? current;
  };
  design.shell = pick("shell", str(design.shell));
  design.homeView = pick("home", str(design.homeView));
  const main = str(design.mainEntity);
  const entities = { ...obj(design.entities) };
  if (main && entities[main]) {
    const entity = { ...obj(entities[main]) };
    entity.view = pick("list-view", str(entity.view));
    entity.detailView = pick("detail-view", str(entity.detailView));
    if ((registry.card ?? []).length) entity.card = pick("card", str(entity.card));
    entities[main] = entity;
  }
  design.entities = entities;
  design.seed = Math.floor(random() * 2 ** 31);
  return JSON.stringify({ ...spec, app: { ...app, design } }, null, 2);
}
