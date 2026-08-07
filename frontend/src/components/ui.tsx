import clsx from "clsx";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

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

export function Badge({ color = "#8B99B8", className, children, ...rest }: BadgeProps) {
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
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: SegmentedProps<T>) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={clsx(
        "inline-flex items-center rounded border border-ink-700 bg-ink-900 p-0.5 shadow-panel",
        className,
      )}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          aria-pressed={value === opt.value}
          onClick={() => onChange(opt.value)}
          className={clsx(
            "rounded-sm px-2.5 py-1 font-body text-xs font-medium transition-colors duration-120",
            // The selected segment reads as pressed *into* the track, the
            // inverse of Button's raised state — so the two never look like the
            // same control. Inset shadow instead of a lift does that.
            value === opt.value
              ? "bg-ink-700 text-ink-100 shadow-[inset_0_1px_3px_rgba(3,7,18,0.55)]"
              : "text-ink-300 hover:bg-ink-800/60 hover:text-ink-100",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- Skeleton */

export function Skeleton({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={clsx("skeleton", className)} {...rest} />;
}
