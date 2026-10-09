/**
 * Single source of truth for application fonts.
 *
 * All faces are self-hosted under `src/assets/fonts/` and loaded via
 * `src/assets/fonts/fonts.css`. Stacks intentionally omit system fallbacks so
 * rendered text uses only those files (see index.css `@theme` tokens).
 *
 * Keep family name strings in sync with `@font-face` rules in fonts.css.
 */

/** UI and body typeface. Files: inter-latin-*-normal.woff2 */
export const FONT_SANS = "Inter" as const;

/** Code and tabular typeface. Files: jetbrains-mono-latin-*-normal.woff2 */
export const FONT_MONO = "JetBrains Mono" as const;

/** Exclusive stacks (no system-ui / ui-sans-serif / monospace fallbacks). */
export const FONT_SANS_STACK = `"${FONT_SANS}"` as const;
export const FONT_MONO_STACK = `"${FONT_MONO}"` as const;

export const fonts = {
  sans: {
    family: FONT_SANS,
    stack: FONT_SANS_STACK,
    /** Weights available as WOFF2 under assets/fonts */
    weights: [400, 500, 600, 700, 800] as const,
  },
  mono: {
    family: FONT_MONO,
    stack: FONT_MONO_STACK,
    weights: [400, 500, 600] as const,
  },
  /** Prefer these in React `style={{ fontFamily }}` objects */
  cssVar: {
    sans: "var(--font-sans)",
    mono: "var(--font-mono)",
  },
} as const;

/** @deprecated Use `fonts`. Kept for existing imports during the transition. */
export const typography = {
  sans: FONT_SANS_STACK,
  mono: FONT_MONO_STACK,
  css: fonts.cssVar,
} as const;
