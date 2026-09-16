import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { codeApi } from "../../api";
import type { CodeSnapshot } from "../../api/types";
import { StageBuild } from "./StageBuild";

afterEach(cleanup);

async function build(pointer: "none" | "branch") {
  const snapshot = await codeApi.getCode("p1");
  const repository = snapshot.repository!;
  return {
    ...snapshot,
    repository: {
      ...repository,
      repository:
        pointer === "none"
          ? null
          : {
              provider: "github" as const,
              owner: "presenter",
              name: "records",
              defaultBranch: "main",
              commitSha: "c".repeat(40),
              url: "https://github.com/presenter/records",
              branch: "code/v3",
            },
      notPushedReason:
        pointer === "none" ? "not pushed: the project owner has no GitHub connection" : null,
    },
  } as CodeSnapshot;
}

function show(snapshot: CodeSnapshot, githubConnected: boolean | null, approved = false) {
  const handlers = { onPush: vi.fn(async () => undefined), onDownload: vi.fn(async () => undefined) };
  render(
    <MemoryRouter>
      <StageBuild snapshot={snapshot} approved={approved} githubConnected={githubConnected} {...handlers} />
    </MemoryRouter>,
  );
  return handlers;
}

/**
 * Without GitHub nothing was pushed and the only remedy was a whole new run;
 * with it, every version landed on main, unreviewed and failing ones included.
 */
describe("where the code went", () => {
  it("pushes a version that was never pushed, once GitHub is connected", async () => {
    const { onPush } = show(await build("none"), true);

    fireEvent.click(screen.getByRole("button", { name: /push this version/i }));

    expect(onPush).toHaveBeenCalled();
  });

  it("says where to connect GitHub, and downloads the code without it", async () => {
    const { onDownload } = show(await build("none"), false);

    expect(screen.queryByRole("button", { name: /push this version/i })).toBeNull();
    expect(screen.getByRole("link", { name: /connect github in settings/i }).getAttribute("href")).toBe(
      "/settings?tab=git",
    );
    fireEvent.click(screen.getByRole("button", { name: /download the code/i }));
    expect(onDownload).toHaveBeenCalled();
  });

  // An accepted security fix wrote it; the build it used to carry was the
  // patched version's, copied, and described other files.
  it("says a version a fix wrote was not built on its own", async () => {
    const fixed = await build("none");
    show({ ...fixed, approvedThrough: 2, repository: { ...fixed.repository!, build: null } }, true);

    expect(screen.getByText(/Not built on its own: an accepted security fix wrote this version/)).toBeTruthy();
  });

  it("says a version's own branch reaches main only on approval", async () => {
    show(await build("branch"), true);

    expect(screen.getByText(/code\/v3/)).toBeTruthy();
    expect(screen.getByText(/main moves to it when the code review approves it, and not before/)).toBeTruthy();
  });
});


/**
 * A build that ran and did not pass had no way on but generating the whole
 * version again.
 */
describe("a build that ran and did not pass", () => {
  async function built(outcome: "passed" | "failed") {
    const snapshot = await build("none");
    return {
      ...snapshot,
      repository: {
        ...snapshot.repository!,
        build: {
          toolchain: "node 22.17.0 / npm 10.9.2",
          isolation: "a sandbox",
          steps: [{ name: "typecheck", command: "tsc", outcome, durationSeconds: 3, logTail: "" }],
        },
      },
    } as CodeSnapshot;
  }

  function showBuild(snapshot: CodeSnapshot, approved: boolean) {
    const onBuildAgain = vi.fn(async () => undefined);
    render(
      <MemoryRouter>
        <StageBuild
          snapshot={snapshot}
          approved={approved}
          githubConnected={true}
          onPush={vi.fn(async () => undefined)}
          onDownload={vi.fn(async () => undefined)}
          onBuildAgain={onBuildAgain}
        />
      </MemoryRouter>,
    );
    return onBuildAgain;
  }

  it("can be built again", async () => {
    const onBuildAgain = showBuild(await built("failed"), false);

    fireEvent.click(screen.getByRole("button", { name: /build again/i }));

    expect(onBuildAgain).toHaveBeenCalled();
  });

  it("is not offered once it passed, or once the version is approved", async () => {
    showBuild(await built("passed"), false);
    expect(screen.queryByRole("button", { name: /build again/i })).toBeNull();
    cleanup();

    showBuild(await built("failed"), true);
    expect(screen.queryByRole("button", { name: /build again/i })).toBeNull();
  });
});
