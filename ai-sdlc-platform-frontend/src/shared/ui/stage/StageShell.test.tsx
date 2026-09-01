import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StageShell } from "./StageShell";
import type { StageModelUse } from "@sdlc/contracts-ts";
import type { StageChrome, StageChromeState } from "./types";

/**
 * The chrome is shared by every gated phase, so a state one phase can produce
 * and the chrome cannot express is a phase that has to grow its own chrome.
 * That is how the testing phase came to have one, and `skipped` is the state
 * that exposed it: the stage had nothing to do on this target, which is not
 * failing and is not finishing.
 */
const CHROME: StageChrome<"only"> = {
  ids: ["only"],
  meta: { only: { label: "Only", heading: "The only stage", blurb: "what it is for" } },
  sections: { only: [] },
  versionNoun: "test version",
};

afterEach(cleanup);

function shell(stage: StageChromeState) {
  render(
    <StageShell chrome={CHROME} stage={stage} stageId="only" version={2} onRetry={vi.fn()}>
      <p>the stage body</p>
    </StageShell>,
  );
}

describe("a stage that did not apply", () => {
  it("says why, from what the stage reported", () => {
    shell({ status: "skipped", generatedFromVersion: 0, summary: "no scanner reads this stack" });

    expect(screen.getByText(/no scanner reads this stack/)).toBeTruthy();
  });

  it("is not offered a retry, because nothing went wrong", () => {
    shell({ status: "skipped", generatedFromVersion: 0, summary: "nothing to write here" });

    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
  });

  it("does not render the stage body, because there is none", () => {
    shell({ status: "skipped", generatedFromVersion: 0, summary: "nothing to write here" });

    expect(screen.queryByText("the stage body")).toBeNull();
  });

  // A skip that does not say why is indistinguishable from one that quietly did
  // nothing, so the chrome supplies a sentence when the stage supplied none.
  it("says something even when the stage said nothing", () => {
    shell({ status: "skipped", generatedFromVersion: 0 });

    expect(screen.getByText(/does not apply/i)).toBeTruthy();
  });

  it("leaves a failed stage its retry, which is a different thing entirely", () => {
    shell({ status: "failed", generatedFromVersion: 1, error: "it broke" });

    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
  });
});

describe("a stage that has not run yet", () => {
  it("says it starts after the stage before it, by default", () => {
    shell({ status: "pending", generatedFromVersion: 0 });

    expect(screen.getByText(/It starts once the stage before it finishes/)).toBeTruthy();
  });

  // While the design waits on its questions the stage before has finished, so
  // "once the stage before it finishes" would be wrong.
  it("says what it waits on when that is something else", () => {
    render(
      <StageShell
        chrome={CHROME}
        stage={{ status: "pending", generatedFromVersion: 0 }}
        stageId="only"
        version={1}
        onRetry={vi.fn()}
        pendingNote="This stage starts once you continue from the design's questions."
      >
        <p>the stage body</p>
      </StageShell>,
    );

    expect(screen.getByText("This stage starts once you continue from the design's questions.")).toBeTruthy();
    expect(screen.queryByText(/the stage before it finishes/)).toBeNull();
  });
});

describe("a stage generating", () => {
  function generating(version: number) {
    render(
      <StageShell
        chrome={CHROME}
        stage={{ status: "generating", generatedFromVersion: 0 }}
        stageId="only"
        version={version}
        onRetry={vi.fn()}
      >
        <p>the stage body</p>
      </StageShell>,
    );
  }

  it("names the version it works from", () => {
    generating(2);
    expect(screen.getByText("Generating from test version 2")).toBeTruthy();
  });

  // The server's version counts what was written, so a first run is at zero
  // until its first artefact lands, and there is no version 0 to name.
  it("does not name a version 0 on a first run", () => {
    generating(0);
    expect(screen.getByText("Generating the first version")).toBeTruthy();
    expect(screen.queryByText(/version 0/)).toBeNull();
  });

  // It said the previous version stayed on screen, and showed nothing: every
  // stage of a run is generating at once.
  it("shows what was there until the new version replaces it", () => {
    render(
      <StageShell
        chrome={CHROME}
        stage={{ status: "generating", generatedFromVersion: 2 }}
        stageId="only"
        version={3}
        onRetry={vi.fn()}
      >
        <p>the stage body</p>
      </StageShell>,
    );

    expect(screen.getByText("Generating from test version 3")).toBeTruthy();
    expect(screen.getByText("the stage body")).toBeTruthy();
    expect(screen.getByText(/as it was at test version 2/)).toBeTruthy();
  });

  // A run marks every stage generating from its start, so each showed a spinner
  // as though all of them were working at once.
  it("says it waits for the stage the run is working on, with no spinner of its own", () => {
    const { container } = render(
      <StageShell
        chrome={CHROME}
        stage={{ status: "generating", generatedFromVersion: 0 }}
        stageId="only"
        version={1}
        onRetry={vi.fn()}
        waitingFor="Test Generation"
      >
        <p>the stage body</p>
      </StageShell>,
    );

    expect(screen.getByText("Starts once Test Generation finishes")).toBeTruthy();
    expect(screen.queryByText(/^Generating/)).toBeNull();
    expect(container.querySelector("[data-spinner]")).toBeNull();
  });
});

/**
 * A second click on Try again started a second run of the stage, each paying
 * for its model calls, because the button stayed live while the first request
 * was on its way.
 */
describe("trying a failed stage again", () => {
  it("is sent once, and offered again only when the server has answered", async () => {
    let answer: (value: unknown) => void = () => {};
    const onRetry = vi.fn(() => new Promise((resolve) => (answer = resolve)));
    render(
      <StageShell
        chrome={CHROME}
        stage={{ status: "failed", generatedFromVersion: 1, error: "it broke" }}
        stageId="only"
        version={2}
        onRetry={onRetry}
      >
        <p>the stage body</p>
      </StageShell>,
    );
    const button = screen.getByRole("button", { name: /try again/i }) as HTMLButtonElement;

    fireEvent.click(button);
    fireEvent.click(button);

    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
    await act(async () => answer(undefined));
    expect(button.disabled).toBe(false);
  });
});

/**
 * A stage the run never reached said it would start once the stage before it
 * finished, which was not going to happen: the run had stopped.
 */
describe("a stage the run did not reach", () => {
  it("says the run stopped before it, rather than that it is coming", () => {
    render(
      <StageShell
        chrome={CHROME}
        stage={{ status: "pending", generatedFromVersion: 0 }}
        stageId="only"
        version={1}
        onRetry={vi.fn()}
        notReached
      >
        <p>the stage body</p>
      </StageShell>,
    );

    expect(screen.getByText(/not reached/i)).toBeTruthy();
    expect(screen.queryByText(/starts once the stage before it finishes/i)).toBeNull();
  });
});

/**
 * Computed from an output that was since generated again: the stage says so,
 * and offers to compute it again from what is there now.
 */
describe("a stage computed before what it reads changed", () => {
  it("says what changed, and computes it again on request", () => {
    const onRetry = vi.fn();
    render(
      <StageShell
        chrome={CHROME}
        stage={{ status: "complete", generatedFromVersion: 2 }}
        stageId="only"
        version={2}
        onRetry={onRetry}
        computedBefore={["Changelog Analysis"]}
      >
        <p>the stage body</p>
      </StageShell>,
    );

    expect(screen.getByText(/Changelog Analysis was generated again/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Compute again" }));
    expect(onRetry).toHaveBeenCalledWith("only");
    expect(screen.getByText("the stage body")).toBeTruthy();
  });
});

/**
 * Which model answered a stage was written only into the audit log, as one line
 * of words. The stage says it under its own content, as the response named it.
 */
describe("what answered a stage", () => {
  const USE: StageModelUse = {
    answeredBy: ["deepseek-flash"],
    thinking: ["disabled"],
    requests: 2,
    tokensIn: 3100,
    tokensOut: 900,
    reasoningTokens: 0,
  };

  it("is said under a complete stage, as the response named it", () => {
    shell({ status: "complete", generatedFromVersion: 2, modelUse: USE });

    expect(
      screen.getByText(
        "Answered by deepseek-flash, thinking off: 2 requests, 3,100 tokens in and 900 out.",
      ),
    ).toBeTruthy();
  });

  it("counts reasoning where the provider reported some, and one request as one", () => {
    shell({
      status: "complete",
      generatedFromVersion: 2,
      modelUse: { ...USE, requests: 1, tokensOut: 1200, reasoningTokens: 700 },
    });

    expect(screen.getByText(/1 request, 3,100 tokens in and 1,200 out, 700 of them reasoning\./)).toBeTruthy();
  });

  it("says nothing for a stage that asked no model", () => {
    shell({ status: "complete", generatedFromVersion: 2, modelUse: null });

    expect(screen.queryByText(/Answered by/)).toBeNull();
  });

  it("says nothing under a failed stage, whose version it would not describe", () => {
    shell({ status: "failed", generatedFromVersion: 1, error: "it broke", modelUse: USE });

    expect(screen.queryByText(/Answered by/)).toBeNull();
  });
});

/** A stage made with thinking on says how hard, in the words Activity uses. */
describe("what a thinking stage says", () => {
  it("names the level it was asked at", () => {
    shell({
      status: "complete",
      generatedFromVersion: 2,
      modelUse: {
        answeredBy: ["deepseek-flash"],
        thinking: ["high"],
        requests: 1,
        tokensIn: 3100,
        tokensOut: 2400,
        reasoningTokens: 1800,
      },
    });

    expect(
      screen.getByText(
        "Answered by deepseek-flash, thinking on, high effort: 1 request, 3,100 tokens in and 2,400 out, 1,800 of them reasoning.",
      ),
    ).toBeTruthy();
  });
});
