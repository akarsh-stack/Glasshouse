import clsx from "clsx";
import { useId } from "react";
import { motion } from "framer-motion";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { useReducedMotion } from "../hooks/useReducedMotion";

/* ---------------------------------------------------------------- Panel */

export function Panel({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx(
        // Depth is applied here rather than per-call-site so every surface in
        // the app is stacked on the same scale. The signature is unchanged.
        // Callers wanting more lift pass `shadow-raised`/`shadow-lift`, which
        // override because Tailwind emits them after `shadow-panel` in the
        // stylesheet (config order) — not because of class-attribute order,
        // which CSS ignores.
        "rounded-md border border-ink-700 bg-ink-900 shadow-panel surface-edge",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

/* --------------------------------------------------------------- Button */

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "solid" | "ghost";
}

export function Button({
  className,
  variant = "solid",
  ...rest
}: ButtonProps) {
  return (
    <button
      className={clsx(
        "inline-flex items-center gap-2 rounded border px-3 py-1.5 font-body text-sm font-medium",
        "transition-[background-color,border-color,color,box-shadow,transform] duration-120 ease-out",
        // A disabled control must not appear liftable, so the lift and its
        // shadow are both dropped rather than just dimmed.
        "disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none disabled:hover:translate-y-0",
        variant === "solid" &&
          "border-ink-700 bg-ink-800 text-ink-100 shadow-panel surface-edge hover:-translate-y-px hover:border-ink-300/40 hover:bg-ink-700 hover:shadow-raised active:translate-y-0 active:shadow-panel",
        variant === "ghost" &&
          "border-transparent bg-transparent text-ink-300 hover:bg-ink-800 hover:text-ink-100",
        className,
      )}
      {...rest}
    />
  );
}

/* ---------------------------------------------------------------- Badge */

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  color?: string; // stage hue — used for text + border tint
}

export function Badge({ color = "#94A6CC", className, children, ...rest }: BadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1 font-body text-xs font-medium",
        className,
      )}
      style={{
        color,
        borderColor: `${color}55`,
        backgroundColor: `${color}14`,
        // Outer bloom in the badge's own hue plus the standard inset top edge.
        // A tinted rectangle is flat; the bloom is what makes it read as a lit
        // chip sitting on the panel.
        boxShadow: `0 0 12px -2px ${color}33, inset 0 1px 0 0 ${color}22`,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}

/* ------------------------------------------------------------ Segmented */

interface SegmentedProps<T extends string> {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
  className?: string;
  /** Tints the moving indicator; used by the tier switch to carry stage hue. */
  accent?: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
  accent,
}: SegmentedProps<T>) {
  const reducedMotion = useReducedMotion();
  // One id per mounted control, so the two switchers in the header don't share
  // a layout animation and fling their indicators at each other.
  const groupId = useId();

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={clsx(
        "relative inline-flex items-center rounded border border-ink-700 bg-ink-900 p-0.5 shadow-panel",
        className,
      )}
    >
      {options.map((opt) => {
        const selected = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(opt.value)}
            className={clsx(
              "relative rounded-sm px-2.5 py-1 font-body text-xs font-medium transition-colors duration-120",
              selected ? "text-ink-100" : "text-ink-300 hover:text-ink-100",
            )}
          >
            {/* The indicator is a single shared element that travels between
                options rather than a background toggling on and off, so the
                selection reads as one thing moving. It sits *behind* the label
                and is aria-hidden — the state is already on aria-pressed. */}
            {selected && (
              <motion.span
                layoutId={`seg-${groupId}`}
                aria-hidden
                className="absolute inset-0 rounded-sm bg-ink-700 shadow-[inset_0_1px_3px_rgba(2,5,12,0.55)]"
                style={
                  accent
                    ? { boxShadow: `inset 0 1px 3px rgba(2,5,12,0.55), 0 0 10px -2px ${accent}88`, borderBottom: `1.5px solid ${accent}` }
                    : undefined
                }
                transition={
                  reducedMotion
                    ? { duration: 0 }
                    : { type: "spring", stiffness: 520, damping: 38, mass: 0.7 }
                }
              />
            )}
            <span className="relative">{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------- Skeleton */

export function Skeleton({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={clsx("skeleton", className)} {...rest} />;
}
