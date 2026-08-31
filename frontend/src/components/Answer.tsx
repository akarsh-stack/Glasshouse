import { Fragment, useMemo } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { STAGE_COLOR } from "../lib/stages";

interface AnswerProps {
  text: string;
  streaming: boolean;
  /** How many retrieved chunks exist — citations [n] outside this range
      render as plain text. */
  citationCount: number;
  /** 1-based citation currently highlighted, from either side of the link. */
  activeCitation: number | null;
  onCitationHover: (n: number | null) => void;
  onCitationSelect: (n: number) => void;
}

/**
 * Render streamed answer text, turning [n] citations into controls wired to the
 * chunk cards.
 *
 * The model is instructed to cite its passages, and the cards are numbered to
 * match — but until these were linked, checking a claim meant reading a number
 * in one panel and finding it by eye in another. For a product whose entire
 * argument is "you can see where the answer came from", that gap was the wrong
 * one to leave. Hovering a citation lights its card; activating one scrolls to
 * it. Buttons rather than <sup> so the link is keyboard-reachable.
 */
export function Answer({
  text,
  streaming,
  citationCount,
  activeCitation,
  onCitationHover,
  onCitationSelect,
}: AnswerProps) {
  const reducedMotion = useReducedMotion();
  const parts = useMemo(() => {
    const out: { kind: "text" | "cite"; value: string }[] = [];
    const re = /\[(\d{1,2})\]/g;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      const n = parseInt(m[1], 10);
      if (n >= 1 && n <= citationCount) {
        if (m.index > last) out.push({ kind: "text", value: text.slice(last, m.index) });
        out.push({ kind: "cite", value: m[1] });
        last = m.index + m[0].length;
      }
    }
    if (last < text.length) out.push({ kind: "text", value: text.slice(last) });
    return out;
  }, [text, citationCount]);

  return (
    <motion.div
      className="whitespace-pre-wrap text-lede text-ink-100"
      initial={reducedMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
    >
      {parts.map((p, i) => {
        if (p.kind === "text") return <Fragment key={i}>{p.value}</Fragment>;
        const n = parseInt(p.value, 10);
        const active = activeCitation === n;
        return (
          <button
            key={i}
            type="button"
            aria-label={`Show source ${n}`}
            onMouseEnter={() => onCitationHover(n)}
            onMouseLeave={() => onCitationHover(null)}
            onFocus={() => onCitationHover(n)}
            onBlur={() => onCitationHover(null)}
            onClick={() => onCitationSelect(n)}
            // Left margin only. `mx` put a gap on the trailing side too, so a
            // sentence ending "…93 percent[1]." rendered as "…93 percent [1] ."
            // — a floating period, which is the kind of detail that makes an
            // interface look machine-assembled.
            className="ml-0.5 inline-flex -translate-y-[0.35em] cursor-pointer items-center rounded-sm border px-1 align-baseline font-mono text-label leading-4 transition-[background-color,border-color,box-shadow,color] duration-120"
            style={{
              color: active ? "#080D1A" : STAGE_COLOR.retrieve,
              backgroundColor: active ? STAGE_COLOR.retrieve : "transparent",
              borderColor: active ? STAGE_COLOR.retrieve : `${STAGE_COLOR.retrieve}55`,
              boxShadow: active
                ? `0 0 10px -1px ${STAGE_COLOR.retrieve}88`
                : `0 0 5px -1px ${STAGE_COLOR.retrieve}44`,
            }}
          >
            {p.value}
          </button>
        );
      })}
      {streaming && <span className="answer-caret" aria-hidden />}
    </motion.div>
  );
}
