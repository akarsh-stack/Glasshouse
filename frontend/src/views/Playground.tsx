import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Answer } from "../components/Answer";
import { CacheBadge } from "../components/CacheBadge";
import { ChunkCards } from "../components/ChunkCards";
import { DocumentRail } from "../components/DocumentRail";
import { PipelineTrace } from "../components/PipelineTrace";
import { Receipt } from "../components/Receipt";
import { Skeleton } from "../components/ui";
import { useDocuments } from "../hooks/useDocuments";
import { useQueryStream } from "../hooks/useQueryStream";
import { WARN_COLOR } from "../lib/stages";
import type { Tier } from "../types";

interface PlaygroundProps {
  tier: Tier;
  railOpen: boolean;
}

export function Playground({ tier, railOpen }: PlaygroundProps) {
  const docs = useDocuments();
  const { state, run } = useQueryStream();
  const [input, setInput] = useState("");

  // Refresh doc list after a completed query (chunk counts can change while
  // ingestion finishes in the background).
  const phase = state.phase;
  useEffect(() => {
    if (phase === "done") void docs.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = input.trim();
    if (!q || state.phase === "running") return;
    run(q, tier);
  };

  const cacheHit = state.cache !== null && state.cache.status !== "miss";
  const hasRun = state.phase !== "idle";
  const noDocuments = docs.documents !== null && docs.documents.length === 0;

  return (
    <div className="flex min-h-0 flex-1">
      {/* left rail */}
      <aside
        className={`shrink-0 overflow-hidden border-r border-ink-700 bg-ink-900 transition-[width] duration-200 ${
          railOpen ? "w-64" : "w-0 border-r-0"
        }`}
        aria-label="Documents"
        aria-hidden={!railOpen}
      >
        <div className="h-full w-64 p-3">
          <DocumentRail
            documents={docs.documents}
            error={docs.error}
            uploads={docs.uploads}
            onUpload={(files) => void docs.upload(files)}
            onDelete={(id) => void docs.remove(id)}
          />
        </div>
      </aside>

      {/* center + right */}
      <div className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-4 lg:flex-row lg:gap-0 lg:p-0">
        {/* center column */}
        <main className="min-w-0 flex-1 lg:overflow-y-auto lg:p-5">
          <form onSubmit={submit}>
            <label htmlFor="query-input" className="sr-only">
              Ask a question about your documents
            </label>
            <input
              id="query-input"
              type="text"
              autoComplete="off"
              placeholder="Ask a question about your documents"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={state.phase === "running"}
              className="w-full rounded-md border border-ink-700 bg-ink-900 px-4 py-3 font-body text-[15px] text-ink-100 placeholder:text-ink-300/70 shadow-panel surface-edge transition-[box-shadow,border-color] duration-120 focus:outline-none focus:border-ink-300/30 focus:shadow-raised disabled:opacity-60"
            />
          </form>

          {noDocuments && !hasRun && (
            <p className="mt-3 text-sm leading-relaxed text-ink-300">
              No documents uploaded yet — add some on the left to ground
              answers in your own material. You can still ask a question
              without context.
            </p>
          )}

          {/* signature element: the pipeline trace */}
          <div className="mt-5 rounded-md border border-ink-700 bg-ink-900 px-3 pb-1 pt-3 shadow-panel surface-edge">
            <div className="mb-1 flex items-baseline justify-between px-1">
              <span className="label-caps">Pipeline trace</span>
              {hasRun && (
                <span className="min-w-0 truncate pl-4 font-mono text-[11px] text-ink-300">
                  {state.query}
                </span>
              )}
            </div>
            <PipelineTrace
              stages={state.stages}
              phase={state.phase}
              cacheHit={cacheHit}
              fallback={Boolean(state.trace?.fallback_triggered)}
              errored={state.phase === "error"}
            />
          </div>

          {/* error states */}
          {state.error && (
            <div
              className="mt-4 rounded-md border px-4 py-3 text-sm shadow-panel"
              style={{ borderColor: `${WARN_COLOR}66`, color: WARN_COLOR }}
              role="alert"
            >
              {state.error.code === 429
                ? `You're sending queries too quickly — try again in ${Math.max(
                    1,
                    Math.ceil(state.error.retry_after ?? 1),
                  )}s.`
                : state.error.message ||
                  "Something went wrong while answering. Try the question again."}
            </div>
          )}

          {/* streaming answer */}
          {(state.answer || state.phase === "running") && !state.error && (
            <div className="mt-4">
              <p className="label-caps mb-2">Answer</p>
              {state.answer ? (
                <Answer
                  text={state.answer}
                  streaming={state.phase === "running"}
                  citationCount={state.chunks?.length ?? 0}
                />
              ) : (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-11/12" />
                  <Skeleton className="h-4 w-3/5" />
                </div>
              )}
            </div>
          )}

          {/* receipt strip */}
          {state.trace && state.phase === "done" && (
            <div className="mt-4">
              <Receipt trace={state.trace} clientStages={state.stages} />
            </div>
          )}
        </main>

        {/* right panel */}
        <aside
          className="w-full shrink-0 border-ink-700 lg:w-80 lg:overflow-y-auto lg:border-l lg:p-4"
          aria-label="Retrieval details"
        >
          {!hasRun ? (
            <div className="pt-1">
              <p className="label-caps mb-2">Retrieved context</p>
              <p className="text-xs leading-relaxed text-ink-300">
                Ask a question and the passages used to answer it will appear
                here, ranked by similarity.
              </p>
            </div>
          ) : (
            <div className="space-y-3 pt-1">
              {state.cache && (
                <CacheBadge
                  status={state.cache.status}
                  similarity={state.cache.similarity}
                  model={state.trace?.model_used}
                />
              )}
              <p className="label-caps">Retrieved context</p>
              {state.chunks === null ? (
                <div className="space-y-2">
                  <Skeleton className="h-24 w-full" />
                  <Skeleton className="h-24 w-full" />
                  <Skeleton className="h-24 w-full" />
                </div>
              ) : (
                <ChunkCards chunks={state.chunks} documents={docs.documents} />
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
