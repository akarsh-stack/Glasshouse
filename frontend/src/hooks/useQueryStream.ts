import { useCallback, useEffect, useRef, useState } from "react";
import { SESSION_ID, streamQuery } from "../lib/api";
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
    // Timings we mutate locally, mirrored into state on each event.
    const timings: StageTimings = { embed: { start: t0, end: null } };
    let cacheHit = false;
    let cacheEventAt: number | null = null;
    let retrievalEventAt: number | null = null;

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
          case "retrieval": {
            retrievalEventAt = now;
            // The backend emits a single event covering embed + retrieve.
            // Split the measured span so both nodes light in sequence.
            const embedEnd = t0 + (now - t0) * 0.35;
            timings.embed = { start: t0, end: embedEnd };
            timings.retrieve = { start: embedEnd, end: now };
            timings.cache = { start: now, end: null };
            setState((s) => ({
              ...s,
              chunks: [...event.chunks].sort((a, b) => b.score - a.score),
              stages: snapshotStages(),
            }));
            break;
          }

          case "cache": {
            cacheEventAt = now;
            cacheHit = event.status !== "miss";
            if (timings.cache) timings.cache.end = now;
            else timings.cache = { start: retrievalEventAt ?? t0, end: now };
            if (!cacheHit) timings.generate = { start: now, end: null };
            setState((s) => ({
              ...s,
              cache: { status: event.status, similarity: event.similarity },
              stages: snapshotStages(),
            }));
            break;
          }

          case "chunk":
            setState((s) => ({ ...s, answer: s.answer + event.text }));
            break;

          case "done": {
            if (timings.generate && timings.generate.end === null) {
              timings.generate.end = now;
            }
            const cacheMs =
              cacheEventAt !== null && retrievalEventAt !== null
                ? cacheEventAt - retrievalEventAt
                : undefined;
            addTrace({
              ts: Date.now(),
              trace: event.trace,
              client_cache_ms: cacheMs,
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
            for (const key of Object.keys(timings) as (keyof StageTimings)[]) {
              const t = timings[key];
              if (t && t.end === null) t.end = now;
            }
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
