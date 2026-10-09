/**
 * Which features can read a real backend, and how the flag that says so is read.
 *
 * Separate from `env.ts` because two very different callers need it and only one
 * of them runs in a browser. `env.ts` applies this to `import.meta.env`, and the
 * Vite config applies it to `process.env` so a bad value fails the build. Neither
 * may own the list: a second copy of these names is a second thing to forget to
 * update.
 *
 * Nothing here touches `import.meta`, which is what makes it importable from the
 * config.
 */

/**
 * The closed set. A name outside it is a typo, and a typo in a flag that selects
 * between real and demo data is the worst kind: the app comes up, looks right,
 * and quietly shows hand written content. So an unknown name is refused rather
 * than ignored.
 */
export const LIVE_FEATURES = [
  "projects",
  "requirements",
  "activity",
  "settings",
  "testing",
  "code-generation",
  "deployment",
] as const;

export type LiveFeature = (typeof LIVE_FEATURES)[number];

/**
 * Features that cannot be live on their own.
 *
 * A design belongs to a project. With projects coming from the server and designs
 * coming from fixtures, the fixture store is asked for a project id it has never
 * seen: it answers with a blank design rather than an error, so the screen looks
 * merely empty instead of misconfigured. Requiring the pair closes that, and it is
 * the same rule that keeps real and fixture gates from mixing, since gates are
 * read under the projects flag.
 */
export const REQUIRES: Partial<Record<LiveFeature, LiveFeature>> = {
  requirements: "projects",
  // The code phase reads a project's own code snapshot, and refuses to
  // generate until that project's design gate has been approved. On fixture
  // projects it would answer with demo content for a project the server has
  // never heard of, which reads as a working phase rather than as a
  // misconfiguration.
  "code-generation": "projects",
  // Testing refuses to start until the server's own code gate has been
  // approved for the current code version. With code generation on fixtures
  // there is no such gate on the server, so every run would be refused with
  // "this project's code has not been approved" and the phase would look
  // broken rather than misconfigured.
  testing: "code-generation",
  // Deployment refuses to start until the server's own test review has
  // approved the current test version. With testing on fixtures there is no
  // such approval on the server, so every run would be refused and the phase
  // would read as broken rather than as misconfigured.
  deployment: "testing",
};

export function parseLiveFeatures(
  raw: string | undefined,
): ReadonlySet<LiveFeature> {
  const names = (raw ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);

  const unknown = names.filter(
    (name) => !(LIVE_FEATURES as readonly string[]).includes(name),
  );
  if (unknown.length > 0) {
    throw new Error(
      `VITE_LIVE_FEATURES names features that do not exist: ${unknown.join(", ")}. ` +
        `Known features are: ${LIVE_FEATURES.join(", ")}.`,
    );
  }

  const live = new Set(names as LiveFeature[]);
  for (const [feature, needed] of Object.entries(REQUIRES) as [
    LiveFeature,
    LiveFeature,
  ][]) {
    if (live.has(feature) && !live.has(needed)) {
      throw new Error(
        `VITE_LIVE_FEATURES has "${feature}" live but not "${needed}". ` +
          `${feature} reads data that belongs to a ${needed} record, so on fixtures it would ` +
          `answer with a blank instead of an error. Add "${needed}" or remove "${feature}".`,
      );
    }
  }
  return live;
}

/**
 * The modes that may read fixtures: the Playwright suite's (`--mode fixtures`,
 * whose checks assert things about four authored demo projects) and vitest's.
 */
export const FIXTURE_MODES: ReadonlySet<string> = new Set(["fixtures", "test"]);

/**
 * Which features read the backend in a mode.
 *
 * Fixtures are unwired from the running app: in development and in a
 * production build every feature is live, whatever VITE_LIVE_FEATURES says,
 * so a missing or partial flag can no longer bring up a page of demo data that
 * looks real. The fixtures themselves stay, for the fixture modes above.
 */
export function liveFeaturesFor(
  mode: string,
  raw: string | undefined,
): ReadonlySet<LiveFeature> {
  return FIXTURE_MODES.has(mode)
    ? parseLiveFeatures(raw)
    : new Set(LIVE_FEATURES);
}
