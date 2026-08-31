import { memo, useEffect, useRef } from "react";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { fmtMs } from "../lib/format";
import { INK, STAGES, WARN_COLOR } from "../lib/stages";
import type { QueryPhase, StageTimings } from "../types";

/*
 * The signature element: a horizontal signal line through four numbered
 * stage nodes (1 Embed, 2 Cache, 3 Retrieve, 4 Generate — the order the
 * backend executes them in). The signal head draws left-to-right in real
 * time, and every settled segment's width is the backend's own measurement
 * of that stage, carried on the SSE events (see lib/stageTimeline.ts).
 * While a stage is in flight the head oscillates near its node. On a cache
 * hit the signal terminates at the Cache node and Generate is marked
 * skipped. On fallback the Generate node pulses terracotta.
 */

const VIEW_W = 860;
const VIEW_H = 132;
const BASE_Y = 50;
const LEAD_X = 24;
const NODE_X = [140, 350, 560, 780];
const NODE_R = 13;
const CACHE_IDX = STAGES.findIndex((s) => s.key === "cache");

type StageStatus = "pending" | "active" | "done" | "skipped";

interface PipelineTraceProps {
  stages: StageTimings;
  phase: QueryPhase;
  cacheHit: boolean;
  fallback: boolean;
  errored: boolean;
}

function segStart(i: number): number {
  return i === 0 ? LEAD_X : NODE_X[i - 1];
}

export const PipelineTrace = memo(function PipelineTrace({
  stages,
  phase,
  cacheHit,
  fallback,
  errored,
}: PipelineTraceProps) {
  const reducedMotion = useReducedMotion();

  const statuses: StageStatus[] = STAGES.map((s) => {
    if (cacheHit && s.key === "generate") return "skipped";
    const t = stages[s.key];
    if (!t) return "pending";
    if (t.end === null) return "active";
    return "done";
  });

  const activeIdx = statuses.indexOf("active");
  // Node to mark terracotta when the stream errored.
  const errorIdx = errored
    ? STAGES.reduce((acc, s, i) => (stages[s.key] ? i : acc), 0)
    : -1;

  /* ---- live head animation (requestAnimationFrame) ------------------- */

  const stagesRef = useRef(stages);
  stagesRef.current = stages;
  const activeIdxRef = useRef(activeIdx);
  activeIdxRef.current = activeIdx;

  const headRef = useRef<SVGCircleElement | null>(null);
  const glowRef = useRef<SVGCircleElement | null>(null);
  const segRefs = useRef<(SVGLineElement | null)[]>([null, null, null, null]);
  const headXRef = useRef(LEAD_X);

  const running = phase === "running";

  useEffect(() => {
    if (!running || reducedMotion) return;
    headXRef.current = LEAD_X;
    let raf = 0;
    const tick = () => {
      const now = performance.now();
      const idx = activeIdxRef.current;
      if (idx >= 0) {
        const timing = stagesRef.current[STAGES[idx].key];
        const x1 = segStart(idx);
        const x2 = NODE_X[idx];
        if (timing) {
          const elapsed = now - timing.start;
          // Asymptotic crawl toward the node — never arrives until the
          // stage's event does, so slow stages visibly take longer.
          const progress = Math.min(0.94, 1 - Math.exp(-elapsed / 1100));
          const target = x1 + (x2 - x1) * progress;
          headXRef.current += (target - headXRef.current) * 0.16;
          const amp = 3 + Math.min(4, elapsed / 900);
          const headY = BASE_Y + Math.sin(now / 82) * amp;
          const hx = Math.max(headXRef.current, x1);

          const seg = segRefs.current[idx];
          if (seg) {
            seg.setAttribute("x2", String(hx));
            seg.setAttribute("stroke", STAGES[idx].color);
          }
          if (headRef.current) {
            headRef.current.setAttribute("cx", String(hx));
            headRef.current.setAttribute("cy", String(headY));
          }
          if (glowRef.current) {
            glowRef.current.setAttribute("cx", String(hx));
            glowRef.current.setAttribute("cy", String(headY));
            glowRef.current.setAttribute("fill", STAGES[idx].color);
          }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [running, reducedMotion]);

  /* ---- render --------------------------------------------------------- */

  const showHead = running && !reducedMotion && activeIdx >= 0;

  return (
    // `trace-ambient` paints a very low-opacity radial wash behind the line so
    // the hero element sits in a pool of light instead of on a flat field. It
    // is the only gradient in the app and is deliberately edgeless.
    <div aria-label="Pipeline trace" role="img" className="relative trace-ambient">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="relative z-10 block w-full select-none"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          {/* A real blur, replacing the flat 28%-opacity disc that stood in for
              a glow. A hard-edged translucent circle reads as a disc; only an
              actual falloff reads as light. */}
          <filter id="pt-head-glow" x="-160%" y="-160%" width="420%" height="420%">
            <feGaussianBlur stdDeviation="4.2" />
          </filter>
          {/* Nodes are the only elements that should feel like physical objects
              sitting above the line, so they get the one drop shadow in the SVG.
              Tuned to the same near-black the CSS shadow scale uses. */}
          <filter id="pt-node-shadow" x="-80%" y="-80%" width="260%" height="260%">
            <feDropShadow
              dx="0"
              dy="1.5"
              stdDeviation="2"
              floodColor="#02050C"
              floodOpacity="0.7"
            />
          </filter>
        </defs>

        {/* baseline */}
        <line
          x1={LEAD_X}
          y1={BASE_Y}
          x2={VIEW_W - 24}
          y2={BASE_Y}
          stroke={INK[700]}
          strokeWidth={1}
        />

        {/* stage segments */}
        {STAGES.map((s, i) => {
          const status = statuses[i];
          if (status === "pending" || status === "skipped") return null;
          const x1 = segStart(i);
          const isDone = status === "done";
          // Active segment: rAF drives x2 (reduced motion draws it faintly full).
          const x2 = isDone
            ? NODE_X[i]
            : reducedMotion
              ? NODE_X[i]
              : Math.max(headXRef.current, x1);
          return (
            <line
              key={s.key}
              ref={(el) => {
                segRefs.current[i] = el;
              }}
              x1={x1}
              y1={BASE_Y}
              x2={x2}
              y2={BASE_Y}
              stroke={s.color}
              // Thicker and fully opaque when settled: the segment is the
              // measurement, so it should be the boldest line on screen.
              strokeWidth={isDone ? 2.5 : 2}
              strokeLinecap="round"
              opacity={isDone ? 1 : 0.5}
            />
          );
        })}

        {/* Terminal tick over the cache node: on a hit, this is where the answer
            came from. Derived from STAGES rather than a literal index so it
            follows the node if the pipeline order changes again. */}
        {cacheHit && CACHE_IDX >= 0 && (
          <line
            x1={NODE_X[CACHE_IDX]}
            y1={BASE_Y - 26}
            x2={NODE_X[CACHE_IDX]}
            y2={BASE_Y - NODE_R - 3}
            stroke={STAGES[CACHE_IDX].color}
            strokeWidth={2}
            strokeLinecap="round"
          />
        )}

        {/* nodes */}
        {STAGES.map((s, i) => {
          const status = statuses[i];
          const isError = i === errorIdx;
          const isFallbackNode = fallback && s.key === "generate";
          const ringColor = isError || isFallbackNode ? WARN_COLOR : s.color;
          const stroke = isError
            ? WARN_COLOR
            : status === "pending" || status === "skipped"
              ? INK[700]
              : s.color;
          const filled = status === "done" && !isError;
          const t = stages[s.key];
          const durMs = t && t.end !== null ? t.end - t.start : null;

          return (
            <g key={s.key} opacity={status === "skipped" ? 0.45 : 1}>
              {(status === "active" || isFallbackNode || isError) && (
                <circle
                  cx={NODE_X[i]}
                  cy={BASE_Y}
                  r={NODE_R}
                  fill="none"
                  stroke={ringColor}
                  strokeWidth={1.5}
                  className={
                    reducedMotion
                      ? undefined
                      : isFallbackNode || isError
                        ? "warn-pulse"
                        : "node-pulse-ring"
                  }
                />
              )}
              {/* Completed stages keep a faint halo in their own hue. Without
                  it a finished node is just a flat coloured dot; the halo is
                  what makes the four stages read as still-lit checkpoints
                  rather than as a legend. Filled nodes only — a pending node
                  glowing would claim work that hasn't happened. */}
              {filled && (
                <circle
                  cx={NODE_X[i]}
                  cy={BASE_Y}
                  r={NODE_R + 2}
                  fill={s.color}
                  // 0.3 -> 0.5: with saturated hues a completed node should
                  // read as genuinely lit, which is what makes the finished
                  // trace look like an instrument rather than a legend.
                  opacity={0.5}
                  filter="url(#pt-head-glow)"
                />
              )}
              <circle
                cx={NODE_X[i]}
                cy={BASE_Y}
                r={NODE_R}
                fill={filled ? s.color : INK[900]}
                stroke={stroke}
                strokeWidth={1.5}
                strokeDasharray={status === "skipped" ? "3 3" : undefined}
                filter="url(#pt-node-shadow)"
              />
              <text
                x={NODE_X[i]}
                y={BASE_Y + 4}
                textAnchor="middle"
                className="font-mono"
                fontSize={11}
                fill={filled ? INK[950] : status === "pending" || status === "skipped" ? INK[300] : s.color}
              >
                {s.num}
              </text>
              <text
                x={NODE_X[i]}
                y={BASE_Y + 40}
                textAnchor="middle"
                className="font-display"
                fontSize={13}
                letterSpacing="0.06em"
                fill={status === "pending" || status === "skipped" ? INK[300] : INK[100]}
              >
                {s.label}
              </text>
              {durMs !== null && !isError && (
                <text
                  x={NODE_X[i]}
                  y={BASE_Y + 58}
                  textAnchor="middle"
                  className="font-mono"
                  fontSize={10}
                  fill={INK[300]}
                >
                  {fmtMs(durMs)}
                </text>
              )}
              {status === "skipped" && (
                <text
                  x={NODE_X[i]}
                  y={BASE_Y + 58}
                  textAnchor="middle"
                  className="font-mono"
                  fontSize={10}
                  fill={INK[300]}
                >
                  skipped
                </text>
              )}
            </g>
          );
        })}

        {/* signal head with glow */}
        {showHead && (
          <g>
            <circle
              ref={glowRef}
              cx={LEAD_X}
              cy={BASE_Y}
              r={7}
              opacity={0.55}
              filter="url(#pt-head-glow)"
            />
            <circle ref={headRef} cx={LEAD_X} cy={BASE_Y} r={4.5} fill={INK[100]} />
          </g>
        )}
      </svg>
    </div>
  );
});
