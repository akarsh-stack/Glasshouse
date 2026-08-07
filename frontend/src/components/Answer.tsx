import { Fragment, useMemo } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { STAGE_COLOR } from "../lib/stages";

interface AnswerProps {
  text: string;
  streaming: boolean;
  /** How many retrieved chunks exist — citations [n] outside this range
      render as plain text. */
  citationCount: number;
}

/** Render streamed answer text, turning [n] citations into small numbered
    references that match the chunk cards in the right panel. */
export function Answer({ text, streaming, citationCount }: AnswerProps) {
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
      className="whitespace-pre-wrap text-[15px] leading-7 text-ink-100"
      initial={reducedMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
    >
      {parts.map((p, i) =>
        p.kind === "text" ? (
          <Fragment key={i}>{p.value}</Fragment>
        ) : (
          <sup
            key={i}
            className="mx-0.5 inline-flex items-center rounded-sm border px-1 font-mono text-[10px] leading-4"
            style={{
              color: STAGE_COLOR.retrieve,
              borderColor: `${STAGE_COLOR.retrieve}55`,
              boxShadow: `0 0 5px -1px ${STAGE_COLOR.retrieve}44`,
            }}
            title={`Source ${p.value}`}
          >
            {p.value}
          </sup>
        ),
      )}
      {streaming && <span className="answer-caret" aria-hidden />}
    </motion.div>
  );
}
