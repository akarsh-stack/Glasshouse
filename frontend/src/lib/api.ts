import type { DocumentInfo, MetricsData, SSEEvent, Tier } from "../types";

/** Stable per-browser-session id used for rate limiting on the backend. */
export const SESSION_ID: string =
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `s-${Math.random().toString(36).slice(2)}`;

export interface QueryBody {
  query: string;
  tier_hint?: Tier;
  session_id?: string;
}

/**
 * POST /api/query and stream the SSE response.
 * EventSource cannot POST, so we read the body with a ReadableStream reader
 * and parse `data: {...}\n\n` frames by hand.
 */
export async function streamQuery(
  body: QueryBody,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    let message = `Request failed (${res.status})`;
    // The rate limiter rejects with a real 429 before the stream opens, so this
    // is a normal response body rather than an SSE frame. FastAPI's `detail` is
    // a string for most errors but an object for 429 (it carries the precise
    // sub-second retry delay, which the Retry-After header can't express).
    let retryAfter: number | undefined;
    const header = res.headers.get("Retry-After");
    if (header) {
      const parsedHeader = Number(header);
      if (Number.isFinite(parsedHeader)) retryAfter = parsedHeader;
    }
    try {
      const text = await res.text();
      if (text) {
        const parsed = JSON.parse(text) as {
          detail?: string | { message?: string; retry_after?: number };
        };
        const detail = parsed.detail;
        if (typeof detail === "string") {
          message = detail;
        } else if (detail && typeof detail === "object") {
          if (detail.message) message = detail.message;
          // Body value wins: it's exact, the header is rounded up to whole seconds.
          if (typeof detail.retry_after === "number") retryAfter = detail.retry_after;
        }
      }
    } catch {
      /* keep default message */
    }
    onEvent({ type: "error", code: res.status, message, retry_after: retryAfter });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const emitFrame = (frame: string) => {
    // A frame may contain several lines; SSE data lines start with "data:".
    for (const line of frame.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const payload = trimmed.slice(5).trim();
      if (!payload) continue;
      try {
        onEvent(JSON.parse(payload) as SSEEvent);
      } catch {
        // Malformed frame — skip rather than break the stream.
      }
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      emitFrame(frame);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) emitFrame(buffer);
}

export async function fetchDocuments(signal?: AbortSignal): Promise<DocumentInfo[]> {
  const res = await fetch("/api/documents", { signal });
  if (!res.ok) throw new Error(`Failed to load documents (${res.status})`);
  return (await res.json()) as DocumentInfo[];
}

export async function uploadDocument(file: File): Promise<DocumentInfo> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/documents", { method: "POST", body: form });
  if (!res.ok) {
    let message = `Upload failed (${res.status})`;
    try {
      const parsed = (await res.json()) as { detail?: string };
      if (parsed.detail) message = parsed.detail;
    } catch {
      /* keep default */
    }
    throw new Error(message);
  }
  return (await res.json()) as DocumentInfo;
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(`/api/documents/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Delete failed (${res.status})`);
}

export async function fetchMetrics(
  window: string,
  signal?: AbortSignal,
): Promise<MetricsData> {
  const res = await fetch(`/api/metrics?window=${encodeURIComponent(window)}`, {
    signal,
  });
  if (!res.ok) throw new Error(`Failed to load metrics (${res.status})`);
  return (await res.json()) as MetricsData;
}
