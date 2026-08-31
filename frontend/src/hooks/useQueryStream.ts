import { useCallback, useEffect, useRef, useState } from "react";
import { SESSION_ID, streamQuery } from "../lib/api";
import { layoutStages, markActive } from "../lib/stageTimeline";
import type { ServerStageMs } from "../lib/stageTimeline";
import { addTrace } from "../lib/traceStore";
import type {
  CacheStatus,
  QueryError,
  QueryPhase,
  RetrievedChunk,
  StageTimings,
  Tier,
  TraceData,
} from "../types";

export interface QueryStreamState {
  phase: QueryPhase;
  /** Query text of the run currently shown */
  query: string;
  chunks: RetrievedChunk[] | null;
  cache: { status: CacheStatus; similarity: number | null } | null;
  answer: string;
  trace: TraceData | null;
  error: QueryError | null;
  /** Live client-side stage timings (performance.now() based) */
  stages: StageTimings;
  startedAt: number | null;
}

const INITIAL: QueryStreamState = {
  phase: "idle",
  query: "",
  chunks: null,
  cache: null,
  answer: "",
  trace: null,
  error: null,
  stages: {},
  startedAt: null,
};

/**
 * Runs one query at a time against POST /api/query, exposing the SSE
 * progression as state. Stage timings are measured client-side from the
 * gaps between SSE events, which is what drives the live pipeline trace.
 */
export function useQueryStream() {
  const [state, setState] = useState<QueryStreamState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = useCallback((query: string, tier: Tier) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const t0 = performance.now();
    // Durations reported by the backend, accumulated as its events arrive.
    // These are the only source of segment widths — see lib/stageTimeline.ts.
    const measured: ServerStageMs = {};
    let timings: StageTimings = markActive({}, "embed", t0);
    let cacheHit = false;

    setState({
      ...INITIAL,
      phase: "running",
      query,
      startedAt: t0,
      stages: { ...timings },
    });

    const snapshotStages = (): StageTimings =>
      Object.fromEntries(
        Object.entries(timings).map(([k, v]) => [k, { ...v }]),
      ) as StageTimings;

    streamQuery(
      { query, tier_hint: tier, session_id: SESSION_ID },
      (event) => {
        if (controller.signal.aborted) return;
        const now = performance.now();

        switch (event.type) {
          // Event order is fixed by the backend: cache first, because it
          // decides whether retrieval runs at all.
          case "cache": {
            cacheHit = event.status !== "miss";
            measured.embed = event.embed_ms;
            measured.cache = event.cache_ms;
            timings = layoutStages(t0, measured);
            // On a hit the answer comes straight back, so nothing is in flight.
            if (!cacheHit) timings = markActive(timings, "retrieve", now);
            setState((s) => ({
              ...s,
              cache: { status: event.status, similarity: event.similarity },
              stages: snapshotStages(),
            }));
            break;
          }

          case "retrieval": {
            measured.retrieve = event.retrieve_ms;
            timings = layoutStages(t0, measured);
            if (!cacheHit) timings = markActive(timings, "generate", now);
            setState((s) => ({
              ...s,
              chunks: [...event.chunks].sort((a, b) => b.score - a.score),
              stages: snapshotStages(),
            }));
            break;
          }

          case "chunk":
            setState((s) => ({ ...s, answer: s.answer + event.text }));
            break;

          case "done": {
            // The generate segment's width is the server's own llm_ms; the
            // client clock only fills in if the trace somehow lacks it.
            const llmMs = event.trace.stages_ms?.llm_ms;
            if (!cacheHit) {
              measured.generate =
                llmMs ?? (timings.generate ? now - timings.generate.start : 0);
              timings = layoutStages(t0, measured);
            }
            addTrace({
              ts: Date.now(),
              trace: event.trace,
              client_total_ms: now - t0,
            });
            setState((s) => ({
              ...s,
              phase: "done",
              trace: event.trace,
              stages: snapshotStages(),
            }));
            break;
          }

          case "error": {
            // Close whatever was in flight so the trace stops mid-pipeline at
            // the stage that failed rather than animating forever.
            timings = Object.fromEntries(
              Object.entries(timings).map(([k, v]) => [
                k,
                v.end === null ? { ...v, end: now } : v,
              ]),
            ) as StageTimings;
            setState((s) => ({
              ...s,
              phase: "error",
              error: {
                code: event.code,
                retry_after: event.retry_after,
                message: event.message,
              },
              stages: snapshotStages(),
            }));
            break;
          }
        }
      },
      controller.signal,
    ).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      setState((s) => ({
        ...s,
        phase: "error",
        error: {
          message:
            err instanceof Error
              ? `Could not reach the server — ${err.message}`
              : "Could not reach the server.",
        },
      }));
    });
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL);
  }, []);

  return { state, run, reset };
}
