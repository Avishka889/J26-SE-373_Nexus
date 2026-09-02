import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook } from "@testing-library/react";

const refreshProject = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  refreshProject,
}));

const { useProjectFollowsItsRun } = await import("./hooks");

afterEach(() => {
  cleanup();
  refreshProject.mockClear();
});

/**
 * A project's status and progress move when its run starts and when it
 * settles, and only Design and Code asked again: after a testing or deployment
 * run, the header and the lists kept the status from before it.
 */
describe("a project following its phase's run", () => {
  it("is read again when the run starts and when it settles, and not in between", () => {
    const { rerender } = renderHook(({ busy }) => useProjectFollowsItsRun("p1", busy), {
      initialProps: { busy: undefined as boolean | undefined },
    });
    expect(refreshProject).not.toHaveBeenCalled();

    rerender({ busy: true });
    rerender({ busy: true });
    rerender({ busy: false });

    expect(refreshProject).toHaveBeenCalledTimes(2);
    expect(refreshProject).toHaveBeenCalledWith("p1");
  });

  it("is not read again for opening a phase with nothing running", () => {
    const { rerender } = renderHook(({ busy }) => useProjectFollowsItsRun("p1", busy), {
      initialProps: { busy: undefined as boolean | undefined },
    });

    rerender({ busy: false });

    expect(refreshProject).not.toHaveBeenCalled();
  });
});
