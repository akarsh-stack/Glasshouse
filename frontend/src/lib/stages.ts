import type { StageKey } from "../types";

export interface StageDef {
  key: StageKey;
  num: number;
  label: string;
  color: string;
}

/**
 * Pipeline order, which is also execution order on the backend. Cache sits
 * *before* Retrieve because it decides whether retrieval happens at all: a hit
 * is served with the chunks that were cached alongside the answer, so no vector
 * search runs. Drawing it third would show a search the server never performed.
 */
export const STAGES: StageDef[] = [
  { key: "embed", num: 1, label: "Embed", color: "#3DDC97" },
  { key: "cache", num: 2, label: "Cache", color: "#FFC24D" },
  { key: "retrieve", num: 3, label: "Retrieve", color: "#A98BFF" },
  { key: "generate", num: 4, label: "Generate", color: "#3FBEF5" },
];

/** Kept in sync with tailwind.config.js — see the palette note there. */
export const STAGE_COLOR: Record<StageKey, string> = {
  embed: "#3DDC97",
  cache: "#FFC24D",
  retrieve: "#A98BFF",
  generate: "#3FBEF5",
};

export const WARN_COLOR = "#FF7A66";
export const INK = {
  950: "#080D1A",
  900: "#101A2E",
  800: "#1C2947",
  700: "#33456F",
  600: "#4A5F94",
  300: "#94A6CC",
  100: "#E4EBFA",
};

/** Map a backend stages_ms key (e.g. "retrieval_ms", "llm_ms") to a stage. */
export function stageForMsKey(key: string): StageKey | null {
  const k = key.toLowerCase();
  if (k.startsWith("embed")) return "embed";
  if (k.startsWith("retriev")) return "retrieve";
  if (k.startsWith("cache")) return "cache";
  if (k.startsWith("llm") || k.startsWith("gen")) return "generate";
  return null;
}

export function labelForMsKey(key: string): string {
  const stage = stageForMsKey(key);
  if (stage === "generate") return "Generate";
  if (stage) return STAGES.find((s) => s.key === stage)!.label;
  return key.replace(/_ms$/, "").replace(/_/g, " ");
}
