import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { DeploySnapshot } from "../api/types";
import { buildDeploySnapshot, withDerived } from "../fixtures/buildDeploySnapshot";
import { decisionViews } from "../fixtures/rules";
import { buildView } from "../model/view";
import { DecisionBar } from "./DecisionBar";
import { StageReview } from "./stages/StageReview";

/**
 * What the live walkthrough met on a first release. The High update had no
 * verified release to roll back to, so the candidate left it out and the
 * release guard asked nothing about it; the review still asked for a decision
 * on it, and the bar counted "1 decisions owed".
 */
const LEFT_OUT = "a high update needs a verified release to roll back to, and this project has none yet";

function leavingOutTheHigh(): DeploySnapshot {
  const snapshot = buildDeploySnapshot("p4", "deploy");
  const assessments = snapshot.risk?.assessments ?? [];
  const high = assessments.find((one) => one.arbitration.final === "high");
  if (!high || !snapshot.candidate) throw new Error("the demo carries a High update and a candidate");
  const candidate = {
    ...snapshot.candidate,
    included: snapshot.candidate.included.filter((id) => id !== high.updateId),
    excluded: [{ updateId: high.updateId, reason: "no-restore-target" as const, detail: LEFT_OUT }],
  };
  return withDerived({
    ...snapshot,
    candidate,
    decisions: decisionViews(assessments, {}, candidate.included),
  });
}

afterEach(cleanup);

describe("an update the candidate left out, at the review", () => {
  it("says why it is not in this release, and asks nothing of the reviewer", () => {
    const snapshot = leavingOutTheHigh();
    const { container } = render(
      <StageReview
        snapshot={snapshot}
        view={buildView(snapshot)}
        targets={[]}
        busy={false}
        goAhead={false}
        onGoAhead={vi.fn()}
        onDecideUpdate={vi.fn()}
        onChooseTarget={vi.fn()}
        onChoosePolicy={vi.fn()}
        onOpenStage={vi.fn()}
        onOpenTesting={vi.fn()}
      />,
    );

    const card = container.querySelector<HTMLElement>('[data-update-decision="react-router-dom"]');
    if (!card) throw new Error("the High update has a decision card");
    expect(within(card).getByText("not in this release")).toBeTruthy();
    expect(within(card).getByText(`Left out of this candidate: ${LEFT_OUT}.`)).toBeTruthy();
    expect(within(card).queryByText("needs your decision")).toBeNull();
    expect(within(card).queryByRole("button", { name: "Approve" })).toBeNull();
  });
});

describe("the decision bar", () => {
  it("counts one decision owed as one", () => {
    // Nothing stops the release, so the bar shows its count rather than a reason.
    const view = { ...buildView(buildDeploySnapshot("p4", "deploy")), needDecision: 1, blocking: [] };
    render(
      <DecisionBar
        view={view}
        goAhead={false}
        busy={false}
        onApprove={vi.fn()}
        onRequestChanges={vi.fn()}
      />,
    );

    expect(screen.getByText(/1 decision owed/)).toBeTruthy();
    expect(screen.queryByText(/1 decisions owed/)).toBeNull();
  });
});

describe("the cloud target at the review", () => {
  const review = (snapshot: DeploySnapshot) =>
    render(
      <StageReview
        snapshot={snapshot}
        view={buildView(snapshot)}
        targets={[]}
        busy={false}
        goAhead={false}
        onGoAhead={vi.fn()}
        onDecideUpdate={vi.fn()}
        onChooseTarget={vi.fn()}
        onChoosePolicy={vi.fn()}
        onOpenStage={vi.fn()}
        onOpenTesting={vi.fn()}
      />,
    ).container;

  it("names the project's own Vercel project and Render service once the platform made them", () => {
    const snapshot: DeploySnapshot = {
      ...buildDeploySnapshot("p4", "deploy"),
      releaseTarget: "cloud",
      cloud: {
        vercel: { projectId: "prj_1", orgId: "team_1", name: "p4", origin: "https://p4.vercel.app" },
        render: {
          serviceId: "srv-1",
          name: "p4-api",
          origin: "https://p4-api.onrender.com",
          ownerId: "tea-1",
          dashboardUrl: "",
        },
        database: null,
        createdAt: "2026-09-29 10:00",
      },
    };
    const note = review(snapshot).querySelector<HTMLElement>("[data-cloud-resources]");
    if (!note) throw new Error("the review says where a cloud release goes");
    expect(note.textContent).toContain("the Vercel project p4");
    expect(note.textContent).toContain("the Render service p4-api");
    expect(within(note).getByRole("link", { name: "https://p4.vercel.app" })).toBeTruthy();
    expect(within(note).getByRole("link", { name: "https://p4-api.onrender.com" })).toBeTruthy();
    // Without an Atlas connection nothing keeps the records, and the review says so.
    expect(note.querySelector("[data-database]")?.textContent).toMatch(
      /keeps its records in memory, so a restart or a release empties them/,
    );
  });

  describe("where the records are kept", () => {
    const withDatabase = (reads: boolean): DeploySnapshot => {
      const base = buildDeploySnapshot("p4", "deploy");
      if (!base.candidate) throw new Error("the fixture has a candidate");
      return {
        ...base,
        releaseTarget: "cloud",
        candidate: {
          ...base.candidate,
          steps: reads
            ? [
                ...base.candidate.steps,
                {
                  name: "database",
                  command: "docker run mongo",
                  outcome: "passed",
                  durationSeconds: 2,
                  logTail: "",
                },
              ]
            : base.candidate.steps,
        },
        cloud: {
          vercel: { projectId: "prj_1", orgId: "team_1", name: "p4", origin: "https://p4.vercel.app" },
          render: {
            serviceId: "srv-1",
            name: "p4-api",
            origin: "https://p4-api.onrender.com",
            ownerId: "tea-1",
            dashboardUrl: "",
          },
          database: {
            cluster: "Cluster0",
            host: "cluster0.ab1cd.mongodb.net",
            database: "p4",
            username: "app-p4",
            serviceId: "srv-1",
          },
          createdAt: "2026-09-29 10:00",
        },
      };
    };

    it("names the project's database when staging ran the code against one", () => {
      const said = review(withDatabase(true)).querySelector("[data-database]")?.textContent ?? "";
      expect(said).toMatch(/kept in the database p4\s+on the Atlas cluster Cluster0/);
      expect(said).not.toContain("app-p4");
    });

    it("says the code keeps memory when it does not read the database the platform made", () => {
      const said = review(withDatabase(false)).querySelector("[data-database]")?.textContent ?? "";
      expect(said).toMatch(/made its database p4 on the\s+Atlas cluster Cluster0/);
      expect(said).toMatch(/this code keeps its\s+records in memory/);
      expect(said).not.toMatch(/records are kept in the database/);
    });
  });

  it("says the cloud analysis makes them, before it has", () => {
    const snapshot: DeploySnapshot = { ...buildDeploySnapshot("p4", "deploy"), releaseTarget: "cloud" };
    const note = review(snapshot).querySelector<HTMLElement>("[data-cloud-resources]");
    expect(note?.textContent).toMatch(
      /makes this project's own Vercel project, a free Render web service and, when Settings has a MongoDB Atlas connection, its own database/,
    );
  });
});

/**
 * A review note is kept until the decision it carries is accepted.
 *
 * Only the open stage is rendered, and the note lived in its card's state: a
 * reviewer halfway through a High update's note who opened Risk Assessment to
 * check the evidence came back to an empty box.
 */
describe("a review note", () => {
  const snapshot = buildDeploySnapshot("p4", "deploy");
  const highOf = (container: HTMLElement) => {
    const high = buildView(snapshot).updates.find((one) => one.level === "high");
    const card = high && container.querySelector<HTMLElement>(`[data-update-decision="${high.package}"]`);
    if (!card) throw new Error("the demo carries a High update to review");
    return within(card).getByLabelText(/Review note/) as HTMLTextAreaElement;
  };
  const review = (onDecideUpdate: (id: string, decision: string, note: string) => Promise<boolean>) =>
    render(
      <StageReview
        snapshot={snapshot}
        view={{ ...buildView(snapshot), decisionPending: true }}
        targets={[]}
        busy={false}
        goAhead={false}
        onGoAhead={vi.fn()}
        onDecideUpdate={onDecideUpdate}
        onChooseTarget={vi.fn()}
        onChoosePolicy={vi.fn()}
        onOpenStage={vi.fn()}
        onOpenTesting={vi.fn()}
      />,
    );

  it("survives the stage being closed and opened again", () => {
    const first = review(vi.fn(async () => false));
    fireEvent.change(highOf(first.container), {
      target: { value: "Checked the changelog: only the data router changed." },
    });
    first.unmount();

    const again = review(vi.fn(async () => false));

    expect(highOf(again.container).value).toBe("Checked the changelog: only the data router changed.");
  });

  it("stays when the decision is refused, and goes once it is accepted", async () => {
    let accepted = false;
    const onDecideUpdate = vi.fn(async () => accepted);
    const { container } = review(onDecideUpdate);
    const note = highOf(container);
    fireEvent.change(note, { target: { value: "Release notes read; no breaking change we use." } });

    const card = note.closest("li") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Leave out" }));
    await waitFor(() => expect(onDecideUpdate).toHaveBeenCalledTimes(1));
    expect(note.value).toBe("Release notes read; no breaking change we use.");

    accepted = true;
    fireEvent.click(within(card).getByRole("button", { name: "Leave out" }));
    await waitFor(() => expect(note.value).toBe(""));
  });
});

/**
 * The release guard said the candidate was not verified in staging and left
 * the reader to find the stage where that can be tried again.
 */
describe("a review blocked by an unverified candidate", () => {
  it("opens Staging Verification from the blocker", () => {
    const snapshot = {
      ...buildDeploySnapshot("p4", "deploy"),
      blocking: [{ code: "G3", message: "the candidate was not verified in staging: its test step failed", updateId: null }],
    };
    const onOpenStage = vi.fn();
    render(
      <StageReview
        snapshot={snapshot}
        view={buildView(snapshot)}
        targets={[]}
        busy={false}
        goAhead={false}
        onGoAhead={vi.fn()}
        onDecideUpdate={vi.fn()}
        onChooseTarget={vi.fn()}
        onChoosePolicy={vi.fn()}
        onOpenStage={onOpenStage}
        onOpenTesting={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Go to Staging Verification" }));

    expect(onOpenStage).toHaveBeenCalledWith("staging-verification");
  });
});
