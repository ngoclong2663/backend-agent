"use client";

import { useEffect, useRef } from "react";
import type { BaseSyntheticEvent } from "react";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { useEngines } from "@/features/specs/hooks/use-spec-queries";
import { ApiError } from "@/lib/api-client";
import { useSpecDraftStore } from "@/store/spec-draft-store";
import {
  ENGINE_NAMES,
  generationOptionsSchema,
  type TGenerationOptionsFormValues,
} from "../schemas/generation-options-schema";
import type { TCreateGenerationPayload, TGenerationMode } from "../types";
import { useCreateGeneration } from "./use-generation-mutations";

const DEFAULT_OPTIONS: TGenerationOptionsFormValues = {
  engine: "claude_code",
  draftEngine: "antigravity_json",
  maxRepairAttempts: 3,
  runTests: true,
  generateDockerfile: true,
  deployPreview: true,
  frontend: { runTests: true, generatePreview: true, mockApi: true },
};

type TNewGenerationInput = {
  mode: TGenerationMode;
  backendSpec: unknown;
  frontendSpec: unknown;
  draftId: string | null;
  canSubmit: boolean;
  onCreated: () => void;
};

/** The request body per mode (the API answers 422 MODE_INPUT_MISMATCH to any other combination). */
function buildPayload(
  mode: TGenerationMode,
  backendSpec: unknown,
  frontendSpec: unknown,
  { frontend, ...options }: TGenerationOptionsFormValues,
): TCreateGenerationPayload {
  if (mode === "backend") return { backendSpec, options };
  if (mode === "static") return { mode, frontendSpec, options: { ...options, frontend } };
  return { mode, frontendSpec, backendSpec, options: { ...options, frontend } };
}

function isEngineName(value: string): value is TGenerationOptionsFormValues["engine"] {
  return (ENGINE_NAMES as readonly string[]).includes(value);
}

/**
 * Options form + submit. The Idempotency-Key is reused while the payload is unchanged, so a double click
 * (or a retry after a network error) cannot create two generations.
 */
export function useNewGeneration({
  mode,
  backendSpec,
  frontendSpec,
  draftId,
  canSubmit,
  onCreated,
}: TNewGenerationInput) {
  const router = useRouter();
  const engines = useEngines();
  const create = useCreateGeneration();
  const lastSubmission = useRef<{ body: string; key: string } | null>(null);

  const form = useForm<TGenerationOptionsFormValues>({
    resolver: zodResolver(generationOptionsSchema),
    defaultValues: DEFAULT_OPTIONS,
  });

  const defaultEngine = engines.data?.default;
  const defaultDraftEngine = engines.data?.draftDefault;
  useEffect(() => {
    if (defaultEngine && isEngineName(defaultEngine) && !form.formState.dirtyFields.engine) {
      form.setValue("engine", defaultEngine);
    }
    if (defaultDraftEngine && isEngineName(defaultDraftEngine) && !form.formState.dirtyFields.draftEngine) {
      form.setValue("draftEngine", defaultDraftEngine);
    }
  }, [defaultEngine, defaultDraftEngine, form]);

  const submitOptions = async (options: TGenerationOptionsFormValues) => {
    if (!canSubmit) return;
    const payload = { ...buildPayload(mode, backendSpec, frontendSpec, options), ...(draftId ? { draftId } : {}) };
    const body = JSON.stringify(payload);
    if (lastSubmission.current?.body !== body) {
      lastSubmission.current = { body, key: crypto.randomUUID() };
    }
    try {
      const created = await create.mutateAsync({ payload, idempotencyKey: lastSubmission.current.key });
      onCreated();
      router.push(`/generations/${created.generationId}`);
    } catch (error) {
      toast.error(error instanceof ApiError ? `${error.code}: ${error.message}` : "Could not start the generation");
    }
  };
  const handleSubmit = (event?: BaseSyntheticEvent) => form.handleSubmit(submitOptions)(event);

  const generateFromRequirement = async (requirement: { text: string; fileName: string | null }) => {
    const options = form.getValues();
    const payload: TCreateGenerationPayload = {
      mode,
      requirement: {
        text: requirement.text,
        fileName: requirement.fileName,
      },
      options: {
        ...options,
        frontend: mode !== "backend" ? options.frontend : undefined,
        draftSpeed: useSpecDraftStore.getState().draftSpeed ?? undefined,
      },
    };
    const key = crypto.randomUUID();
    try {
      const created = await create.mutateAsync({ payload, idempotencyKey: key });
      onCreated();
      router.push(`/generations/${created.generationId}`);
    } catch (error) {
      toast.error(error instanceof ApiError ? `${error.code}: ${error.message}` : "Could not start the generation");
    }
  };

  return {
    form,
    handleSubmit,
    generateFromRequirement,
    engines: engines.data?.engines ?? [],
    enginesReportedByWorker: engines.data?.reportedByWorker ?? true,
    media: engines.data?.media ?? null,
    isSubmitting: create.isPending,
  };
}
