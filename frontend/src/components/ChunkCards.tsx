import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { fmtNum, truncate } from "../lib/format";
import { STAGE_COLOR } from "../lib/stages";
import type { DocumentInfo, RetrievedChunk } from "../types";

interface ChunkCardsProps {
  /** Already sorted by score, descending */
  chunks: RetrievedChunk[];
  documents: DocumentInfo[] | null;
  /** 1-based index highlighted from either the answer's citations or here. */
  activeCitation: number | null;
  onHover: (n: number | null) => void;
  /** Set when the user activates a citation, so the card scrolls into view. */
  scrollToCitation: number | null;
  /** Changes on every activation, so repeat clicks re-trigger the scroll. */
  scrollNonce: number;
}

export function ChunkCards({
  chunks,
  documents,
  activeCitation,
  onHover,
  scrollToCitation,
  scrollNonce,
}: ChunkCardsProps) {
  const reducedMotion = useReducedMotion();
  const refs = useRef<(HTMLLIElement | null)[]>([]);

  // Scroll the requested card into view when a citation is activated. `smooth`
  // is dropped under reduced motion, where a scroll animation is exactly the
  // kind of unrequested movement the preference is asking us not to make.
  useEffect(() => {
    if (scrollToCitation === null) return;
    const el = refs.current[scrollToCitation - 1];
    el?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "nearest",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollToCitation, scrollNonce, reducedMotion]);

  const docName = (id: string): string => {
    const doc = documents?.find((d) => d.id === id);
    return doc ? doc.filename : truncate(id, 14);
  };

  if (chunks.length === 0) {
    return (
      <p className="px-1 text-sm text-ink-300">
        No matching passages — the answer will be generated without document
        context.
      </p>
    );
  }

  return (
    // `tilt-scene` supplies the perspective the children's rotateX needs; on a
    // flat (perspective-less) parent the same rotation is an orthographic
    // squash that reads as a vertical glitch rather than a tilt.
    <ol className="tilt-scene space-y-2">
      {chunks.map((chunk, i) => {
        const pct = Math.max(0, Math.min(1, chunk.score));
        const active = activeCitation === i + 1;
        return (
          <motion.li
            key={chunk.chunk_id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            onMouseEnter={() => onHover(i + 1)}
            onMouseLeave={() => onHover(null)}
            // Cards arrive as a short stagger, top-ranked first, which matches
            // the order retrieval actually ranked them in. Capped at 6 so a
            // large top-k doesn't turn into a slow cascade.
            initial={reducedMotion ? false : { opacity: 0, y: 10, rotateX: -7 }}
            animate={{ opacity: 1, y: 0, rotateX: 0 }}
            transition={
              reducedMotion
                ? { duration: 0 }
                : { duration: 0.34, delay: Math.min(i, 6) * 0.045, ease: [0.16, 1, 0.3, 1] }
            }
            whileHover={reducedMotion ? undefined : { y: -2 }}
            className="group rounded-md border bg-ink-800/60 p-3 shadow-panel surface-edge transition-[box-shadow,border-color,background-color] duration-120 hover:shadow-lift"
            style={{
              // The linked state has to be legible without colour alone, so it
              // moves border, background and glow together — and the [n] marker
              // below inverts, which is a shape change rather than a hue shift.
              borderColor: active ? `${STAGE_COLOR.retrieve}99` : "#33456F",
              backgroundColor: active
                ? `${STAGE_COLOR.retrieve}12`
                : "rgba(28,41,71,0.6)",
              boxShadow: active
                ? `0 0 0 1px ${STAGE_COLOR.retrieve}44, 0 2px 4px rgba(2,5,12,0.55), 0 8px 18px -4px rgba(2,5,12,0.55)`
                : undefined,
            }}
          >
            <div className="mb-1.5 flex items-baseline justify-between gap-2">
              <span className="min-w-0 truncate font-body text-xs font-medium text-ink-100">
                <span
                  className="mr-1.5 inline-block rounded-sm px-1 font-mono text-label transition-colors duration-120"
                  style={{
                    color: active ? "#080D1A" : STAGE_COLOR.retrieve,
                    backgroundColor: active ? STAGE_COLOR.retrieve : "transparent",
                  }}
                >
                  [{i + 1}]
                </span>
                {docName(chunk.document_id)}
                {chunk.page_number !== null && chunk.page_number !== undefined && (
                  <span className="ml-1 text-ink-300">p.{chunk.page_number}</span>
                )}
              </span>
            </div>
            {/* Clamp lifts to 5 lines when the card is the active citation:
                if you followed a link here, you came to read the passage, and
                three lines was rarely enough to contain the cited claim. */}
            <p
              className="text-meta text-ink-300 transition-[max-height] duration-200"
              style={{
                display: "-webkit-box",
                WebkitLineClamp: active ? 6 : 3,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
            >
              {chunk.text}
            </p>
            <div className="mt-2.5 flex items-center gap-2.5">
              {/* Inset track: the bar should read as filling a channel cut into
                  the card, not as a stripe laid on top of it. */}
              <div className="h-1 flex-1 overflow-hidden rounded-full bg-ink-950/70 shadow-[inset_0_1px_2px_rgba(2,5,12,0.6)]">
                <motion.div
                  className="h-full rounded-full"
                  initial={reducedMotion ? false : { width: 0 }}
                  animate={{ width: `${pct * 100}%` }}
                  transition={
                    reducedMotion
                      ? { duration: 0 }
                      : {
                          duration: 0.55,
                          delay: Math.min(i, 6) * 0.045 + 0.12,
                          ease: [0.16, 1, 0.3, 1],
                        }
                  }
                  style={{
                    backgroundColor: STAGE_COLOR.retrieve,
                    // Faint bloom in the retrieve hue so the filled portion
                    // looks emissive against the recessed track.
                    boxShadow: `0 0 6px ${STAGE_COLOR.retrieve}66`,
                  }}
                />
              </div>
              {/* Promoted from ink-300 to ink-100 and tabular: this is a
                  measurement, and it was the dimmest thing on the card despite
                  being the reason the card is here at all. */}
              <span className="font-mono text-label font-medium tabular-nums text-ink-100">
                {fmtNum(chunk.score, 3)}
              </span>
            </div>
          </motion.li>
        );
      })}
    </ol>
  );
}
