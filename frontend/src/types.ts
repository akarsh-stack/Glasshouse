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
  | { type: "retrieval"; chunks: RetrievedChunk[] }
  | { type: "cache"; status: CacheStatus; similarity: number | null }
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

export interface MetricsData {
  window: string;
  /** Arrivals, including requests the limiter shed. */
  total_requests: number;
  /** Admitted requests. The denominator for every rate below. */
  served_requests?: number;
  req_per_sec?: number;
  cache_hit_rate?: number;
  error_rate?: number;
  /** Counted separately from error_rate: a 429 means the limiter did its job. */
  rate_limited_count?: number;
  latency_p50_ms?: number;
  latency_p95_ms?: number;
  latency_p99_ms?: number;
  total_cost_usd?: number;
  model_breakdown?: Record<string, number>;
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
