import { useEffect, useRef, useState } from "react";
import { Glasshouse3D } from "./Glasshouse3D";
import { STAGE_COLOR, WARN_COLOR } from "../lib/stages";

/*
 * Holds the app back until the backend answers.
 *
 * This exists because of a real defect, not to have somewhere to put a
 * loading screen: with the backend down the UI rendered perfectly and then
 * every request failed one at a time — an empty document rail, a query that
 * errored, metrics that never arrived. Three separate confusing failures
 * instead of one clear "the backend isn't up yet".
 *
 * It is also a genuine wait. First backend boot downloads the ~80 MB ONNX
 * embedding model, and a cold start on a free host takes seconds.
 *
 * The gate never blocks forever: after `HINT_AFTER_MS` it shows the command to
 * start the backend, and offers a way through so the frontend can still be
 * inspected offline.
 */

const POLL_MS = 900;
const HINT_AFTER_MS = 6000;

type Phase = "checking" | "ready" | "unreachable";

interface Health {
  status: string;
  redis?: string;
  embeddings?: string;
  chunker?: string;
}

export function BootGate({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [skipped, setSkipped] = useState(false);
  const startedAt = useRef(Date.now());

  useEffect(() => {
    if (phase === "ready") return;
    let alive = true;

    const check = async () => {
      try {
        const res = await fetch("/api/health");
        if (!alive) return;
        if (res.ok) {
          // Parsed rather than trusting the status alone: a dev-server proxy
          // returning its own HTML error page still answers 200.
          const body = (await res.json()) as Health;
          if (body.status !== "ok") throw new Error(body.status);
          setPhase("ready");
          return;
        }
        throw new Error(String(res.status));
      } catch {
        if (!alive) return;
        setPhase(
          Date.now() - startedAt.current > HINT_AFTER_MS ? "unreachable" : "checking",
        );
      }
    };

    void check();
    const id = window.setInterval(() => void check(), POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [phase]);

  if (phase === "ready" || skipped) return <>{children}</>;

  const unreachable = phase === "unreachable";

  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-7 px-6">
      <Glasshouse3D size={208} />

      <div className="flex flex-col items-center gap-3 text-center">
        <p className="font-display text-title text-ink-100">Glasshouse</p>

        <p
          className="flex items-center gap-2 font-mono text-label"
          style={{ color: unreachable ? WARN_COLOR : STAGE_COLOR.generate }}
          role="status"
          aria-live="polite"
        >
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{
              backgroundColor: unreachable ? WARN_COLOR : STAGE_COLOR.generate,
              boxShadow: `0 0 6px ${unreachable ? WARN_COLOR : STAGE_COLOR.generate}`,
            }}
          />
          {unreachable ? "backend unreachable" : "waiting for backend"}
        </p>

        {unreachable && (
          <div className="mt-1 flex max-w-measure flex-col items-center gap-3">
            <p className="text-ui text-ink-300">
              Nothing is answering on <code className="font-mono">/api/health</code>. First
              start also downloads the embedding model, which takes a minute.
            </p>
            <pre className="w-full overflow-x-auto rounded-md border border-ink-700 bg-ink-900 px-3.5 py-2.5 text-left font-mono text-meta text-ink-100 shadow-panel surface-edge">
              cd backend &amp;&amp; uvicorn app.main:app
            </pre>
            <button
              type="button"
              onClick={() => setSkipped(true)}
              className="font-mono text-label text-ink-300 underline underline-offset-4 transition-colors duration-120 hover:text-ink-100"
            >
              continue without a backend
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/** Exported for tests: the status text for a given phase. */
export function bootStatusLabel(phase: Phase): string {
  return phase === "unreachable" ? "backend unreachable" : "waiting for backend";
}

export type { Health, Phase };
