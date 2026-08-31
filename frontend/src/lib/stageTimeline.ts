import { STAGES } from "./stages";
import type { StageKey, StageTimings } from "../types";

/**
 * Server-measured duration, in milliseconds, for stages that have finished.
 * Absent key means "not measured yet" — which is different from zero.
 */
export type ServerStageMs = Partial<Record<StageKey, number>>;

/**
 * Lay finished stages end to end from `t0`, each occupying exactly the time the
 * backend measured for it.
 *
 * The timeline is in `performance.now()` space so the live animation can share
 * it, but the *widths* come entirely from the server's own stopwatch. This
 * replaces a hardcoded `* 0.35` split of one combined span — the backend had
 * been measuring embed time all along and discarding it, so the two leading
 * segments of the trace were the only numbers in the UI that weren't real.
 */
export function layoutStages(t0: number, durations: ServerStageMs): StageTimings {
  const timings: StageTimings = {};
  let cursor = t0;
  // Walk STAGES rather than Object.keys so the layout follows the pipeline
  // order, not whatever order the events happened to populate the object in.
  for (const stage of STAGES) {
    const ms = durations[stage.key];
    if (ms === undefined) continue;
    timings[stage.key] = { start: cursor, end: cursor + ms };
    cursor += ms;
  }
  return timings;
}

/** Open a stage that is still in flight, so the trace head has something to crawl toward. */
export function markActive(
  timings: StageTimings,
  key: StageKey,
  now: number,
): StageTimings {
  return { ...timings, [key]: { start: now, end: null } };
}
