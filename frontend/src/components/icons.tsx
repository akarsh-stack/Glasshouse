import type { SVGProps } from "react";

/*
 * A small icon set, hand-rolled rather than pulled from a library.
 *
 * The app needs six glyphs; adding an icon package for that is ~1 MB of
 * dependency to tree-shake for six paths. These follow the Lucide conventions
 * so swapping to it later is a straight substitution: 24-unit grid, 2px stroke,
 * round caps and joins, currentColor.
 *
 * The rule these exist to satisfy: structural icons must be vectors. The rail
 * toggle used the glyphs "⟨" and "⟩" and the delete button used "×" — those are
 * font-dependent, resist stroke and size tokens, and are announced literally by
 * screen readers.
 */

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 16, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const ChevronLeft = (p: IconProps) => (
  <Icon {...p}><path d="m15 18-6-6 6-6" /></Icon>
);

export const ChevronRight = (p: IconProps) => (
  <Icon {...p}><path d="m9 18 6-6-6-6" /></Icon>
);

export const Close = (p: IconProps) => (
  <Icon {...p}><path d="M18 6 6 18M6 6l12 12" /></Icon>
);

export const Upload = (p: IconProps) => (
  <Icon {...p}>
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <path d="M17 8l-5-5-5 5" />
    <path d="M12 3v12" />
  </Icon>
);

export const Play = (p: IconProps) => (
  <Icon {...p}><path d="M6 4.5v15l13-7.5-13-7.5Z" /></Icon>
);

export const Stop = (p: IconProps) => (
  <Icon {...p}><rect x="6" y="6" width="12" height="12" rx="1.5" /></Icon>
);

export const Check = (p: IconProps) => (
  <Icon {...p}><path d="M20 6 9 17l-5-5" /></Icon>
);

export const Alert = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5v5.5M12 16.5h.01" />
  </Icon>
);

/** Indeterminate progress. The one place an infinite animation is correct. */
export const Spinner = ({ size = 16, className, ...rest }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    focusable="false"
    className={`spin-slow ${className ?? ""}`}
    {...rest}
  >
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" opacity="0.25" />
    <path
      d="M21 12a9 9 0 0 0-9-9"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
  </svg>
);
