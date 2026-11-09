"use client";

import { useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { useWatch } from "react-hook-form";
import { toast } from "sonner";
import { AppWindow, Braces, FileCode, FileInput, Globe, MessageSquareText, Rocket } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Stack } from "@/components/layout/Stack";
import { prettyJson } from "@/lib/files";
import { DesignPanel } from "@/features/specs/components/DesignPanel";
import { AppDesignPanel } from "@/features/specs/components/AppDesignPanel";
import { readAppDesign } from "@/features/specs/lib/app-design";
import { FrontendImportTab } from "@/features/specs/components/FrontendImportTab";
import { FrontendSpecSummaryPanel } from "@/features/specs/components/FrontendSpecSummaryPanel";
import { JsonEditor } from "@/features/specs/components/JsonEditor";
import { JsonTab } from "@/features/specs/components/JsonTab";
import { RequirementTab } from "@/features/specs/components/RequirementTab";
import { SpecSummaryPanel } from "@/features/specs/components/SpecSummaryPanel";
import { useJsonEditor } from "@/features/specs/hooks/use-json-editor";
import { useSpecPairCheck } from "@/features/specs/hooks/use-spec-pair-check";
import { useSpecDraft } from "@/features/specs/hooks/use-spec-queries";
import { useSpecValidation } from "@/features/specs/hooks/use-spec-validation";
import type { TEditorIssue } from "@/features/specs/hooks/use-spec-validation";
import { summarizeFrontendSpec } from "@/features/specs/lib/frontend-spec-summary";
import { summarizeSpec } from "@/features/specs/lib/spec-summary";
import type { TSpecKind, TSpecTab } from "@/features/specs/types";
import { useSpecDraftHydrated, useSpecDraftStore } from "@/store/spec-draft-store";
import { useGenerationMode } from "../hooks/use-generation-mode";
import { useNewGeneration } from "../hooks/use-new-generation";
import type { TGenerationMode } from "../types";
import { GenerationOptionsForm } from "./GenerationOptionsForm";
import { ModeCards } from "./ModeCards";
import { SpecValidationCard } from "./SpecValidationCard";

const MODE_TABS: Record<TGenerationMode, TSpecTab[]> = {
  backend: ["requirement", "import", "json"],
  static: ["requirement", "frontend"],
  dynamic: ["requirement", "frontend", "json", "contract"],
};

const SUBMIT_LABELS: Record<TGenerationMode, string> = {
  backend: "Generate backend",
  static: "Generate site",
  dynamic: "Generate app",
};

const EMPTY_TEXT: Record<TSpecKind, string> = {
  backend: "Paste, load or import a BackendSpec to validate it.",
  frontend: "Paste, load or upload a FrontendSpec to validate it.",
};

export function NewGenerationView() {
  const { mode, setMode } = useGenerationMode();
  const searchParams = useSearchParams();
  const urlDraftId = searchParams.get("draftId");
  const urlTab = searchParams.get("tab") as TSpecTab | null;
  const urlDraftQuery = useSpecDraft(urlDraftId);
  const loadedDraftRef = useRef<string | null>(null);
  const hydrated = useSpecDraftHydrated();

  const specText = useSpecDraftStore((state) => state.specText);
  const setSpecText = useSpecDraftStore((state) => state.setSpecText);
  const frontendSpecText = useSpecDraftStore((state) => state.frontendSpecText);
  const setFrontendSpecText = useSpecDraftStore((state) => state.setFrontendSpecText);
  const activeTab = useSpecDraftStore((state) => state.activeTab);
  const setActiveTab = useSpecDraftStore((state) => state.setActiveTab);
  const clearDraft = useSpecDraftStore((state) => state.clearDraft);
  const appliedDraft = useSpecDraftStore((state) => state.appliedDraft);
  const setAppliedDraft = useSpecDraftStore((state) => state.setAppliedDraft);
  const setDraftId = useSpecDraftStore((state) => state.setDraftId);
  const setRequirement = useSpecDraftStore((state) => state.setRequirement);

  const editors = { backend: useJsonEditor(), frontend: useJsonEditor() };
  const backend = useSpecValidation("backend", specText);
  const frontend = useSpecValidation("frontend", frontendSpecText, mode === "backend" ? undefined : mode);
  const pair = useSpecPairCheck(
    mode === "dynamic",
    { ...frontend, text: frontendSpecText },
    { ...backend, text: specText },
  );
  const summary = useMemo(() => summarizeSpec(backend.parsed), [backend.parsed]);
  const frontendSummary = useMemo(() => summarizeFrontendSpec(frontend.parsed), [frontend.parsed]);
  // The design directions of the draft the editors were filled from (Story 12.6); an app draft has none.
  const activeDraftId = urlDraftId ?? (mode !== "backend" && appliedDraft?.mode === mode ? appliedDraft.id : null);
  const appliedDraftQuery = useSpecDraft(mode !== "backend" ? activeDraftId : null);
  const design = appliedDraftQuery.data?.design ?? null;

  const canSubmit = {
    backend: backend.isSubmittable,
    static: frontend.isSubmittable,
    // The pair is not the user's to fix: drafts settle it in code; pasted specs are checked by the first step.
    dynamic: frontend.isSubmittable && backend.isSubmittable,
  }[mode];
  const submit = useNewGeneration({
    mode,
    backendSpec: backend.parsed,
    frontendSpec: frontend.parsed,
    // The requirement draft the editors were filled from, so the generation keeps its requirement (2.4, 12.4).
    draftId: appliedDraft?.mode === mode ? appliedDraft.id : null,
    canSubmit,
    onCreated: clearDraft,
  });
  const draftEngine = useWatch({ control: submit.form.control, name: "draftEngine" });

  useEffect(() => {
    useSpecDraftStore.persist.rehydrate();
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (!urlDraftId) {
      loadedDraftRef.current = null;
      return;
    }
    if (!urlDraftQuery.data) return;
    const draft = urlDraftQuery.data;
    if (loadedDraftRef.current === draft.draftId) return;
    loadedDraftRef.current = draft.draftId;

    if (draft.mode && draft.mode !== mode) {
      setMode(draft.mode as TGenerationMode);
    }
    if (draft.backendSpec) {
      setSpecText(prettyJson(draft.backendSpec));
    }
    if (draft.frontendSpec) {
      setFrontendSpecText(prettyJson(draft.frontendSpec));
    }
    if (draft.requirement?.text) {
      setRequirement(draft.requirement.text, draft.requirement.fileName ?? null);
    }
    setDraftId(draft.draftId);
    setAppliedDraft({ id: draft.draftId, mode: draft.mode as TGenerationMode });
    const targetTab =
      urlTab && MODE_TABS[draft.mode as TGenerationMode]?.includes(urlTab)
        ? urlTab
        : draft.mode === "backend"
          ? "json"
          : "frontend";
    setActiveTab(targetTab);
  }, [
    hydrated,
    urlDraftId,
    urlDraftQuery.data,
    urlTab,
    mode,
    setMode,
    setSpecText,
    setFrontendSpecText,
    setRequirement,
    setDraftId,
    setAppliedDraft,
    setActiveTab,
  ]);

  useEffect(() => {
    if (urlDraftId && urlDraftQuery.isError) {
      toast.error("Could not load the specified draft");
    }
  }, [urlDraftId, urlDraftQuery.isError]);

  const tabs = MODE_TABS[mode];
  const tab = tabs.includes(activeTab) ? activeTab : tabs[0];

  const jumpTo = (kind: TSpecKind, issue: TEditorIssue) => {
    setActiveTab(kind === "frontend" ? "frontend" : "json");
    requestAnimationFrame(() => editors[kind].jumpTo(issue));
  };

  if (urlDraftId && (!hydrated || (urlDraftQuery.isLoading && !urlDraftQuery.data))) {
    return <Skeleton className="h-[640px] w-full rounded-xl" />;
  }

  return (
    <Stack gap="lg">
      <ModeCards mode={mode} onChange={setMode} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Tabs value={tab} onValueChange={(value) => setActiveTab(value as TSpecTab)}>
          <TabsList>
            {tabs.includes("requirement") && (
              <TabsTrigger value="requirement">
                <MessageSquareText /> Requirement
              </TabsTrigger>
            )}
            {tabs.includes("import") && (
              <TabsTrigger value="import">
                <FileInput /> Import frontend JSON
              </TabsTrigger>
            )}
            {tabs.includes("frontend") && (
              <TabsTrigger value="frontend">
                {mode === "static" ? <Globe /> : <AppWindow />} FrontendSpec
              </TabsTrigger>
            )}
            {tabs.includes("json") && (
              <TabsTrigger value="json">
                <Braces /> {mode === "dynamic" ? "BackendSpec" : "JSON"}
              </TabsTrigger>
            )}
            {tabs.includes("contract") && (
              <TabsTrigger value="contract">
                <FileCode /> Contract
              </TabsTrigger>
            )}
          </TabsList>
          {tabs.includes("requirement") && (
            <TabsContent value="requirement" className="pt-2" keepMounted>
              <RequirementTab
                mode={mode}
                engine={draftEngine ?? null}
                onGenerateDirect={submit.generateFromRequirement}
                isGenerating={submit.isSubmitting}
              />
            </TabsContent>
          )}
          {tabs.includes("import") && (
            <TabsContent value="import" className="pt-2" keepMounted>
              <FrontendImportTab />
            </TabsContent>
          )}
          {tabs.includes("frontend") && (
            <TabsContent value="frontend" className="pt-2" keepMounted>
              <JsonTab
                kind="frontend"
                text={frontendSpecText}
                onTextChange={setFrontendSpecText}
                editor={editors.frontend}
                issues={frontend.issues}
                parsed={frontend.parsed}
              />
            </TabsContent>
          )}
          {tabs.includes("json") && (
            <TabsContent value="json" className="pt-2" keepMounted>
              <JsonTab
                kind="backend"
                text={specText}
                onTextChange={setSpecText}
                editor={editors.backend}
                issues={backend.issues}
                parsed={backend.parsed}
              />
            </TabsContent>
          )}
          {tabs.includes("contract") && (
            <TabsContent value="contract" className="pt-2">
              {pair.contract ? (
                <Stack gap="xs">
                  <p className="text-sm text-muted-foreground">
                    The API contract (OpenAPI 3.1) both lanes are generated from. Read-only: change the BackendSpec.
                  </p>
                  <JsonEditor path="contract.json" value={JSON.stringify(pair.contract, null, 2)} readOnly />
                </Stack>
              ) : pair.isChecking ? (
                <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
                  <Spinner className="size-4" /> Generating API contract…
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  The contract appears once the FrontendSpec and BackendSpec are both valid.
                </p>
              )}
            </TabsContent>
          )}
        </Tabs>

        <aside className="lg:sticky lg:top-4 lg:self-start">
          <Stack gap="md">
            {mode !== "backend" && (
              <SpecValidationCard
                title={mode === "dynamic" ? "FrontendSpec" : "Validation"}
                validation={frontend}
                emptyText={EMPTY_TEXT.frontend}
                onSelect={(issue) => jumpTo("frontend", issue)}
              />
            )}
            {mode !== "static" && (
              <SpecValidationCard
                title={mode === "dynamic" ? "BackendSpec" : "Validation"}
                validation={backend}
                emptyText={EMPTY_TEXT.backend}
                onSelect={(issue) => jumpTo("backend", issue)}
              />
            )}

            {mode !== "backend" && design && design.directions.length > 0 && (
              <Card size="sm">
                <CardHeader>
                  <CardTitle>Design</CardTitle>
                  <CardDescription>
                    Three directions written for this draft: colours, fonts, the first screen and the home page&apos;s sections.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <DesignPanel design={design} specText={frontendSpecText} onApply={setFrontendSpecText} />
                </CardContent>
              </Card>
            )}

            {mode === "dynamic" && readAppDesign(frontendSpecText) && (
              <Card size="sm">
                <CardHeader>
                  <CardTitle>App design</CardTitle>
                  <CardDescription>The brief code built the screens from: pick a look, a shell and each list&apos;s view.</CardDescription>
                </CardHeader>
                <CardContent>
                  <AppDesignPanel specText={frontendSpecText} onApply={setFrontendSpecText} />
                </CardContent>
              </Card>
            )}

            {mode !== "backend" && (
              <Card size="sm">
                <CardHeader>
                  <CardTitle>{frontendSummary.projectName ?? "Site"}</CardTitle>
                  <CardDescription>What the current FrontendSpec builds.</CardDescription>
                </CardHeader>
                <CardContent>
                  <FrontendSpecSummaryPanel
                    summary={frontendSummary}
                    showOperations={mode === "dynamic"}
                  />
                </CardContent>
              </Card>
            )}

            {mode !== "static" && (
              <Card size="sm">
                <CardHeader>
                  <CardTitle>{summary.projectName ?? "Summary"}</CardTitle>
                  <CardDescription>What the current BackendSpec describes.</CardDescription>
                </CardHeader>
                <CardContent>
                  <SpecSummaryPanel summary={summary} />
                </CardContent>
              </Card>
            )}

            <Card size="sm">
              <form onSubmit={submit.handleSubmit} noValidate>
                <CardHeader>
                  <CardTitle>Options</CardTitle>
                  {!submit.enginesReportedByWorker && (
                    <CardDescription>The worker is not reporting; engine availability may be stale.</CardDescription>
                  )}
                  {submit.media && (
                    <CardDescription data-bga-media-providers>
                      Photos: {submit.media.photos}. Videos: {submit.media.videos.length ? submit.media.videos.join(", ") : "off"}.
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="py-4">
                  <GenerationOptionsForm form={submit.form} engines={submit.engines} mode={mode} />
                </CardContent>
                <CardFooter>
                  <Button type="submit" className="w-full" disabled={!canSubmit || submit.isSubmitting}>
                    {submit.isSubmitting ? <Spinner /> : <Rocket />}
                    {SUBMIT_LABELS[mode]}
                  </Button>
                </CardFooter>
              </form>
            </Card>
          </Stack>
        </aside>
      </div>
    </Stack>
  );
}
