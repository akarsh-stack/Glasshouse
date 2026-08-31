import { motion } from "framer-motion";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { STAGE_COLOR } from "../lib/stages";
import type { DocumentInfo } from "../types";

/*
 * Starter questions for the empty state.
 *
 * Two problems solved at once. The Playground's idle view was an input, a trace
 * with nothing in it, and then half a screen of nothing — the emptiest possible
 * first impression for a product about making things visible. And demoing meant
 * typing a question from memory while someone watched.
 *
 * Suggestions are derived from what is actually loaded rather than hardcoded:
 * if the sample corpus is present the tailored questions appear (including the
 * cache-demo pair), otherwise generic openers that work on any document set. A
 * suggestion that references a document the user never uploaded is worse than
 * no suggestion.
 */

interface Suggestion {
  text: string;
  /** Short note on what this one demonstrates. */
  note: string;
}

const SAMPLE_MATCHERS: { match: RegExp; questions: Suggestion[] }[] = [
  {
    match: /orbital|kessler/i,
    questions: [
      { text: "How much water does life support recycle?", note: "grounded answer" },
      {
        text: "What percentage of water does life support recycle?",
        note: "semantic cache hit",
      },
      { text: "What happens if the control moment gyroscopes fail?", note: "multi-hop" },
    ],
  },
  {
    match: /meridian|release/i,
    questions: [{ text: "What did incremental linking improve?", note: "from the PDF" }],
  },
];

const GENERIC: Suggestion[] = [
  { text: "Summarise the main points", note: "broad retrieval" },
  { text: "What are the key figures mentioned?", note: "specific facts" },
  { text: "What limitations are described?", note: "targeted" },
];

export function suggestionsFor(documents: DocumentInfo[] | null): Suggestion[] {
  if (!documents || documents.length === 0) return [];
  const names = documents.map((d) => d.filename).join(" ");
  const matched = SAMPLE_MATCHERS.filter((m) => m.match.test(names)).flatMap(
    (m) => m.questions,
  );
  return matched.length > 0 ? matched.slice(0, 4) : GENERIC;
}

interface Props {
  documents: DocumentInfo[] | null;
  onPick: (question: string) => void;
}

export function SuggestedQuestions({ documents, onPick }: Props) {
  const reducedMotion = useReducedMotion();
  const suggestions = suggestionsFor(documents);
  if (suggestions.length === 0) return null;

  return (
    <div>
      <p className="label-caps mb-3">Try a question</p>
      <ul className="flex flex-col gap-2">
        {suggestions.map((s, i) => (
          <motion.li
            key={s.text}
            initial={reducedMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={
              reducedMotion
                ? { duration: 0 }
                : { duration: 0.3, delay: 0.05 + i * 0.04, ease: [0.16, 1, 0.3, 1] }
            }
          >
            <button
              type="button"
              onClick={() => onPick(s.text)}
              className="group flex w-full items-center gap-3 rounded-md border border-ink-700 bg-ink-900 px-3.5 py-2.5 text-left shadow-panel surface-edge transition-[border-color,box-shadow,transform] duration-120 hover:-translate-y-px hover:border-ink-600 hover:shadow-raised"
            >
              {/* A hairline in the generate hue, so the row reads as "this will
                  run the pipeline" rather than as a link. */}
              <span
                className="h-4 w-0.5 shrink-0 rounded-full transition-[box-shadow] duration-120"
                style={{
                  backgroundColor: STAGE_COLOR.generate,
                  boxShadow: `0 0 6px ${STAGE_COLOR.generate}66`,
                }}
              />
              <span className="min-w-0 flex-1 truncate font-body text-ui text-ink-100">
                {s.text}
              </span>
              <span className="shrink-0 font-mono text-label text-ink-300 opacity-0 transition-opacity duration-120 group-hover:opacity-100">
                {s.note}
              </span>
            </button>
          </motion.li>
        ))}
      </ul>
    </div>
  );
}
