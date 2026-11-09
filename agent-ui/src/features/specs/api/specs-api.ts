import { apiClient } from "@/lib/api-client";
import type {
  TCreateSpecDraftPayload,
  TDesignRegistry,
  TEngineList,
  TExampleIndex,
  TFrontendImportResult,
  TSpecDraft,
  TSpecKind,
  TSpecPairReport,
  TValidationReport,
} from "../types";

const SPEC_ROUTES: Record<TSpecKind, string> = { backend: "/specs", frontend: "/frontend-specs" };

export function fetchFrontendSpec(id: string) {
  return apiClient.get<{ id: string; raw: string; normalized: Record<string, unknown> | null }>(`/frontend-specs/${id}`);
}

export function validateSpec(kind: TSpecKind, raw: string, signal?: AbortSignal) {
  return apiClient.post<TValidationReport>(`${SPEC_ROUTES[kind]}/validate`, { rawBody: raw, signal });
}

export function fetchSpecSchema(kind: TSpecKind) {
  return apiClient.get<Record<string, unknown>>(`${SPEC_ROUTES[kind]}/schema`);
}

export function checkSpecPair(frontendSpec: unknown, backendSpec: unknown, signal?: AbortSignal) {
  return apiClient.post<TSpecPairReport>("/frontend-specs/check-pair", { json: { frontendSpec, backendSpec }, signal });
}

export function importFrontendSite(raw: string, includeAdminCrud: boolean) {
  return apiClient.post<TFrontendImportResult>("/spec-imports/frontend", {
    rawBody: raw,
    query: { includeAdminCrud },
  });
}

export function createSpecDraft(payload: TCreateSpecDraftPayload) {
  return apiClient.post<{ draftId: string; status: TSpecDraft["status"] }>("/spec-drafts", {
    json: { source: "requirement", ...payload },
  });
}

export function fetchSpecDraft(draftId: string) {
  return apiClient.get<TSpecDraft>(`/spec-drafts/${draftId}`);
}

export function fetchEngines() {
  return apiClient.get<TEngineList>("/engines");
}

/** Epic 30: the ready design plugins by kind (the registry), for the Design panel's choices. */
export function fetchDesignPlugins() {
  return apiClient.get<TDesignRegistry>("/design-plugins");
}

async function fetchStatic<TData>(path: string): Promise<TData> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return (await response.json()) as TData;
}

export function fetchExampleIndex() {
  return fetchStatic<TExampleIndex>("/examples/index.json");
}

export async function fetchExampleText(path: string): Promise<string> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.text();
}
