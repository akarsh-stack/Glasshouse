import { AnimatePresence, motion } from "framer-motion";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { STAGE_COLOR } from "../lib/stages";
import type { Tier } from "../types";

/*
 * What changing the tier actually changes.
 *
 * The switch was three words and no feedback: picking "deep" gave no signal
 * that anything had happened, let alone what it would do. This is the answer to
 * "and then what?" — the model that will answer, and the trade being made.
 *
 * The model id is *real*, resolved server-side by the same `resolve_models` the
 * router uses and published on /api/health. Hardcoding "Haiku / Sonnet / Opus"
 * here would go stale the moment LLM_BASE_URL points at Groq.
 *
 * The two bars are deliberately NOT presented as measurements. This project's
 * whole argument is that the numbers on screen are measured, so inventing a
 * "1.2s" for a query nobody ran would undermine the thing it exists to prove.
 * They are labelled `relative` and drawn without units — a spec sheet, not a
 * reading. The measured numbers appear in the receipt after a real query.
 */

interface TierSpec {
  /** 0..1, relative to the other tiers. Characteristics, not timings. */
  speed: number;
  depth: number;
  blurb: string;
}

const SPEC: Record<Tier, TierSpec> = {
  fast: { speed: 1.0, depth: 0.35, blurb: "cheapest, first to answer" },
  quality: { speed: 0.6, depth: 0.7, blurb: "the default trade" },
  deep: { speed: 0.3, depth: 1.0, blurb: "most capable, slowest" },
};

const TIER_HUE: Record<Tier, string> = {
  fast: STAGE_COLOR.embed,
  quality: STAGE_COLOR.generate,
  deep: STAGE_COLOR.retrieve,
};

function Bar({ value, hue, label }: { value: number; hue: string; label: string }) {
  const reducedMotion = useReducedMotion();
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 shrink-0 font-mono text-label text-ink-300">{label}</span>
      <div className="h-1 w-16 overflow-hidden rounded-full bg-ink-950/70 shadow-[inset_0_1px_2px_rgba(2,5,12,0.6)]">
        <motion.div
          className="h-full rounded-full"
          initial={false}
          animate={{ width: `${value * 100}%` }}
          transition={
            reducedMotion
              ? { duration: 0 }
              : { type: "spring", stiffness: 260, damping: 30 }
          }
          style={{ backgroundColor: hue, boxShadow: `0 0 6px ${hue}88` }}
        />
      </div>
    </div>
  );
}

export function TierReadout({
  tier,
  model,
}: {
  tier: Tier;
  /** Resolved model id from /api/health, or null before it arrives. */
  model: string | null;
}) {
  const reducedMotion = useReducedMotion();
  const spec = SPEC[tier];
  const hue = TIER_HUE[tier];

  return (
    <div className="flex items-center gap-4">
      {/* The bars animate between tiers rather than swapping, so the change
          reads as the same two quantities moving. */}
      <div className="hidden flex-col gap-1 sm:flex">
        <Bar value={spec.speed} hue={hue} label="speed" />
        <Bar value={spec.depth} hue={hue} label="depth" />
      </div>

      {/* The model name does swap, because it is a different string, not a
          different amount. Height is fixed so the header never reflows. */}
      <div className="flex h-8 min-w-0 flex-col justify-center">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={tier}
            initial={reducedMotion ? false : { opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reducedMotion ? undefined : { opacity: 0, y: -5 }}
            transition={{ duration: reducedMotion ? 0 : 0.16, ease: [0.16, 1, 0.3, 1] }}
            className="min-w-0"
          >
            <p
              className="truncate font-mono text-label"
              style={{ color: hue }}
              title={model ?? undefined}
            >
              {model ?? "resolving…"}
            </p>
            <p className="mt-1 truncate font-body text-label normal-case tracking-normal text-ink-300">
              {spec.blurb}
            </p>
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

export { TIER_HUE };
