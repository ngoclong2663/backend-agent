"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  createSpecDraft,
  fetchDesignPlugins,
  fetchEngines,
  fetchExampleIndex,
  fetchSpecDraft,
  fetchSpecSchema,
  importFrontendSite,
} from "../api/specs-api";
import { specKeys } from "../query-keys";
import type { TCreateSpecDraftPayload, TSpecDraftStatus, TSpecKind } from "../types";

const DRAFT_POLL_MS = 1500;
export const FINISHED_DRAFT: TSpecDraftStatus[] = ["SUCCEEDED", "NEEDS_REVIEW", "FAILED", "CANCELLED"];

export function useSpecSchema(kind: TSpecKind) {
  return useQuery({ queryKey: specKeys.schema(kind), queryFn: () => fetchSpecSchema(kind), staleTime: Infinity });
}

export function useExampleIndex() {
  return useQuery({ queryKey: specKeys.examples(), queryFn: fetchExampleIndex, staleTime: Infinity });
}

export function useEngines() {
  return useQuery({ queryKey: specKeys.engines(), queryFn: fetchEngines, staleTime: 30_000 });
}

/** Epic 30: the design plugin registry (changes only with a deployment). */
export function useDesignPlugins() {
  return useQuery({ queryKey: specKeys.designPlugins(), queryFn: fetchDesignPlugins, staleTime: Infinity });
}

export function useFrontendImport() {
  return useMutation({
    mutationFn: ({ raw, includeAdminCrud }: { raw: string; includeAdminCrud: boolean }) =>
      importFrontendSite(raw, includeAdminCrud),
  });
}

export function useCreateSpecDraft() {
  return useMutation({ mutationFn: (payload: TCreateSpecDraftPayload) => createSpecDraft(payload) });
}

/** A draft job, polled until it finishes (simple status polling is enough, Story 2.4). */
export function useSpecDraft(draftId: string | null) {
  return useQuery({
    queryKey: specKeys.draft(draftId ?? ""),
    queryFn: () => fetchSpecDraft(draftId as string),
    enabled: Boolean(draftId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && FINISHED_DRAFT.includes(status) ? false : DRAFT_POLL_MS;
    },
  });
}
