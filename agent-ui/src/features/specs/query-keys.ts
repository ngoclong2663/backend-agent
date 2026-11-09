import type { TSpecKind } from "./types";

export const specKeys = {
  all: ["specs"] as const,
  schema: (kind: TSpecKind) => [...specKeys.all, "schema", kind] as const,
  validation: (kind: TSpecKind, text: string) => [...specKeys.all, "validation", kind, text] as const,
  pair: (frontendText: string, backendText: string) => [...specKeys.all, "pair", frontendText, backendText] as const,
  examples: () => [...specKeys.all, "examples"] as const,
  draft: (draftId: string) => [...specKeys.all, "draft", draftId] as const,
  engines: () => ["engines"] as const,
  designPlugins: () => ["design-plugins"] as const,
  uploads: () => ["uploads"] as const,
};
