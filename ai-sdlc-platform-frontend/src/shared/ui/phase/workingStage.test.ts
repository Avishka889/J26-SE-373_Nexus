import { describe, expect, it } from "vitest";
import { workingStage } from "./workingStage";

/**
 * Which stage a run is working on, and since when.
 *
 * A run marks every stage it will produce as generating when it starts, so a
 * page that showed each one's status had a spinner on all of them, and nothing
 * said which was working or for how long. Reported from the live run, where Test
 * Generation waited three minutes on the model with nothing to say so.
 */
const ORDER = ["generation", "run", "quality", "review"] as const;
const STARTED = "2026-10-06T05:20:18Z";

describe("the stage a run is working on", () => {
  it("is the first in run order still generating, timed from the run's start", () => {
    const working = workingStage(
      ORDER,
      {
        generation: { status: "generating" },
        run: { status: "generating" },
        quality: { status: "generating" },
      },
      STARTED,
    );

    expect(working).toEqual({ id: "generation", since: STARTED });
  });

  it("is timed from when the stage before it finished in this run", () => {
    const working = workingStage(
      ORDER,
      {
        generation: { status: "complete", generatedAt: "2026-10-06T05:24:24Z" },
        run: { status: "complete", generatedAt: "2026-10-06T05:24:42Z" },
        quality: { status: "generating" },
      },
      STARTED,
    );

    expect(working).toEqual({ id: "quality", since: "2026-10-06T05:24:42Z" });
  });

  it("ignores a stage finished before this run began", () => {
    const working = workingStage(
      ORDER,
      {
        generation: { status: "complete", generatedAt: "2026-10-06T04:00:00Z" },
        run: { status: "generating" },
      },
      STARTED,
    );

    expect(working).toEqual({ id: "run", since: STARTED });
  });

  it("names the stage without a time when no full run is going, as during a retry", () => {
    const working = workingStage(ORDER, { quality: { status: "generating" } }, null);

    expect(working).toEqual({ id: "quality", since: null });
  });

  it("is nothing when no stage is generating", () => {
    const working = workingStage(
      ORDER,
      { generation: { status: "complete", generatedAt: STARTED }, run: { status: "failed" } },
      STARTED,
    );

    expect(working).toBeNull();
  });
});
