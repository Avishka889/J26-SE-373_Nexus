import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { StageCodeReview } from "./StageCodeReview";
import { CODE_STAGE_IDS } from "@/types/project";
import { fireEvent } from "@testing-library/react";
import type { CodeChanges, CodeSnapshot, CodeStages, PreviewState } from "../../api/types";

/**
 * The preview row on the review page, in the states fixtures cannot produce.
 *
 * A preview is a process on the server, so the fixture branch answers
 * `unavailable` and always will: there is nothing running behind it. That
 * leaves every other state, which is most of them, reachable only from a live
 * backend and therefore untestable end to end. Stubbing the one hook that
 * reads the process is what makes them testable at all, and each assertion
 * below is about what a reviewer is told rather than about how it looks.
 */

let preview: PreviewState = { status: "none" };
let changes: CodeChanges | undefined;

vi.mock("../../hooks/useCode", () => ({
  usePreview: () => ({ data: preview }),
  useCodeChanges: () => ({ data: changes }),
}));

afterEach(cleanup);

/** The version under review, and the only number these assertions turn on. */
const CODE_VERSION = 3;

/**
 * Built here rather than taken from the fixtures, which live behind the api
 * seam and are not a component's to reach for. Nothing below reads a field
 * this leaves empty, and a snapshot with nothing in it makes the preview row
 * the only thing under test.
 */
function snapshot(built: boolean): CodeSnapshot {
  const stages = Object.fromEntries(
    CODE_STAGE_IDS.map((id) => [
      id,
      {
        id,
        status: "pending" as const,
        generatedFromVersion: 0,
        generatedAt: null,
        summary: null,
        error: null,
      },
    ]),
  ) as CodeStages;
  return {
    projectId: "p1",
    codeVersion: CODE_VERSION,
    designVersion: 1,
    designBlocker: null,
    generatedFromDesignVersion: 1,
    stages,
    run: null,
    gate: { decision: null, history: [] },
    approvedThrough: null,
    scope: null,
    nextSprint: null,
    techStack: null,
    contract: null,
    agreement: null,
    repository: built
      ? {
          version: CODE_VERSION,
          manifest: [],
          build: {
            toolchain: "node",
            isolation: "a subprocess in a temporary directory",
            steps: [
              {
                name: "install",
                command: "npm install",
                outcome: "passed",
                durationSeconds: 12,
                logTail: "",
              },
            ],
          },
          repository: null,
          notPushedReason: "no connection",
        }
      : null,
    diff: null,
    thread: [],
  };
}

function show(state: PreviewState, { built = true }: { built?: boolean } = {}) {
  preview = state;
  render(
    <StageCodeReview
      projectId="p1"
      snapshot={snapshot(built)}
      onOpenStage={vi.fn()}
      onContinue={vi.fn()}
    />,
  );
}

describe("the way on to Testing and Security", () => {
  const approved = {
    kind: "approved" as const,
    by: "Alex Chen",
    at: "2026-09-29 10:00",
    version: CODE_VERSION,
    note: null,
  };

  it("is offered once the code is approved, and goes there", () => {
    preview = { status: "none" };
    const onContinue = vi.fn();
    const decided = {
      ...snapshot(true),
      gate: { decision: approved, history: [approved] },
    };
    render(
      <StageCodeReview
        projectId="p1"
        snapshot={decided}
        onOpenStage={vi.fn()}
        onContinue={onContinue}
      />,
    );
    expect(
      screen.getByText(`Code approved for code version ${CODE_VERSION}`),
    ).toBeTruthy();
    screen
      .getByRole("button", { name: "Continue to Testing & Security" })
      .click();
    expect(onContinue).toHaveBeenCalledOnce();
  });

  it("is offered for a version a fix wrote, which its patched version's approval covers", () => {
    preview = { status: "none" };
    const onContinue = vi.fn();
    render(
      <StageCodeReview
        projectId="p1"
        snapshot={{ ...snapshot(true), approvedThrough: CODE_VERSION - 1 }}
        onOpenStage={vi.fn()}
        onContinue={onContinue}
      />,
    );

    expect(
      screen.getByText(
        `Code version ${CODE_VERSION} is approved through code version ${CODE_VERSION - 1}`,
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/Nothing has been decided yet/)).toBeNull();
    screen.getByRole("button", { name: "Continue to Testing & Security" }).click();
    expect(onContinue).toHaveBeenCalledOnce();
  });

  it("is not offered before a decision, nor after changes were asked for", () => {
    show({ status: "none" });
    expect(
      screen.queryByRole("button", { name: "Continue to Testing & Security" }),
    ).toBeNull();
    cleanup();
    const changes = {
      ...approved,
      kind: "changes" as const,
      note: "split the endpoints",
    };
    render(
      <StageCodeReview
        projectId="p1"
        snapshot={{
          ...snapshot(true),
          gate: { decision: changes, history: [changes] },
        }}
        onOpenStage={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Continue to Testing & Security" }),
    ).toBeNull();
  });
});

describe("the preview on the review page", () => {
  it("links to the running app", () => {
    show({
      status: "running",
      url: "http://127.0.0.1:41234",
      codeVersion: CODE_VERSION,
    });
    const link = screen.getByRole("link", { name: /open the app/i });
    expect(link.getAttribute("href")).toBe("http://127.0.0.1:41234");
    expect(
      screen.getByText(/running on http:\/\/127\.0\.0\.1:41234/i),
    ).toBeTruthy();
  });

  it("says when the running app is not the version under review", () => {
    /**
     * The one thing here that can disagree with the snapshot. A reviewer shown
     * an older app beside a newer report would be deciding about code they are
     * not looking at.
     */
    show({
      status: "running",
      url: "http://127.0.0.1:41234",
      codeVersion: CODE_VERSION - 1,
    });
    expect(
      screen.getByText(new RegExp(`not the ${CODE_VERSION} under review`, "i")),
    ).toBeTruthy();
  });

  it("points at Build rather than offering a second way to start one", () => {
    show({ status: "none" });
    expect(screen.getByText(/start it in build/i)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /open the app/i })).toBeNull();
  });

  it("says a version that did not build has nothing to run", () => {
    show({ status: "none" }, { built: false });
    expect(screen.getByText(/did not build/i)).toBeTruthy();
  });

  it("says it is starting rather than saying nothing", () => {
    show({ status: "starting" });
    expect(screen.getByText(/installing dependencies/i)).toBeTruthy();
  });

  it("stays out of the way where previews cannot run at all", () => {
    /** Fixtures mode: a row explaining an absent capability is noise. */
    show({ status: "unavailable", reason: "previews need the live backend" });
    expect(screen.queryByText(/^Preview$/)).toBeNull();
  });
});

describe("the agreement line", () => {
  // It said "100% of the contract is implemented" over a count of registered
  // routes: a route that answers without doing anything counted (review item C2-3).
  it("says routes registered, not implemented", () => {
    preview = { status: "none" };
    const data: CodeSnapshot = {
      ...snapshot(true),
      agreement: {
        contractVersion: 1,
        findings: [],
        counts: {
          endpointsTotal: 4,
          endpointsImplemented: 4,
          endpointsMissing: [],
          endpointsCalled: 3,
          endpointsUnused: ["get-orders-id"],
          orphanRoutes: [],
          foreignCalls: [],
          schemaMismatches: 0,
          agreementRate: 1,
        },
      },
    };

    render(<StageCodeReview projectId="p1" snapshot={data} onOpenStage={vi.fn()} onContinue={vi.fn()} />);

    expect(screen.getByText(/100% of the contract's routes are registered/)).toBeTruthy();
    expect(screen.queryByText(/of the contract is implemented/)).toBeNull();
  });
});

describe("what a version changed", () => {
  // The review showed a version's files and nothing of what had changed since
  // the one before, and no pull request to read it in (review item C2-8).
  const open = (data: CodeSnapshot) =>
    render(<StageCodeReview projectId="p1" snapshot={data} onOpenStage={vi.fn()} onContinue={vi.fn()} />);

  it("lists each file changed since the version before, and shows a file's diff when opened", () => {
    preview = { status: "none" };
    changes = {
      version: CODE_VERSION,
      againstVersion: 2,
      files: [
        {
          path: "apps/api/src/routes/orders.ts",
          status: "changed",
          additions: 2,
          deletions: 1,
          diff: "@@ -1,2 +1,3 @@\n one\n-two\n+TWO\n+three",
          truncated: false,
        },
        { path: "apps/api/src/new.ts", status: "added", additions: 4, deletions: 0, diff: "+x", truncated: false },
      ],
    };
    open(snapshot(true));

    expect(screen.getByText("2 files changed since code version 2")).toBeTruthy();
    expect(screen.getByText("+2 -1")).toBeTruthy();
    expect(screen.queryByText("+TWO")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /apps\/api\/src\/routes\/orders.ts/ }));
    expect(screen.getByText("+TWO")).toBeTruthy();
  });

  it("says the first version has nothing before it", () => {
    changes = { version: CODE_VERSION, againstVersion: null, files: [] };
    open(snapshot(true));

    expect(screen.getByText("This is the first code version, so there is nothing to compare it with.")).toBeTruthy();
  });

  it("links the pull request that proposes the version", () => {
    changes = undefined;
    const data = snapshot(true);
    if (!data.repository) throw new Error("built");
    data.repository.repository = {
      provider: "github",
      owner: "presenter",
      name: "tracker",
      defaultBranch: "main",
      commitSha: "c".repeat(40),
      url: "https://github.com/presenter/tracker",
      branch: "code/v3",
      pullRequestUrl: "https://github.com/presenter/tracker/pull/7",
      pullRequestNumber: 7,
    };
    open(data);

    const link = screen.getByRole("link", { name: "Pull request #7" }) as HTMLAnchorElement;
    expect(link.href).toBe("https://github.com/presenter/tracker/pull/7");
  });
});

