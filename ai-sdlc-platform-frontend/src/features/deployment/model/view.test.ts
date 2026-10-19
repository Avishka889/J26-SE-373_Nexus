import { describe, expect, it } from "vitest";
import type { DeploySnapshot } from "../api/types";
import { buildDeploySnapshot, withDerived } from "../fixtures/buildDeploySnapshot";
import { decisionViews } from "../fixtures/rules";
import {
  GO_AHEAD_BLOCKER,
  approval,
  buildView,
  deploymentTranscript,
  reviewMovedPastLine,
  stageToOpen,
} from "./view";
import { buildDeploymentConversation } from "./conversation";

const seeded = (): DeploySnapshot => buildDeploySnapshot("p4", "deploy");

describe("the updates, as a reviewer reads them", () => {
  it("puts the most cautious first", () => {
    const levels = buildView(seeded()).updates.map((one) => one.level);
    expect(levels).toEqual(["high", "medium", "medium", "low", "low", "low"]);
  });

  it("carries the verified quotes the changelog vote cites, beside the files", () => {
    const [high] = buildView(seeded()).updates;
    expect(high.package).toBe("react-router-dom");
    expect(high.decidedBy).toEqual(["Changelog"]);
    expect(high.quotes.map((one) => one.kind)).toContain("breaking");
    expect(high.quotes.some((one) => one.quote.includes("CSRF"))).toBe(true);
    // The study found no file of the generated application using a changed
    // symbol, and the view says none rather than inventing one.
    expect(high.files).toEqual([]);
    expect(high.usage?.importsPackage).toBe(true);
  });

  it("says why an explanation is the rule's", () => {
    const [high] = buildView(seeded()).updates;
    expect(high.explanationSource).toBe("rule");
    expect(high.explanationNote).toBe("the demo does not ask a model");
  });
});

describe("what the page asks of the reader", () => {
  it("waits on a review with three decisions owed, and the guards say why", () => {
    const view = buildView(seeded());
    expect(view.decisionPending).toBe(true);
    expect(view.decided).toBeNull();
    expect(view.needDecision).toBe(3);
    expect(view.blocking).toHaveLength(3);
    expect(view.steps["deployment-review"]).toMatchObject({ state: "waiting", count: 3 });
  });

  it("stops waiting once the version is decided", () => {
    const decided = withDerived({
      ...seeded(),
      gate: {
        decision: { kind: "approved", by: "Alex Chen", at: "2026-09-24 10:00", note: null, version: 3 },
        history: [],
      },
    });
    const view = buildView(decided);
    expect(view.decisionPending).toBe(false);
    expect(view.steps["deployment-review"]).toEqual({ state: "done", hint: "approved" });
  });

  it("does not ask for a decision while a run is analysing", () => {
    const snapshot = seeded();
    snapshot.stages["risk-assessment"] = { ...snapshot.stages["risk-assessment"], status: "generating" };
    const view = buildView(snapshot);
    expect(view.running).toBe(true);
    expect(view.decisionPending).toBe(false);
    expect(view.steps["deployment-review"].hint).toBe("waits for the run");
  });

  it("opens where it is needed most: a release down in production first", () => {
    expect(stageToOpen(buildView(seeded()))).toBe("release");
    const recovered = withDerived({
      ...seeded(),
      deployments: seeded().deployments.map((one) =>
        one.state === "awaiting-rollback-approval" ? { ...one, state: "rolled-back" } : one,
      ),
    });
    expect(stageToOpen(buildView(recovered))).toBe("deployment-review");
  });

  it("shows a first run in flight, though the server's version is still zero", () => {
    // What the live walkthrough met: the version counts reports written, so a
    // first run reads as version 0 until detection writes its report, and the
    // page used to take that for a phase nobody had started.
    const first = buildDeploySnapshot("p4", "deploy");
    const running = withDerived({
      ...first,
      deployVersion: 0,
      deployments: [],
      risk: null,
      stages: Object.fromEntries(
        Object.entries(first.stages).map(([id, stage]) => [
          id,
          { ...stage, status: id === "dependency-updates" ? "generating" : "pending", generatedFromVersion: 0 },
        ]),
      ) as DeploySnapshot["stages"],
    });
    const view = buildView(running);
    expect(view.empty).toBeNull();
    expect(view.running).toBe(true);
  });

  it("owes no decision on an update the candidate left out, and says why it is out", () => {
    // A High update on a first release has nothing to roll back to, so the
    // candidate leaves it out and the release guard asks nothing about it.
    const snapshot = seeded();
    const assessments = snapshot.risk?.assessments ?? [];
    const high = assessments.find((one) => one.arbitration.final === "high");
    if (!high || !snapshot.candidate) throw new Error("the demo carries a High update and a candidate");
    const candidate = {
      ...snapshot.candidate,
      included: snapshot.candidate.included.filter((id) => id !== high.updateId),
      excluded: [
        { updateId: high.updateId, reason: "no-restore-target" as const, detail: "nothing to restore to" },
      ],
    };
    const view = buildView(
      withDerived({ ...snapshot, candidate, decisions: decisionViews(assessments, {}, candidate.included) }),
    );
    const left = view.updates.find((one) => one.updateId === high.updateId);
    expect(left).toMatchObject({ included: false, leftOut: "nothing to restore to" });
    expect(left?.decision?.needsDecision).toBe(false);
    // The two Medium updates the candidate carries are the decisions still owed.
    expect(view.needDecision).toBe(2);
  });

  it("has nothing to show before the test review approves", () => {
    const view = buildView(buildDeploySnapshot("p1", "testing"));
    expect(view.empty).toBe("not-approved");
    expect(Object.values(view.chevrons).every((one) => one === "future")).toBe(true);
  });
});

describe("release and monitoring come from the ledger, not from stage rows", () => {
  it("shows the release stage whenever there is a history, and red while a rollback waits", () => {
    const view = buildView(seeded());
    expect(view.stages.release.status).toBe("complete");
    expect(view.chevrons.release).toBe("failed");
    expect(view.steps.release.hint).toBe("deploy version 2 is down, a rollback waits on you");
    expect(view.release.serving?.deployVersion).toBe(1);
  });

  it("shows an approved release being written down as working, not as never run", () => {
    // What Book Tracker's first cloud release met: the approval answered before
    // the run wrote the release, and the page called the stage not run yet.
    const approved = {
      ...seeded(),
      deployments: [],
      currentRelease: null,
      stages: {
        ...seeded().stages,
        release: { ...seeded().stages.release, status: "generating" as const },
      },
    };
    const view = buildView(approved);
    expect(view.stages.release.status).toBe("generating");
    expect(view.chevrons.release).toBe("generating");
    expect(buildView({ ...approved, stages: seeded().stages }).stages.release.status).toBe(
      "pending",
    );
  });

  it("does not report a replaced release's window as the state of what serves now", () => {
    const view = buildView(seeded());
    expect(view.monitoring.watched?.deployVersion).toBe(2);
    expect(view.monitoring.watchesServing).toBe(false);
    expect(view.steps.monitoring.hint).toBe("the serving release has not been watched");
  });

  it("will not open a second window on what serves, and says a window is watching it", () => {
    // What the live walkthrough met: the orchestrator opens a window on release,
    // and a page that did not know offered to open another, which is refused.
    const serving = withDerived({
      ...seeded(),
      deployments: seeded().deployments.filter((one) => one.state !== "awaiting-rollback-approval"),
    });
    expect(buildView(serving).monitoring.canWatch).toBe(true);

    const [release] = serving.deployments;
    const monitoring = buildView({ ...serving, watching: release.id }).monitoring;
    expect(monitoring.canWatch).toBe(false);
    expect(monitoring.watchingNow?.id).toBe(release.id);
    expect(monitoring.cannotWatch).toBe(
      `Deploy version ${release.deployVersion} is being watched now, and its report replaces ` +
        "the one below when the window closes.",
    );
  });

  it("will not open a window while the newest release waits on a rollback decision", () => {
    const view = buildView(seeded());
    expect(view.monitoring.canWatch).toBe(false);
    expect(view.monitoring.cannotWatch).toMatch(/waits on a rollback decision/);
  });

  it("writes only a deployment's finished steps to the console", () => {
    const [running] = seeded().deployments;
    const lines = deploymentTranscript({
      ...running,
      state: "running",
      steps: running.steps.map((step, index) => ({
        ...step,
        state: index === 0 ? "succeeded" : index === 1 ? "running" : "pending",
      })),
    });
    const commands = lines.filter((one) => one.kind === "cmd");
    expect(commands).toHaveLength(1);
    expect(lines.at(-1)?.kind).toBe("pass");
  });
});

describe("the conversation", () => {
  it("opens the stage each message belongs to, and tells a person's decision from the platform", () => {
    const opened: string[] = [];
    const messages = buildDeploymentConversation({
      snapshot: seeded(),
      onOpenStage: (id) => opened.push(id),
    });
    expect(messages.map((one) => one.chip)).toContain("Monitoring");
    const approval = messages.find((one) => one.content === "Approved deploy version 2.");
    expect(approval?.role).toBe("user");
    const down = messages.find((one) => one.content.startsWith("Monitoring found"));
    expect(down?.role).toBe("system");
    down?.onOpen?.();
    expect(opened).toEqual(["monitoring"]);
  });
});

describe("a cloud release's go ahead", () => {
  const goAhead = { code: "G5", message: GO_AHEAD_BLOCKER, updateId: null };

  it("is the one guard a person clears by deciding", () => {
    const view = buildView({ ...seeded(), blocking: [goAhead] });
    expect(approval(view, false)).toMatchObject({ disabled: true, asksForGoAhead: true });
    expect(approval(view, false).reason).toMatch(/must carry the go ahead/);
    expect(approval(view, true)).toEqual({ disabled: false, reason: "", asksForGoAhead: true });
  });

  it("clears nothing else: a cloud switch that is off still stops the release", () => {
    const off = { code: "G5", message: "cloud releases are turned off on this orchestrator", updateId: null };
    const view = buildView({ ...seeded(), blocking: [off, goAhead] });
    const state = approval(view, true);
    expect(state.disabled).toBe(true);
    expect(state.reason).toBe(
      "1 thing stops this release: cloud releases are turned off on this orchestrator",
    );
  });

  it("is not asked for on the local target", () => {
    expect(approval(buildView(seeded()), false).asksForGoAhead).toBe(false);
  });
});

/**
 * A first release has nothing earlier to restore, and the rollback stage read
 * as needing attention on every one: a finished project stayed at 80%.
 */
describe("a rollback plan with nothing to restore", () => {
  function withPlan(statuses: ("not-required" | "unavailable")[]) {
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const rollback = snapshot.rollback!;
    return buildView({
      ...snapshot,
      rollback: {
        ...rollback,
        restorable: false,
        restoreTarget: null,
        unrestorableReason: "this project has no verified release yet, so there is nothing to return to",
        updates: rollback.updates.slice(0, statuses.length).map((one, index) => ({
          ...one,
          status: statuses[index],
        })),
      },
    });
  }

  it("is done when nothing in the release needed it", () => {
    expect(withPlan(["not-required"]).steps["rollback-planning"]).toMatchObject({
      state: "done",
      hint: "nothing to restore",
    });
  });

  it("needs attention when an update needed a prepared rollback", () => {
    expect(withPlan(["unavailable"]).steps["rollback-planning"].state).toBe("attention");
  });
});

/**
 * A review waiting while the code moved on is of an analysis of code that is
 * no longer current: its approval is refused, requesting changes there is
 * refused, and analysing again, once the current code's tests are approved,
 * closes it.
 */
describe("a review the code has moved past", () => {
  function waiting(fields: Partial<DeploySnapshot> = {}): DeploySnapshot {
    const base = seeded();
    return {
      ...base,
      gate: { ...base.gate, decision: null },
      stages: {
        ...base.stages,
        "deployment-review": {
          ...base.stages["deployment-review"],
          status: "complete",
          generatedFromVersion: base.deployVersion,
        },
      },
      ...fields,
    };
  }
  // Newer code, as the server reads it: stale once its tests are approved.
  const moved = (tested: "current" | "older"): Partial<DeploySnapshot> => {
    const analysed = seeded().deployedCodeVersion;
    return {
      codeVersion: analysed + 1,
      codeMovedOn: tested === "current",
      approvedTestedCodeVersion: tested === "current" ? analysed + 1 : analysed,
    };
  };

  it("is one when newer code was tested while it waited", () => {
    const view = buildView(waiting(moved("current")));

    expect(view.decisionPending).toBe(true);
    expect(view.reviewMovedPast).toBe(true);
    expect(view.codeAwaitingTests).toBe(0);
  });

  it("is not one while the newer code waits for its tests: the analysed code may ship", () => {
    const view = buildView(waiting(moved("older")));

    expect(view.reviewMovedPast).toBe(false);
    expect(view.codeAwaitingTests).toBe(seeded().deployedCodeVersion + 1);
  });

  it("is not one while the code is the code it analysed", () => {
    const view = buildView(waiting());

    expect(view.decisionPending).toBe(true);
    expect(view.reviewMovedPast).toBe(false);
  });

  it("says which code has approved tests now, and to analyse again", () => {
    const tested = waiting(moved("current"));
    const newer = seeded().deployedCodeVersion + 1;

    expect(reviewMovedPastLine(tested)).toContain(`code version ${newer} has approved tests now`);
    expect(reviewMovedPastLine(tested)).toContain(
      `Analyse the updates again to analyse version ${newer}`,
    );
  });
});
