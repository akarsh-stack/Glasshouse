import { describe, expect, it } from "vitest";
import { STAGES } from "./stages";
import { layoutStages, markActive } from "./stageTimeline";

/*
 * The pipeline trace used to fabricate its first two segments:
 *
 *   const embedEnd = t0 + (now - t0) * 0.35;
 *
 * — a hardcoded 35/65 split of one combined span, while the backend measured
 * the real embed time and threw it away. The README calls each segment "the
 * real measured latency of that stage", so these tests pin that the layout is
 * driven by server numbers and nothing else.
 */

describe("stage order", () => {
  it("matches the order the backend executes: embed, cache, retrieve, generate", () => {
    // The cache decides whether retrieval happens, so it cannot be drawn after it.
    expect(STAGES.map((s) => s.key)).toEqual([
      "embed",
      "cache",
      "retrieve",
      "generate",
    ]);
  });

  it("numbers the nodes 1..4 in that order", () => {
    expect(STAGES.map((s) => s.num)).toEqual([1, 2, 3, 4]);
  });
});

describe("layoutStages", () => {
  it("lays segments end to end from t0 using the measured durations", () => {
    const timings = layoutStages(1000, { embed: 5, cache: 2 });
    expect(timings.embed).toEqual({ start: 1000, end: 1005 });
    expect(timings.cache).toEqual({ start: 1005, end: 1007 });
  });

  it("gives each segment exactly its measured duration", () => {
    const timings = layoutStages(0, { embed: 12.5, cache: 0.4, retrieve: 7.1 });
    expect(timings.embed!.end! - timings.embed!.start).toBeCloseTo(12.5);
    expect(timings.cache!.end! - timings.cache!.start).toBeCloseTo(0.4);
    expect(timings.retrieve!.end! - timings.retrieve!.start).toBeCloseTo(7.1);
  });

  it("orders segments by the pipeline, not by key insertion order", () => {
    const timings = layoutStages(0, { retrieve: 10, embed: 1, cache: 2 });
    expect(timings.embed!.start).toBe(0);
    expect(timings.cache!.start).toBe(1);
    expect(timings.retrieve!.start).toBe(3);
  });

  it("omits stages with no measurement rather than inventing a zero", () => {
    const timings = layoutStages(0, { embed: 4 });
    expect(timings.cache).toBeUndefined();
    expect(timings.retrieve).toBeUndefined();
  });

  it("keeps a zero-duration stage, which is a real measurement", () => {
    // A cache hit serves chunks from the cache: retrieval genuinely took 0 ms.
    const timings = layoutStages(0, { embed: 4, cache: 1, retrieve: 0 });
    expect(timings.retrieve).toEqual({ start: 5, end: 5 });
  });

  it("preserves earlier stages when a later measurement arrives", () => {
    const first = layoutStages(100, { embed: 5, cache: 2 });
    const second = layoutStages(100, { embed: 5, cache: 2, retrieve: 8 });
    expect(second.embed).toEqual(first.embed);
    expect(second.cache).toEqual(first.cache);
    expect(second.retrieve).toEqual({ start: 107, end: 115 });
  });
});

describe("markActive", () => {
  it("opens the in-flight stage at the given clock, with no end", () => {
    const timings = markActive(layoutStages(0, { embed: 4 }), "cache", 250);
    expect(timings.cache).toEqual({ start: 250, end: null });
  });

  it("leaves completed stages untouched", () => {
    const timings = markActive(layoutStages(0, { embed: 4 }), "cache", 250);
    expect(timings.embed).toEqual({ start: 0, end: 4 });
  });
});
