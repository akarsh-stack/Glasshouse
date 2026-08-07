import { useCallback, useRef, useState } from "react";
import { streamQuery } from "../lib/api";
import { addTrace } from "../lib/traceStore";

const SAMPLE_QUERIES = [
  "Summarize the key points of the uploaded documents.",
  "What are the main risks discussed?",
  "List the most important dates mentioned.",
  "Who are the people or organizations referenced?",
  "What conclusions do the documents reach?",
  "Explain the methodology described in the material.",
  "What open questions remain unanswered?",
  "Give a one-paragraph executive summary.",
  "What financial figures appear in the documents?",
  "Compare the different approaches described.",
  "What recommendations are made?",
  "Describe the timeline of events covered.",
  "What terminology is defined in the documents?",
  "What are the strongest arguments presented?",
  "Which sections discuss future plans?",
];

export interface LoadTestState {
  running: boolean;
  completed: number;
  total: number;
}

/** Fires 15 concurrent queries at POST /api/query, recording each finished
    trace in the client-side rolling log. */
export function useLoadTest() {
  const [state, setState] = useState<LoadTestState>({
    running: false,
    completed: 0,
    total: SAMPLE_QUERIES.length,
  });
  const runningRef = useRef(false);

  const start = useCallback(() => {
    if (runningRef.current) return;
    runningRef.current = true;
    setState({ running: true, completed: 0, total: SAMPLE_QUERIES.length });

    const runId = Date.now().toString(36);
    const jobs = SAMPLE_QUERIES.map((query, i) =>
      streamQuery(
        {
          query,
          tier_hint: i % 3 === 0 ? "fast" : "quality",
          // One bucket for the whole run, not one per request. A unique
          // session_id per request would give each its own fresh token bucket
          // and quietly route the load test around the rate limiter — the one
          // component a load test should be exercising. The burst still fits
          // inside the 100-token capacity, so all 15 are admitted.
          session_id: `loadtest-${runId}`,
        },
        (event) => {
          if (event.type === "done") {
            addTrace({ ts: Date.now(), trace: event.trace });
          }
        },
      )
        .catch(() => {
          /* individual failures still count as settled */
        })
        .finally(() => {
          setState((s) => ({ ...s, completed: s.completed + 1 }));
        }),
    );

    void Promise.allSettled(jobs).then(() => {
      runningRef.current = false;
      setState((s) => ({ ...s, running: false }));
    });
  }, []);

  return { ...state, start };
}
