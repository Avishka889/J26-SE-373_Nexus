/**
 * Typed access to Vite public env. Fail loud at startup if something is wrong.
 * Only VITE_* values are available in the client bundle, so never put secrets here.
 */

import {
  LIVE_FEATURES,
  type LiveFeature,
  liveFeaturesFor,
  parseLiveFeatures,
} from "./liveFeatures";

export { LIVE_FEATURES, parseLiveFeatures };
export type { LiveFeature };

/**
 * Every feature, outside the fixture modes; there, what the flag names. Read at
 * module load, which is what makes a bad value stop the app rather than degrade
 * it, and the Vite config runs the same parser, so a typo fails the build.
 */
const liveFeatures = liveFeaturesFor(
  import.meta.env.MODE,
  import.meta.env.VITE_LIVE_FEATURES,
);

export const env = {
  /** Defaults for local demo when `.env` is absent; override via VITE_API_URL. */
  apiUrl: import.meta.env.VITE_API_URL?.trim() || "http://localhost:8000",
  /** Which features read a real backend: all of them, outside the fixture modes. */
  liveFeatures,
  /**
   * True when nothing is live, which only a fixture mode can be. For asking "is
   * this a demo at all", never for deciding where one feature's data comes from.
   */
  allFixtures: liveFeatures.size === 0,
} as const;

/**
 * Whether one feature reads a real backend.
 *
 * Every call site that used to branch on a single global boolean asks this
 * instead, so the list advances one feature at a time as each component lands
 * rather than flipping the whole product at once.
 */
export function isLive(feature: LiveFeature): boolean {
  return liveFeatures.has(feature);
}

/**
 * Whether gates are read from the real process API.
 *
 * Not its own flag. A gate belongs to a project's run, so it is live exactly when
 * projects are, and saying so here once means a future approvals view cannot
 * accidentally list fixture gates beside real projects.
 */
export function gatesAreLive(): boolean {
  return isLive("projects");
}

function requireEnv(
  key: keyof ImportMetaEnv,
  value: string | undefined,
): string {
  if (value === undefined || value === "") {
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value;
}

/** Call at bootstrap if you need hard-fail for production deploys. */
export function assertProductionEnv() {
  if (import.meta.env.PROD) {
    requireEnv("VITE_API_URL", import.meta.env.VITE_API_URL);
  }
}
