import type { StageKey } from "../types";

export interface StageDef {
  key: StageKey;
  num: number;
  label: string;
  color: string;
}

export const STAGES: StageDef[] = [
  { key: "embed", num: 1, label: "Embed", color: "#7C9E8F" },
  { key: "retrieve", num: 2, label: "Retrieve", color: "#9287C0" },
  { key: "cache", num: 3, label: "Cache", color: "#C7A96B" },
  { key: "generate", num: 4, label: "Generate", color: "#6B95C7" },
];

export const STAGE_COLOR: Record<StageKey, string> = {
  embed: "#7C9E8F",
  retrieve: "#9287C0",
  cache: "#C7A96B",
  generate: "#6B95C7",
};

export const WARN_COLOR = "#C77B6B";
export const INK = {
  950: "#0B1120",
  900: "#111A2E",
  800: "#1A2540",
  700: "#263354",
  300: "#8B99B8",
  100: "#DDE4F2",
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
