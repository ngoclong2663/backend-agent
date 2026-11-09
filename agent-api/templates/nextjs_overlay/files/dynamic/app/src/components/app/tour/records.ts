import { allowed, app, listOf, type TAppAction, type TRecord, type TTourStep } from "../app";
import { fetchOperation } from "../bindings";

/** Story 28.4 (Epic 28 D5): the record a tour step opens is one whose `allowedActions` include the step's action
 *  (the backend decides what a record allows; the kit only reads). The record the previous step made or changed is
 *  tried first, then the record the user is on, then the entity's list. None: the step says which earlier step makes
 *  one (`needs`). */

export type TReady = { id: string } | { none: true };

const LIST_LIMIT = 50;

/** The entity, the action and the record's own read operation behind a step on a record page. */
export function stepPlace(step: TTourStep): { entity?: string; action?: TAppAction; getOperation?: string; listOperation?: string } {
  const page = step.page ? app.pages[step.page] : undefined;
  const section = page?.sections.find((candidate) => candidate.id === step.target?.section);
  const entity = section?.content?.entity ?? page?.sections.find((candidate) => candidate.content?.entity)?.content?.entity;
  const action = section?.content?.actions?.find((candidate) => candidate.id === step.target?.action);
  const detail = entity ? app.entities[entity]?.detail : undefined;
  const detailPage = detail ? Object.values(app.pages).find((candidate) => candidate.route === detail) : undefined;
  const getOperation =
    (section?.data?.action === "get" ? section.data.operationId : undefined) ??
    detailPage?.sections.find((candidate) => candidate.data?.action === "get")?.data?.operationId;
  return { entity, action, getOperation, listOperation: entity ? (app.entities[entity]?.listOperation ?? undefined) : undefined };
}

function qualifies(record: TRecord | undefined, action: TAppAction | undefined): boolean {
  if (!record) return false;
  return action ? allowed(record, action) : true;
}

async function read(getOperation: string | undefined, id: unknown): Promise<TRecord | undefined> {
  if (!getOperation || id === undefined || id === null) return undefined;
  try {
    const found = await fetchOperation(getOperation, { id });
    return found && typeof found === "object" ? (found as TRecord) : undefined;
  } catch {
    return undefined;
  }
}

/** The id of a record the step's action is allowed on: `preferred` (the previous step's record, the one on screen)
 *  first, then the list. */
export async function readyRecord(step: TTourStep, preferred: unknown[], params: Record<string, unknown> = {}): Promise<TReady> {
  const { action, getOperation, listOperation } = stepPlace(step);
  for (const id of preferred) {
    if (id === undefined || id === null || id === "") continue;
    if (!getOperation) return { id: String(id) }; // nothing to check it with: the record is taken as it is
    if (qualifies(await read(getOperation, id), action)) return { id: String(id) };
  }
  if (!listOperation) return { none: true };
  try {
    const listed = listOf(await fetchOperation(listOperation, { ...params, limit: LIST_LIMIT, offset: 0 }));
    const found = listed.records.find((record) => qualifies(record, action));
    if (found?.id !== undefined && found.id !== null) return { id: String(found.id) };
  } catch {
    // the list could not be read: the step stays a note
  }
  return { none: true };
}
