import type { TraceData } from "../types";

/**
 * Client-side rolling log of recent query traces. Every completed query
 * (playground or load test) records its "done" trace here so the ops
 * dashboard can chart per-stage latency of recent queries.
 */
export interface TraceLogEntry {
  /** Date.now() when the trace completed */
  ts: number;
  trace: TraceData;
  /** Client-measured cache-stage duration (backend does not report it) */
  client_cache_ms?: number;
  /** Client-measured total wall time */
  client_total_ms?: number;
}

const MAX_ENTRIES = 40;

let entries: TraceLogEntry[] = [];
const listeners = new Set<() => void>();

export function addTrace(entry: TraceLogEntry): void {
  entries = [...entries, entry].slice(-MAX_ENTRIES);
  listeners.forEach((fn) => fn());
}

export function getTraces(): TraceLogEntry[] {
  return entries;
}

export function subscribeTraces(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
