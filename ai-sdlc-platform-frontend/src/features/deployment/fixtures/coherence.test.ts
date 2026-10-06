import { beforeEach, describe, expect, it } from "vitest";
import { DEPLOY_STAGE_IDS } from "@/types/project";
import type { DeploySnapshot, RiskLevel, UpdateAssessment } from "../api/types";
import { createDeploymentApi } from "../api/createDeploymentApi";
import { buildDeploySnapshot } from "./buildDeploySnapshot";
import { resetDeployDb } from "./deployDb";

/**
 * The demo holds to the rules the server enforces.
 *
 * Every assertion here is written from the rule, not from the builder, so a
 * fixture edited by hand (or a generator that drifted) fails here before the
 * page learns to render a level the server would refuse. The rules are FR6
 * and FR7 (the most cautious vote wins), NFR10 (disagreement is said), FR17
 * and FR18 (manual review and a prepared rollback exactly for High), NFR11
 * (the evidence a vote cites is in the assessment), and FR20 (no rollback
 * without a person's decision).
 */

const ORDER: Record<RiskLevel, number> = { low: 0, medium: 1, high: 2 };
const STRATEGY: Record<RiskLevel, string> = {
  low: "automatic",
  medium: "approval",
  high: "approval-with-rollback",
};

const awaiting = (): DeploySnapshot => buildDeploySnapshot("p4", "deploy");
const assessments = (): UpdateAssessment[] => awaiting().risk?.assessments ?? [];

describe("each assessment is the rules' own", () => {
  it("has one High, two Medium and three Low updates", () => {
    const levels = assessments().map((one) => one.arbitration.final).sort();
    expect(levels).toEqual(["high", "low", "low", "low", "medium", "medium"]);
  });

  it("takes the most cautious vote cast, decided by the signals that cast it", () => {
    for (const assessment of assessments()) {
      const cast = assessment.votes.filter((vote) => vote.level !== null);
      const highest = cast.reduce<RiskLevel | null>(
        (top, vote) =>
          top === null || ORDER[vote.level as RiskLevel] > ORDER[top] ? (vote.level as RiskLevel) : top,
        null,
      );
      expect(assessment.arbitration.final).toBe(highest ?? "high");
      expect(assessment.arbitration.decidedBy).toEqual(
        cast.filter((vote) => vote.level === highest).map((vote) => vote.signal),
      );
    }
  });

  it("says so exactly when the signals disagree or none voted", () => {
    for (const assessment of assessments()) {
      const cast = new Set(assessment.votes.map((vote) => vote.level).filter(Boolean));
      const owed = cast.size !== 1;
      expect(Boolean(assessment.arbitration.advisory.trim()), assessment.key).toBe(owed);
      expect(assessment.disagreement).toBe(cast.size > 1);
    }
  });

  it("asks for manual review and a prepared rollback exactly when High", () => {
    for (const assessment of assessments()) {
      const level = assessment.arbitration.final as RiskLevel;
      expect(assessment.strategy.deploy).toBe(STRATEGY[level]);
      expect(assessment.strategy.manualReviewRequired).toBe(level === "high");
      expect(assessment.strategy.rollbackRequired).toBe(level === "high");
    }
  });

  it("carries every piece of evidence a vote cites", () => {
    for (const assessment of assessments()) {
      const known = new Set(assessment.evidence.map((item) => item.id));
      for (const vote of assessment.votes) {
        for (const cited of vote.evidenceIds) expect(known.has(cited), cited).toBe(true);
      }
    }
  });

  it("quotes only claims the changelog signal verified for that update", () => {
    const snapshot = awaiting();
    for (const analysis of snapshot.changelog?.perUpdate ?? []) {
      const assessment = snapshot.risk?.assessments.find((one) => one.updateId === analysis.updateId);
      const claimIds = new Set(analysis.claims.map((claim) => claim.id));
      const cited = assessment?.votes.find((vote) => vote.signal === "changelog")?.evidenceIds ?? [];
      for (const id of cited) expect(claimIds.has(id)).toBe(true);
    }
  });
});

describe("the release in review is the one that was built and planned", () => {
  it("builds one candidate over the assessed updates, and plans it", () => {
    const snapshot = awaiting();
    const ids = assessments().map((one) => one.updateId).sort();
    expect([...(snapshot.candidate?.included ?? [])].sort()).toEqual(ids);
    expect(snapshot.candidate?.verified).toBe(true);
    expect(snapshot.pipeline?.candidateHash).toBe(snapshot.candidate?.candidateHash);
    expect(snapshot.plan?.candidateHash).toBe(snapshot.candidate?.candidateHash);
  });

  it("prepares a rollback for every High update, to a release that is not the candidate", () => {
    const snapshot = awaiting();
    const rollback = snapshot.rollback;
    expect(rollback?.candidateHash).toBe(snapshot.candidate?.candidateHash);
    expect(rollback?.restorable).toBe(true);
    expect(rollback?.restoreTarget?.candidateHash).not.toBe(snapshot.candidate?.candidateHash);
    for (const assessment of assessments()) {
      if (assessment.arbitration.final !== "high") continue;
      expect(rollback?.updates.find((one) => one.updateId === assessment.updateId)?.status).toBe(
        "prepared",
      );
    }
  });

  it("restores to what serves now: the verified release before the one that went down", () => {
    const snapshot = awaiting();
    const serving = snapshot.deployments.find((one) => one.id === snapshot.currentRelease?.deploymentId);
    expect(serving?.state).toBe("succeeded");
    expect(serving?.verified).toBe(true);
    expect(snapshot.rollback?.restoreTarget?.deploymentId).toBe(serving?.id);
  });
});

describe("the phase itself", () => {
  it("has all ten stages, each failing only with a reason and skipping only with one", () => {
    const snapshot = awaiting();
    expect(Object.keys(snapshot.stages).sort()).toEqual([...DEPLOY_STAGE_IDS].sort());
    for (const stage of Object.values(snapshot.stages)) {
      expect(stage.status === "failed").toBe(Boolean(stage.error));
      if (stage.status === "skipped") expect(stage.summary?.trim()).toBeTruthy();
    }
  });

  it("waits on a person for the High and both Medium updates, and on nothing else", () => {
    const snapshot = awaiting();
    const owed = snapshot.decisions.filter((one) => one.needsDecision).map((one) => one.updateId);
    const aboveLow = assessments()
      .filter((one) => one.arbitration.final !== "low")
      .map((one) => one.updateId);
    expect(owed.sort()).toEqual(aboveLow.sort());
    expect(snapshot.blocking.map((one) => one.code)).toEqual(["G1", "G1", "G1"]);
  });

  it("shows a release that went down as waiting on a rollback decision, and none started", () => {
    const snapshot = awaiting();
    expect(snapshot.rollbackPending).toBe(true);
    expect(snapshot.deployments.some((one) => one.kind === "rollback")).toBe(false);
  });

  it("stops waiting on a rollback decision once one is declined", async () => {
    resetDeployDb();
    const down = awaiting().deployments.find((one) => one.state === "awaiting-rollback-approval")!;
    const after = await createDeploymentApi().decideRollback("p4", down.id, {
      decision: "rejected",
      by: "Alex Chen",
      note: "A cold start, not an outage.",
    });
    // Verified before monitoring flagged it, so it serves on.
    expect(after.deployments.find((one) => one.id === down.id)?.state).toBe("succeeded");
    expect(after.rollbackPending).toBe(false);
  });

  it("names where every monitoring number came from, and ends in the state it reports", () => {
    const monitoring = awaiting().monitoring;
    expect(monitoring?.source).toMatch(/probes every 30 s/);
    expect(monitoring?.states.at(-1)?.state).toBe(monitoring?.currentState);
  });

  it("has nothing to deploy before the test review approves", () => {
    const snapshot = buildDeploySnapshot("p1", "testing");
    expect(snapshot.deployVersion).toBe(0);
    expect(snapshot.approvedTestVersion).toBe(0);
    expect(snapshot.risk).toBeNull();
    expect(snapshot.blocking).toEqual([]);
  });
});

describe("the demo refuses what the server refuses", () => {
  beforeEach(() => resetDeployDb());

  const api = createDeploymentApi();
  const high = () => assessments().find((one) => one.arbitration.final === "high")!;
  const mediums = () => assessments().filter((one) => one.arbitration.final === "medium");

  it("approving a High update without a review note", async () => {
    await expect(
      api.decideUpdate("p4", high().updateId, { decision: "approved", by: "Alex Chen" }),
    ).rejects.toThrow("approving a High update needs a review note (manual review, FR17)");
  });

  it("leaving an update out without saying why", async () => {
    await expect(
      api.decideUpdate("p4", mediums()[0].updateId, { decision: "rejected", by: "Alex Chen" }),
    ).rejects.toThrow("leaving an update out needs a note saying why");
  });

  it("approving the release while decisions are owed, naming each", async () => {
    await expect(
      api.submitDecision("p4", { kind: "approved", by: "Alex Chen" }),
    ).rejects.toThrow(/release guards refuse this approval: .*needs a person's approval/);
  });

  it("declining a rollback without saying why", async () => {
    const down = awaiting().deployments.find((one) => one.state === "awaiting-rollback-approval")!;
    await expect(
      api.decideRollback("p4", down.id, { decision: "rejected", by: "Alex Chen" }),
    ).rejects.toThrow("declining a rollback needs a note saying why");
  });

  it("releasing to a target the version was not planned for", async () => {
    // The plan names the adapters that carry a release out, so a target switched
    // at the review would record one target and carry out the other's plan.
    await api.chooseTarget("p4", "cloud", "Alex Chen");
    await expect(
      api.submitDecision("p4", { kind: "approved", by: "Alex Chen", goAhead: true }),
    ).rejects.toThrow(
      "this version was planned for the local target, not the cloud target chosen now: " +
        "request changes, and the next version is planned for cloud",
    );
  });

  it("starting a run before testing approved anything", async () => {
    await expect(api.run("p1")).rejects.toThrow(/test review has not approved anything/);
  });

  it("and lets the release through once every decision it needs is taken", async () => {
    await api.decideUpdate("p4", high().updateId, {
      decision: "approved",
      by: "Alex Chen",
      note: "Checked the CSRF change: the app sets no reverse proxy host.",
    });
    for (const medium of mediums()) {
      await api.decideUpdate("p4", medium.updateId, { decision: "approved", by: "Alex Chen" });
    }
    const released = await api.submitDecision("p4", { kind: "approved", by: "Alex Chen" });
    expect(released.gate.decision?.kind).toBe("approved");
    expect(released.deployments[0]).toMatchObject({ kind: "release", deployVersion: 3 });
    expect(released.blocking).toEqual([]);
  });
});
