import type {
  Blocker,
  DeploySnapshot,
  RiskLevel,
  UpdateAssessment,
  UpdateDecisionView,
} from "../api/types";

/**
 * The orchestrator's rules for this phase, as the fixtures answer them.
 *
 * The demo has to refuse exactly what the server refuses, in the server's
 * words, or the page learns to rely on something the flag flip takes away:
 * a High approval the demo accepted without a note would be a button that
 * works until the day it matters. So these are the server's rules, written
 * again here and nowhere else in the browser. The page never decides whether
 * a release may go ahead; it shows `blocking`, which the server computes and
 * which this computes in its place.
 *
 * The sources, for when one of them changes: `api/deployment.py`
 * (`decide_update`, `submit_decision`, `decide_rollback`) and
 * `deploy/guards.py` (`release_blockers`, `still_counts`) in the orchestrator.
 */

const ORDER: Record<RiskLevel, number> = { low: 0, medium: 1, high: 2 };

const capitalised = (level: string) => level.charAt(0).toUpperCase() + level.slice(1);

/** A decision counts unless the update's level has risen above the one it was taken at. */
export function stillCounts(atDecision: RiskLevel | null | undefined, now: RiskLevel): boolean {
  return atDecision != null && ORDER[atDecision] >= ORDER[now];
}

/** A decision a person recorded about one update, before the read model shapes it. */
export type UpdateDecisionRecord = {
  decision: "approved" | "rejected" | "deferred";
  by: string;
  at: string;
  note: string;
  levelAtDecision: RiskLevel;
};

/**
 * The read model's `decisions`: one view per assessed update, and whether one is owed.
 *
 * Owed where the release guard asks for one (G1): on a Medium or High update the
 * candidate carries. `included` is the candidate's list, empty with no candidate.
 */
export function decisionViews(
  assessments: readonly UpdateAssessment[],
  recorded: Readonly<Record<string, UpdateDecisionRecord>>,
  included: readonly string[],
): UpdateDecisionView[] {
  const carried = new Set(included);
  return assessments.map((assessment) => {
    const final = assessment.arbitration.final as RiskLevel;
    const record = recorded[assessment.updateId];
    const counts = record !== undefined && stillCounts(record.levelAtDecision, final);
    return {
      updateId: assessment.updateId,
      decision: counts ? record.decision : null,
      by: counts ? record.by : null,
      at: counts ? record.at : null,
      note: counts ? record.note || null : null,
      levelAtDecision: counts ? record.levelAtDecision : null,
      needsDecision: final !== "low" && !counts && carried.has(assessment.updateId),
      needsReviewNote: final === "high",
    };
  });
}

/** `decide_update`'s refusals: a High approval and any rejection carry a note. */
export function updateDecisionRefusal(
  level: RiskLevel,
  decision: UpdateDecisionRecord["decision"],
  note: string,
): string | null {
  if (decision === "approved" && level === "high" && !note.trim()) {
    return "approving a High update needs a review note (manual review, FR17)";
  }
  if (decision === "rejected" && !note.trim()) {
    return "leaving an update out needs a note saying why";
  }
  return null;
}

type ReleaseFacts = {
  /** The go ahead a cloud release needs, from the decision itself. */
  goAhead: boolean;
  /** Whether this orchestrator allows cloud releases at all. The demo's does not. */
  cloudEnabled: boolean;
  /** The providers a cloud release needs a working connection to. */
  connected: ReadonlySet<string>;
};

const CLOUD_PROVIDERS = ["github", "vercel", "render"] as const;

/**
 * The release guards, G1 to G6, over what the pending review would approve.
 *
 * In the order the orchestrator checks them and with its messages, so a
 * refusal reads the same whichever side answered.
 */
export function releaseBlockers(snapshot: DeploySnapshot, facts: ReleaseFacts): Blocker[] {
  const blockers: Blocker[] = [];
  const assessments = snapshot.risk?.assessments ?? [];
  const byId = new Map(assessments.map((one) => [one.updateId, one]));
  const levelOf = (updateId: string) =>
    (byId.get(updateId)?.arbitration.final ?? "high") as RiskLevel;
  const keyOf = (updateId: string) => byId.get(updateId)?.key ?? updateId;
  const decided = new Map(snapshot.decisions.map((one) => [one.updateId, one]));
  const candidate = snapshot.candidate;
  const rollback = snapshot.rollback;
  const included = candidate?.included ?? [];

  // G1: Medium and High need a person, at the level they have now.
  for (const updateId of included) {
    const level = levelOf(updateId);
    if (level === "low") continue;
    const decision = decided.get(updateId);
    if (!decision?.decision) {
      blockers.push({
        code: "G1",
        message: `${keyOf(updateId)} is ${capitalised(level)} and needs a person's approval`,
        updateId,
      });
    } else if (decision.decision === "approved" && level === "high" && !decision.note) {
      blockers.push({
        code: "G1",
        message: `${keyOf(updateId)} is High, and its approval carries no review note`,
        updateId,
      });
    }
  }

  // G2: a High update ships only with a rollback prepared for it.
  const high = included.filter((updateId) => levelOf(updateId) === "high");
  if (high.length > 0) {
    if (!rollback) {
      blockers.push({ code: "G2", message: "there is no rollback plan for this candidate", updateId: null });
    } else if (candidate && rollback.candidateHash !== candidate.candidateHash) {
      blockers.push({
        code: "G2",
        message: "the rollback plan was written for another candidate",
        updateId: null,
      });
    } else {
      for (const item of rollback.updates) {
        if (high.includes(item.updateId) && item.status === "unavailable") {
          blockers.push({
            code: "G2",
            message:
              `${keyOf(item.updateId)} is High and its rollback is unavailable: ` +
              (item.reason || rollback.unrestorableReason),
            updateId: item.updateId,
          });
        }
      }
    }
  }

  // G3: what ships is what was verified, and what the review left out is out.
  if (!candidate) {
    blockers.push({ code: "G3", message: "no release candidate was built", updateId: null });
  } else {
    if (!candidate.verified) {
      const failed = candidate.steps.find((step) => ["failed", "timed-out"].includes(step.outcome));
      const why = failed
        ? `its ${failed.name} step failed`
        : candidate.fingerprint !== candidate.candidateHash
          ? "it did not serve its own fingerprint"
          : "a smoke request did not answer";
      blockers.push({
        code: "G3",
        message: `the candidate was not verified in staging: ${why}`,
        updateId: null,
      });
    }
    for (const updateId of included) {
      const decision = decided.get(updateId);
      if (decision?.decision === "rejected" || decision?.decision === "deferred") {
        blockers.push({
          code: "G3",
          message:
            `${keyOf(updateId)} was ${decision.decision} at review and the candidate still ` +
            "carries it: request changes to rebuild without it",
          updateId,
        });
      }
    }
  }

  // G4: the tests that justify this release still hold.
  if (snapshot.approvedTestVersion < snapshot.testVersion || snapshot.testVersion === 0) {
    blockers.push({
      code: "G4",
      message: `test version ${snapshot.testVersion} is not approved, so nothing may ship`,
      updateId: null,
    });
  } else if (snapshot.codeMovedOn) {
    blockers.push({
      code: "G4",
      message:
        `the approved tests measured code version ${snapshot.deployedCodeVersion} and the ` +
        `code is now version ${snapshot.codeVersion}`,
      updateId: null,
    });
  }

  // G5: the cloud is opt in, connected, and asked for each time.
  if (snapshot.releaseTarget === "cloud") {
    if (!facts.cloudEnabled) {
      blockers.push({
        code: "G5",
        message: "cloud releases are turned off on this orchestrator",
        updateId: null,
      });
    }
    for (const provider of CLOUD_PROVIDERS) {
      if (!facts.connected.has(provider)) {
        blockers.push({
          code: "G5",
          message: `there is no working ${provider} connection`,
          updateId: null,
        });
      }
    }
    if (!facts.goAhead) {
      blockers.push({
        code: "G5",
        message:
          "a cloud release spends provider minutes, so the decision must carry the go ahead",
        updateId: null,
      });
    }
  }
  // G6: the release goes where its plan was made for; the plan's steps name the
  // adapters that carry it out, so a target changed at the review is replanned.
  const planned = snapshot.plan?.target;
  if (planned && planned !== snapshot.releaseTarget) {
    blockers.push({
      code: "G6",
      message:
        `this version was planned for the ${planned} target, not the ${snapshot.releaseTarget} ` +
        `target chosen now: request changes, and the next version is planned for ` +
        snapshot.releaseTarget,
      updateId: null,
    });
  }
  return blockers;
}
