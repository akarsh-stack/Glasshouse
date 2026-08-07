import { useEffect, useRef, useState } from "react";
import { fetchMetrics } from "../lib/api";
import type { MetricsData } from "../types";

export type MetricsWindow = "1h" | "24h" | "7d";

/**
 * Polls GET /api/metrics. `intervalMs` can be lowered (e.g. during a load
 * test) to make the readouts update faster.
 */
export function useMetrics(window_: MetricsWindow, intervalMs: number, active: boolean) {
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Reset to loading state when the window changes.
  const lastWindow = useRef(window_);
  if (lastWindow.current !== window_) {
    lastWindow.current = window_;
    setMetrics(null);
  }

  useEffect(() => {
    if (!active) return;
    let alive = true;
    const load = async () => {
      try {
        const data = await fetchMetrics(window_);
        if (!alive) return;
        setMetrics(data);
        setError(null);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Failed to load metrics");
      }
    };
    void load();
    const id = window.setInterval(() => void load(), intervalMs);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [window_, intervalMs, active]);

  return { metrics, error };
}
