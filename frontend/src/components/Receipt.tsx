import { motion } from "framer-motion";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { fmtCost, fmtMs } from "../lib/format";
import { labelForMsKey, stageForMsKey, STAGE_COLOR, WARN_COLOR } from "../lib/stages";
import type { StageTimings, TraceData } from "../types";

interface ReceiptProps {
  trace: TraceData;
  /** Client-measured timings, used when the backend trace has no stages_ms
      (e.g. cache hits terminate before generation). */
  clientStages: StageTimings;
}

interface WaterfallSegment {
  label: string;
  ms: number;
  color: string;
}

function buildSegments(trace: TraceData, clientStages: StageTimings): WaterfallSegment[] {
  const stagesMs = trace.stages_ms ?? {};
  const entries = Object.entries(stagesMs).filter(([, v]) => v > 0);
  if (entries.length > 0) {
    return entries.map(([key, ms]) => {
      const stage = stageForMsKey(key);
      return {
        label: labelForMsKey(key),
        ms,
        color: stage ? STAGE_COLOR[stage] : "#8B99B8",
      };
    });
  }
  // Fallback: client-observed gaps between SSE events.
  const out: WaterfallSegment[] = [];
  const retrieve = clientStages.retrieve;
  const embed = clientStages.embed;
  if (embed && retrieve && retrieve.end !== null) {
    out.push({
      label: "Retrieval",
      ms: retrieve.end - embed.start,
      color: STAGE_COLOR.retrieve,
    });
  }
  const cache = clientStages.cache;
  if (cache && cache.end !== null) {
    out.push({ label: "Cache", ms: cache.end - cache.start, color: STAGE_COLOR.cache });
  }
  const gen = clientStages.generate;
  if (gen && gen.end !== null) {
    out.push({ label: "Generate", ms: gen.end - gen.start, color: STAGE_COLOR.generate });
  }
  return out;
}

export function Receipt({ trace, clientStages }: ReceiptProps) {
  const reducedMotion = useReducedMotion();
  const segments = buildSegments(trace, clientStages);
  const total = segments.reduce((acc, s) => acc + s.ms, 0);
  const cacheHit = trace.cache_status !== "miss";

  return (
    // The receipt is the settled summary of a finished query, so it sits at the
    // top of the depth scale — it should feel like a card handed back to you,
    // above the panels that produced it.
    <motion.div
      initial={reducedMotion ? false : { opacity: 0, y: 8, rotateX: -5 }}
      animate={{ opacity: 1, y: 0, rotateX: 0 }}
      transition={reducedMotion ? { duration: 0 } : { duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-md border border-ink-700 bg-ink-900 px-4 py-3 shadow-raised surface-edge"
    >
      <div className="mb-2 flex items-baseline justify-between">
        <span className="label-caps">Receipt</span>
        <span className="font-mono text-[11px] text-ink-300">
          {trace.request_id.slice(0, 8)}
        </span>
      </div>

      {/* latency waterfall */}
      {segments.length > 0 && total > 0 && (
        <>
          {/* Recessed channel, same treatment as the chunk similarity bars, so
              every "proportion of a whole" bar in the app reads identically. */}
          <div className="flex h-2.5 w-full overflow-hidden rounded-sm bg-ink-950/70 shadow-[inset_0_1px_2px_rgba(3,7,18,0.65)]">
            {segments.map((seg, i) => (
              <motion.div
                key={seg.label}
                title={`${seg.label} ${fmtMs(seg.ms)}`}
                initial={reducedMotion ? false : { width: 0 }}
                animate={{ width: `${Math.max(1.5, (seg.ms / total) * 100)}%` }}
                transition={
                  reducedMotion
                    ? { duration: 0 }
                    : { duration: 0.5, delay: 0.08 + i * 0.06, ease: [0.16, 1, 0.3, 1] }
                }
                style={{
                  backgroundColor: seg.color,
                  // 1px dark rule between adjacent segments. Two stage hues
                  // meeting flush blur into one band at this height; the gap is
                  // what keeps the proportions legible.
                  boxShadow: i > 0 ? "inset 1px 0 0 rgba(11,17,32,0.85)" : undefined,
                }}
              />
            ))}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
            {segments.map((seg) => (
              <span key={seg.label} className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block h-2 w-2 rounded-[2px]"
                  style={{ backgroundColor: seg.color }}
                />
                <span className="text-[11px] text-ink-300">{seg.label}</span>
                <span className="font-mono text-[11px] text-ink-100">
                  {fmtMs(seg.ms)}
                </span>
              </span>
            ))}
            <span className="ml-auto inline-flex items-center gap-1.5">
              <span className="text-[11px] text-ink-300">total</span>
              <span className="font-mono text-[11px] text-ink-100">{fmtMs(total)}</span>
            </span>
          </div>
        </>
      )}

      {/* figures */}
      <div className="mt-3 flex flex-wrap items-baseline gap-x-7 gap-y-2.5 border-t border-ink-700 pt-3">
        <Figure label="model" value={cacheHit ? "cache" : trace.model_used || "—"} />
        <Figure
          label="tokens in / out"
          value={
            cacheHit
              ? "0 / 0"
              : `${trace.tokens_in ?? "—"} / ${trace.tokens_out ?? "—"}`
          }
        />
        <Figure label="cost" value={cacheHit ? "$0.0000" : fmtCost(trace.cost_usd)} />
      </div>

      {trace.fallback_triggered && (
        // Degradation is the thing this project refuses to hide, so it gets a
        // terracotta rule and a tinted field rather than a line of coloured
        // text that scans as a footnote.
        <p
          className="mt-3 rounded-sm border-l-2 px-2.5 py-1.5 text-xs"
          style={{
            color: WARN_COLOR,
            borderColor: WARN_COLOR,
            backgroundColor: `${WARN_COLOR}12`,
          }}
        >
          Primary model unavailable — served by{" "}
          <span className="font-mono font-medium">
            {trace.model_used || "fallback model"}
          </span>
          .
        </p>
      )}
    </motion.div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    // Stacked rather than inline: the label was competing with the value at the
    // same optical weight. Dropping the label to a caption above lets the
    // measurement carry the row.
    <span className="inline-flex flex-col gap-0.5">
      <span className="label-caps text-[10px]">{label}</span>
      <span className="font-mono text-[15px] font-medium tabular-nums leading-none text-ink-100">
        {value}
      </span>
    </span>
  );
}
