import { describe, expect, it } from "vitest";
import { DEPLOY_STAGE_IDS } from "@/types/project";
import type { DeploySnapshot } from "../api/types";
import { buildDeploySnapshot } from "../fixtures/buildDeploySnapshot";
import { deploymentPollMs } from "./useDeploymentPage";

type Run = NonNullable<DeploySnapshot["run"]>;

const RUN: Run = {
  id: "run-1",
  state: "running",
  version: 1,
  startedAt: "2026-10-17T18:40:00Z",
  finishedAt: null,
  error: null,
  stoppedAt: null,
  model: null,
  thinking: null,
};

/**
 * Every stage up to the review finished, the review not yet open, no release
 * being carried out and no monitoring window running.
 */
function finishing(state: Run["state"] | null): DeploySnapshot {
  const base = buildDeploySnapshot("p4", "deploy");
  const review = DEPLOY_STAGE_IDS.indexOf("deployment-review");
  const stages = Object.fromEntries(
    DEPLOY_STAGE_IDS.map((id, index) => [
      id,
      { ...base.stages[id], status: index < review ? "complete" : "pending" },
    ]),
  ) as DeploySnapshot["stages"];
  return {
    ...base,
    stages,
    deployments: [],
    watching: null,
    run: state ? { ...RUN, state } : null,
  };
}

describe("how often the deployment phase is read", () => {
  // Between Rollback Planning finishing and the review opening nothing was
  // generating, so the page stopped asking just before the review opened.
  it("keeps asking while the run opens the review, with nothing generating", () => {
    expect(deploymentPollMs(finishing("running"))).toBe(1200);
    expect(deploymentPollMs(finishing("queued"))).toBe(1200);
  });

  it("stops once the review is open, with nothing released and no window running", () => {
    expect(deploymentPollMs(finishing("awaiting_gate"))).toBe(false);
    expect(deploymentPollMs(finishing(null))).toBe(false);
  });

  it("still asks while a monitoring window runs, at the window's pace", () => {
    // The server names the release it watches.
    expect(deploymentPollMs({ ...finishing("awaiting_gate"), watching: "d-1" })).toBe(5000);
  });
});
