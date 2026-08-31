export type Tier = "fast" | "quality" | "deep";

export interface RetrievedChunk {
  chunk_id: string;
  score: number;
  text: string;
  document_id: string;
  chunk_index: number;
  page_number: number | null;
}

export type CacheStatus = "miss" | "hit_exact" | "hit_semantic";

export interface TraceData {
  request_id: string;
  cache_status: string;
  model_used?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number;
  fallback_triggered?: boolean;
  stages_ms?: Record<string, number>;
}

export type SSEEvent =
  /** `retrieve_ms` is 0 and `from_cache` true when chunks came back with a cached answer. */
  | {
      type: "retrieval";
      chunks: RetrievedChunk[];
      retrieve_ms: number;
      from_cache: boolean;
    }
  /** Carries the two stages that ran before it, both measured server-side. */
  | {
      type: "cache";
      status: CacheStatus;
      similarity: number | null;
      embed_ms: number;
      cache_ms: number;
    }
  | { type: "chunk"; text: string }
  | { type: "done"; trace: TraceData }
  | { type: "error"; code?: number; retry_after?: number; message?: string };

export interface DocumentInfo {
  id: string;
  filename: string;
  uploaded_at: string;
  status: string;
  chunk_count: number;
  content_hash: string;
}

/**
 * Every field is always present — an empty window returns the same keys zeroed.
 * These were optional because the backend used to return two keys when there
 * was no traffic and twelve when there was.
 */
export interface MetricsData {
  window: string;
  /** Arrivals, including requests the limiter shed. */
  total_requests: number;
  /** Admitted requests. The denominator for every rate below. */
  served_requests: number;
  /** Seconds between the first and last request in the window. */
  observed_span_sec: number;
  /** Over `observed_span_sec`, not the window length — a 30s burst is not an hour of traffic. */
  req_per_sec: number;
  cache_hit_rate: number;
  error_rate: number;
  /** Counted separately from error_rate: a 429 means the limiter did its job. */
  rate_limited_count: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  latency_p99_ms: number;
  total_cost_usd: number;
  model_breakdown: Record<string, number>;
}

export type StageKey = "embed" | "retrieve" | "cache" | "generate";

export interface StageTiming {
  /** performance.now() when the stage started */
  start: number;
  /** performance.now() when the stage finished, null while in flight */
  end: number | null;
}

export type StageTimings = Partial<Record<StageKey, StageTiming>>;

export type QueryPhase = "idle" | "running" | "done" | "error";

export interface QueryError {
  code?: number;
  retry_after?: number;
  message?: string;
}
