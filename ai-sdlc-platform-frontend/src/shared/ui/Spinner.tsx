import type { CSSProperties } from "react";
import { cn } from "@/shared/utils/cn";

/** Diameter and stroke, in pixels. */
const SIZES = {
  xs: [12, 2],
  sm: [16, 2],
  md: [24, 3],
  lg: [44, 4],
} as const;

export type SpinnerSize = keyof typeof SIZES;

/**
 * The platform's one loading indicator, used by every loading state so they all
 * look and behave alike (`.tp-spinner` in `index.css`).
 *
 * `tone="current"` takes the colour of the text around it, which is what an
 * inline indicator in a button or a chip needs; `tone="accent"` is the brand's
 * loader colour, for a spinner standing on its own. A spinner beside words that
 * already say what is happening is `decorative`, hidden from assistive
 * technology so the words are not repeated; otherwise it announces its label.
 */
export function Spinner({
  size = "sm",
  tone = "current",
  label = "Loading",
  decorative = false,
  className,
  style,
}: {
  size?: SpinnerSize;
  tone?: "current" | "accent";
  label?: string;
  decorative?: boolean;
  className?: string;
  /** Merged over the size variables, for a colour an icon slot passes. */
  style?: CSSProperties;
}) {
  const [diameter, stroke] = SIZES[size];
  const sized = {
    "--tp-spinner-size": `${diameter}px`,
    "--tp-spinner-stroke": `${stroke}px`,
    ...style,
  } as CSSProperties;
  return (
    <span
      data-spinner
      className={cn("tp-spinner", tone === "accent" && "tp-spinner-accent", className)}
      style={sized}
      {...(decorative ? { "aria-hidden": true } : { role: "status", "aria-label": label })}
    />
  );
}

/**
 * A spinner an icon slot can take, where a component is passed as an icon and
 * given a className, as lucide icons are.
 */
export function SpinnerIcon({ className, style }: { className?: string; style?: CSSProperties }) {
  return <Spinner size="xs" decorative className={className} style={style} />;
}

/** What a page or a panel shows while its data is on its way: a spinner, not words. */
export function PageLoader({ label = "Loading", className }: { label?: string; className?: string }) {
  return (
    <div
      role="status"
      aria-label={label}
      className={cn("flex w-full flex-1 items-center justify-center py-24", className)}
    >
      <span className="tp-spinner-halo">
        <Spinner size="lg" tone="accent" decorative />
      </span>
    </div>
  );
}
