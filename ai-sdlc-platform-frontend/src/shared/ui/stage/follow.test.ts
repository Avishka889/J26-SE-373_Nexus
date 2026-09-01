import { describe, expect, it } from "vitest";
import { stageToFollow } from "./follow";

/**
 * Reported from the browser: the phase never opened the review stage on its
 * own, so a reader who had just watched a run finish had to go and find the
 * decision themselves.
 */
const ORDER = ["scope", "contract", "build", "review"] as const;
type Id = (typeof ORDER)[number];

function follow(
  complete: Id[],
  extra: Partial<Parameters<typeof stageToFollow<Id>>[0]> = {},
) {
  return stageToFollow<Id>({
    order: ORDER,
    isComplete: (id) => complete.includes(id),
    isGenerating: true,
    sawGenerating: true,
    userChoseStage: false,
    followedTo: null,
    ...extra,
  });
}

describe("which stage the page follows a run to", () => {
  it("opens the stage that just finished", () => {
    expect(follow(["scope"])).toBe("scope");
    expect(follow(["scope", "contract"])).toBe("contract");
  });

  it("lands on the last stage even though nothing is generating by then", () => {
    /**
     * The bug. The snapshot that reports the review stage complete is the same
     * one that reports nothing generating, so a rule that asked only about
     * `isGenerating` stopped one stage short, every time.
     */
    expect(
      follow(["scope", "contract", "build", "review"], {
        isGenerating: false,
        sawGenerating: true,
        followedTo: "build",
      }),
    ).toBe("review");
  });

  it("does nothing on a phase the reader merely arrived at", () => {
    /** No run was watched, so the page opens where the reader put it. */
    expect(
      follow(["scope", "contract", "build", "review"], {
        isGenerating: false,
        sawGenerating: false,
      }),
    ).toBeNull();
  });

  it("stops once the reader has chosen a stage", () => {
    expect(follow(["scope", "contract"], { userChoseStage: true })).toBeNull();
  });

  it("does not repeat a stage it has already opened", () => {
    expect(follow(["scope", "contract"], { followedTo: "contract" })).toBeNull();
  });

  it("has nothing to open before the first stage finishes", () => {
    expect(follow([])).toBeNull();
  });
});
