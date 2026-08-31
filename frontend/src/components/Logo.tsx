import { memo } from "react";
import { motion } from "framer-motion";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { INK, STAGES } from "../lib/stages";

/*
 * The mark: one signal enters glass and leaves as four.
 *
 * That is the product stated as a shape — a query goes in, and what comes out
 * is a *measured four-stage pipeline you can see*. The exit beams are the four
 * stage hues in pipeline order (embed, cache, retrieve, generate), so the logo
 * and the trace share one colour language: seeing amber in the mark and amber
 * on node 2 is the same fact twice.
 *
 * The previous favicon was a stock violet gradient (#863bff) with no
 * relationship to the ink-navy palette or to anything the app does.
 *
 * Built from the existing tokens only. No new colour enters the system here.
 */

/*
 * Geometry: beams radiate from a single point at ±28° and ±9.5°, all the same
 * length, so the fan has even optical weight rather than bunching. Endpoints
 * are precomputed rather than rotated in CSS so the shape is identical at every
 * size and in the static favicon.
 *
 * The containing box was dropped after looking at it: at 24px the border
 * competed with the beams and the fan overflowed its own corners. The glass is
 * now a single edge-on plane at the split point, which is how you'd actually
 * draw a prism cross-section — and it leaves the beams as the only detail the
 * eye has to resolve.
 */
const ORIGIN = { x: 12.5, y: 16 };
const BEAM_LEN = 16.4;
const INCOMING_LEN = ORIGIN.x - 1.6;
const BEAMS = [-28, -9.5, 9.5, 28].map((deg) => {
  const rad = (deg * Math.PI) / 180;
  return {
    x: ORIGIN.x + Math.cos(rad) * BEAM_LEN,
    y: ORIGIN.y + Math.sin(rad) * BEAM_LEN,
  };
});

/*
 * Draw-on animation via explicit dash geometry rather than framer-motion's
 * `pathLength`.
 *
 * `pathLength` emits `stroke-dasharray: 1px 1px` alongside `pathLength="1"`.
 * The px unit defeats the normalisation, so the browser renders a literal
 * 1px-on/1px-off dotted line — over a 12px beam at header size that is a few
 * specks, and the mark rendered as a bare "-|". Every length here is known
 * exactly, so the dash values can be too.
 */
function drawIn(length: number, delay: number, enabled: boolean) {
  if (!enabled) return {};
  return {
    initial: { strokeDasharray: `${length} ${length}`, strokeDashoffset: length },
    animate: { strokeDashoffset: 0 },
    transition: { duration: 0.36, delay, ease: [0.16, 1, 0.3, 1] as const },
  };
}

interface LogoProps {
  size?: number;
  /** Animate the beams on mount. Off for the favicon-like static contexts. */
  animate?: boolean;
  className?: string;
}

export const Logo = memo(function Logo({
  size = 26,
  animate = true,
  className,
}: LogoProps) {
  const reducedMotion = useReducedMotion();
  const shouldAnimate = animate && !reducedMotion;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label="Glasshouse"
      className={className}
    >
      {/* The glass, seen edge-on: a single plane the signal passes through. */}
      <path
        d={`M${ORIGIN.x} 5.5V26.5`}
        stroke={INK[100]}
        strokeOpacity="0.22"
        strokeWidth="2"
        strokeLinecap="round"
      />

      {/* Incoming signal — one line, neutral, before the pipeline touches it. */}
      <motion.path
        d={`M1.6 16H${ORIGIN.x}`}
        stroke={INK[100]}
        strokeWidth="2.4"
        strokeLinecap="round"
        {...drawIn(INCOMING_LEN, 0, shouldAnimate)}
      />

      {/* Exit beams, one per stage, in pipeline order top to bottom. Staggered
          40ms apart — the same rhythm the chunk cards and readout row use. */}
      {STAGES.map((stage, i) => (
        <motion.path
          key={stage.key}
          d={`M${ORIGIN.x} ${ORIGIN.y}L${BEAMS[i].x.toFixed(2)} ${BEAMS[i].y.toFixed(2)}`}
          stroke={stage.color}
          strokeWidth="2.4"
          strokeLinecap="round"
          {...drawIn(BEAM_LEN, 0.26 + i * 0.04, shouldAnimate)}
        />
      ))}
    </svg>
  );
});

/**
 * Header lockup: mark plus wordmark plus the standing tagline.
 *
 * The tagline is set in mono at the same size as every other measurement label
 * in the app, because it *is* a label rather than marketing copy.
 */
export function Wordmark({ className }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className ?? ""}`}>
      <Logo size={24} />
      <div className="flex items-baseline gap-2.5">
        <span className="font-display text-title font-semibold leading-none text-ink-100">
          Glasshouse
        </span>
        <span className="hidden font-mono text-label uppercase leading-none tracking-[0.18em] text-ink-300 sm:inline">
          rag pipeline, visible
        </span>
      </div>
    </div>
  );
}
