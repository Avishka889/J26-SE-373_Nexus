import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  LIVE_FEATURES,
  liveFeaturesFor,
  parseLiveFeatures,
} from "./liveFeatures";

/**
 * The flag that decides real data from demo data.
 *
 * Worth its own test because of how it fails when it is wrong. Every other
 * misconfiguration in this app is loud: a bad URL is a network error, a missing
 * variable throws. A mistyped feature name would be silent, and the app would
 * come up looking correct while showing four hand written demo projects. So the
 * parser refuses rather than falls back, and this pins that it does.
 */
describe("which features read a real backend", () => {
  it("reads a comma separated list", () => {
    const live = parseLiveFeatures("projects,requirements");
    expect(live.has("projects")).toBe(true);
    expect(live.has("requirements")).toBe(true);
    expect(live.has("testing")).toBe(false);
  });

  it("tolerates spacing and trailing commas", () => {
    // The value is hand edited in a .env file, so it will be.
    const live = parseLiveFeatures(" projects , requirements ,");
    expect([...live].sort()).toEqual(["projects", "requirements"]);
  });

  it("treats absent and empty as all fixtures", () => {
    expect(parseLiveFeatures(undefined).size).toBe(0);
    expect(parseLiveFeatures("").size).toBe(0);
  });

  it("refuses a name that is not a feature", () => {
    // The whole point. Falling back to fixtures here is the failure mode this
    // guard exists to prevent, not an acceptable default.
    expect(() => parseLiveFeatures("projects,requirement")).toThrowError(
      /do not exist/,
    );
  });

  it("names what it does know, so the message is actionable", () => {
    expect(() => parseLiveFeatures("wireframes")).toThrowError(/projects/);
  });

  it("refuses requirements without projects", () => {
    // A design belongs to a project. With projects on fixtures the store answers
    // an unknown id with a blank design rather than an error, so the screen looks
    // empty instead of misconfigured.
    expect(() => parseLiveFeatures("requirements")).toThrowError(
      /not "projects"/,
    );
  });

  it("accepts the pair", () => {
    expect(() => parseLiveFeatures("requirements,projects")).not.toThrow();
  });

  it("refuses testing without code generation", () => {
    // Testing refuses to start until the server's own code gate has been
    // approved. With code generation on fixtures there is no such gate on the
    // server, so every run would be refused and the phase would read as broken
    // rather than as misconfigured.
    expect(() => parseLiveFeatures("testing,projects")).toThrowError(
      /not "code-generation"/,
    );
  });

  it("accepts the whole chain", () => {
    expect(() =>
      parseLiveFeatures("testing,code-generation,projects"),
    ).not.toThrow();
  });

  it("refuses deployment without testing", () => {
    // Deployment starts only from an approved test version, which on fixtures
    // the server has never seen, so every run would be refused.
    expect(() =>
      parseLiveFeatures("deployment,code-generation,projects"),
    ).toThrowError(/not "testing"/);
  });

  it("accepts deployment with the chain beneath it", () => {
    expect(() =>
      parseLiveFeatures("deployment,testing,code-generation,projects"),
    ).not.toThrow();
  });

  it("accepts every known feature at once", () => {
    // Guards against a name being added to the list and not to the parser.
    expect(() => parseLiveFeatures(LIVE_FEATURES.join(","))).not.toThrow();
  });

  it("is the value the committed default uses", () => {
    // .env.development is the record of how much of the product is real. If this
    // list stops parsing, the app stops booting in development. Read from the
    // file itself: a copy of the list kept here had gone stale.
    const committed = readFileSync(
      join(__dirname, "..", "..", ".env.development"),
      "utf8",
    ).match(/^VITE_LIVE_FEATURES=(.*)$/m)?.[1];
    expect(committed).toBeTruthy();
    expect(() => parseLiveFeatures(committed ?? "")).not.toThrow();
  });
});

describe("which modes may read fixtures", () => {
  it("reads only the backend in development and in a production build, whatever the flag says", () => {
    for (const mode of ["development", "production"]) {
      for (const raw of [undefined, "", "projects"]) {
        expect([...liveFeaturesFor(mode, raw)].sort()).toEqual(
          [...LIVE_FEATURES].sort(),
        );
      }
    }
  });

  it("reads what the flag names in the test modes, and fixtures for the rest", () => {
    expect(liveFeaturesFor("fixtures", "").size).toBe(0);
    expect(
      [...liveFeaturesFor("test", "projects,requirements")].sort(),
    ).toEqual(["projects", "requirements"]);
  });
});
