import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { DeploySnapshot } from "../../api/types";
import { buildDeploySnapshot } from "../../fixtures/buildDeploySnapshot";
import { buildView } from "../../model/view";
import { StageRelease } from "./StageRelease";

afterEach(cleanup);

function renderRelease(snapshot: ReturnType<typeof buildDeploySnapshot>) {
  const onDecideRollback = vi.fn(async () => true);
  render(
    <StageRelease
      view={buildView(snapshot)}
      busy={false}
      isDark={false}
      onDecideRollback={onDecideRollback}
      onReleaseAgain={vi.fn()}
      onLoadHistory={vi.fn(async () => null)}
    />,
  );
  return onDecideRollback;
}

describe("the rollback decision says what happened, and what approving restores", () => {
  it("names a verified release monitoring found down as down, restoring the one before it", () => {
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const down = snapshot.deployments.find((one) => one.state === "awaiting-rollback-approval")!;
    renderRelease(snapshot);

    expect(
      screen.getByText(`Deploy version ${down.deployVersion} is down, and a rollback waits for your decision`),
    ).toBeTruthy();
    expect(
      screen.getByText(new RegExp(`Approving restores deploy version ${snapshot.currentRelease!.deployVersion}`)),
    ).toBeTruthy();
  });

  it("names a cloud release that failed after moving traffic as that, and restores nothing its plan cannot", () => {
    // The first live cloud release stopped at the dispatch with both sites serving
    // the candidate, and the page said it was down and that approving restored
    // deploy version 2, a release on this machine that a cloud rollback cannot use.
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const reason = "the latest verified release ran on the local target, and this release goes to the cloud one";
    const failed = snapshot.deployments.find((one) => one.state === "awaiting-rollback-approval")!;
    const cloud = {
      ...snapshot,
      deployments: snapshot.deployments.map((one) =>
        one.id === failed.id ? { ...one, target: "cloud" as const, verified: false } : one,
      ),
      rollback: snapshot.rollback && {
        ...snapshot.rollback,
        version: failed.deployVersion,
        restorable: false,
        restoreTarget: null,
        unrestorableReason: reason,
      },
    };
    renderRelease(cloud);

    expect(
      screen.getByText(
        `Deploy version ${failed.deployVersion} failed after production traffic may have moved, and a rollback waits for your decision`,
      ),
    ).toBeTruthy();
    expect(screen.getByText(new RegExp(`There is nothing to restore: ${reason}\\.`))).toBeTruthy();
    expect(screen.queryByText(/Approving restores/)).toBeNull();
  });
});

/**
 * The rollback decision was made without what its plan says a restore does to
 * the data, and Approve and Decline were enabled where the server refuses them.
 */
describe("deciding a rollback", () => {
  /** The demo's release found down, with its own run's plan beside it. */
  function down() {
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const awaiting = snapshot.deployments.find((one) => one.state === "awaiting-rollback-approval")!;
    return {
      awaiting,
      snapshot: {
        ...snapshot,
        rollback: snapshot.rollback && { ...snapshot.rollback, version: awaiting.deployVersion },
      },
    };
  }

  it("asks first, saying what a restore does to the data", () => {
    const { awaiting, snapshot } = down();
    const onDecideRollback = renderRelease(snapshot);

    fireEvent.click(screen.getByRole("button", { name: /approve the rollback/i }));

    expect(onDecideRollback).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog").textContent).toMatch(/a restore starts it empty/);
    fireEvent.click(screen.getAllByRole("button", { name: "Approve the rollback" }).at(-1)!);
    expect(onDecideRollback).toHaveBeenCalledWith(awaiting.id, "approved", "");
  });

  it("holds Approve when there is nothing to restore, and Decline until its reason", () => {
    const { snapshot } = down();
    renderRelease({
      ...snapshot,
      currentRelease: null,
      rollback: snapshot.rollback && {
        ...snapshot.rollback,
        restorable: false,
        restoreTarget: null,
        unrestorableReason: "no release was verified before this one",
      },
    });

    const approve = screen.getByRole("button", { name: /approve the rollback/i }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    expect(approve.title).toMatch(/no release was verified before this one/);
    const decline = screen.getByRole("button", { name: "Decline" }) as HTMLButtonElement;
    expect(decline.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/note, required to decline/i), {
      target: { value: "a planned outage" },
    });
    expect(decline.disabled).toBe(false);
  });
});

/** The demo's release, ended as named. */
function releaseThat(state: "compensated" | "succeeded"): DeploySnapshot {
  const snapshot = buildDeploySnapshot("p4", "deploy");
  const [newest, ...rest] = snapshot.deployments;
  if (!newest) throw new Error("the demo has a release");
  return {
    ...snapshot,
    deployments: [
      {
        ...newest,
        kind: "release",
        state,
        verified: state === "succeeded",
        cause: state === "compensated" ? "boot failed. Undone before any traffic moved" : "",
      },
      ...rest,
    ],
  };
}

function release(snapshot: DeploySnapshot) {
  const onReleaseAgain = vi.fn();
  render(
    <StageRelease
      view={buildView(snapshot)}
      busy={false}
      isDark={false}
      onDecideRollback={vi.fn()}
      onReleaseAgain={onReleaseAgain}
      onLoadHistory={vi.fn(async () => null)}
    />,
  );
  return onReleaseAgain;
}

/**
 * A release undone before traffic moved left only a new analysis and a new
 * review of a version already approved.
 */
describe("a release undone before any traffic moved", () => {
  it("can be released again, under the same approval", () => {
    const snapshot = releaseThat("compensated");
    const onReleaseAgain = release(snapshot);

    fireEvent.click(screen.getByRole("button", { name: "Release again" }));

    expect(onReleaseAgain).toHaveBeenCalledWith(snapshot.deployments[0].id);
  });
});

describe("a release that succeeded", () => {
  it("is not offered again", () => {
    release(releaseThat("succeeded"));

    expect(screen.queryByRole("button", { name: "Release again" })).toBeNull();
  });
});

/**
 * The live addresses were plain text, and "Every release and rollback" was the
 * newest ten.
 */
describe("the release's addresses and history", () => {
  it("links where the release serves", () => {
    const snapshot = releaseThat("succeeded");
    release({ ...snapshot, deployments: [{ ...snapshot.deployments[0], url: "http://127.0.0.1:8081" }, ...snapshot.deployments.slice(1)] });

    const link = screen.getByRole("link", { name: "http://127.0.0.1:8081" });
    expect(link.getAttribute("href")).toBe("http://127.0.0.1:8081");
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("says how many attempts there are, and shows them all on request", async () => {
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const [first] = snapshot.deployments;
    const many = Array.from({ length: 12 }, (_, index) => ({ ...first, id: `d-${index}` }));
    const onLoadHistory = vi.fn(async () => many);
    render(
      <StageRelease
        view={buildView({ ...snapshot, deployments: many.slice(0, 10), deploymentsTotal: 12 })}
        busy={false}
        isDark={false}
        onDecideRollback={vi.fn()}
        onReleaseAgain={vi.fn()}
        onLoadHistory={onLoadHistory}
      />,
    );

    expect(screen.getByText(/The newest 10 of 12 releases and rollbacks/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show all 12" }));

    expect(await screen.findByText(/Every release and rollback, newest first/)).toBeTruthy();
    const table = screen.getByRole("table");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(12);
  });
});
