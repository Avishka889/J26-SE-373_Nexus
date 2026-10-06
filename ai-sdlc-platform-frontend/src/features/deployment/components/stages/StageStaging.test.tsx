import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { DeploySnapshot } from "../../api/types";
import { buildDeploySnapshot } from "../../fixtures/buildDeploySnapshot";
import { buildView } from "../../model/view";
import { StageStaging } from "./StageStaging";

afterEach(cleanup);

/**
 * The demo's reviewed release, its candidate failed at the named step. The
 * step is the harness's own name (install, test, image, boot), added when the
 * demo's candidate does not have it.
 */
function failedAt(step: string): DeploySnapshot {
  const snapshot = buildDeploySnapshot("p4", "deploy");
  const candidate = snapshot.candidate;
  if (!candidate) throw new Error("the demo builds a candidate");
  const failed = { ...candidate.steps[0], name: step, outcome: "failed" as const };
  return {
    ...snapshot,
    candidate: {
      ...candidate,
      verified: false,
      // Never empty: the contract asks for at least one step.
      steps: [failed, ...candidate.steps.filter((one) => one.name !== step)],
    },
  };
}

function staging(snapshot: DeploySnapshot) {
  const onRetry = vi.fn();
  const onOpenTesting = vi.fn();
  render(
    <StageStaging
      snapshot={snapshot}
      view={buildView(snapshot)}
      onRetry={onRetry}
      onOpenTesting={onOpenTesting}
    />,
  );
  return { onRetry, onOpenTesting };
}

/**
 * A candidate that failed staging could not be tried again from the page:
 * Try again exists only for a failed stage, and a candidate that did not
 * verify is a stage that finished with that outcome. Requesting changes was
 * the only way on, which runs every stage again, the paid ones included.
 */
describe("a candidate that was not verified, while the review waits", () => {
  it("can be staged again", () => {
    const { onRetry } = staging(failedAt("boot"));

    fireEvent.click(screen.getByRole("button", { name: "Retry staging" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("sends a reader whose tests failed to Testing", () => {
    const { onOpenTesting } = staging(failedAt("test"));

    fireEvent.click(screen.getByRole("button", { name: "Open Testing" }));

    expect(onOpenTesting).toHaveBeenCalledTimes(1);
  });
});

describe("a verified candidate", () => {
  it("is not offered a retry", () => {
    staging(buildDeploySnapshot("p4", "deploy"));

    expect(screen.queryByRole("button", { name: "Retry staging" })).toBeNull();
  });
});
