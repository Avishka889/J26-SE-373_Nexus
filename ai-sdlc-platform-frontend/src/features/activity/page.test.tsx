import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { activityLogEntries } from "./fixtures/activityData";

/**
 * The log arrives after the page first renders, as it does from the
 * orchestrator. The page crashed there on every live visit: its store handed
 * React a new empty list on every read until the log arrived, so React saw the
 * snapshot change on each read and rendered until it gave up.
 */
vi.mock("./api", () => ({
  activityApi: {
    list: vi.fn(
      () => new Promise((resolve) => setTimeout(() => resolve(structuredClone(activityLogEntries)), 30)),
    ),
  },
}));

afterEach(cleanup);

async function show() {
  const { ActivityLog } = await import("./page");
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/projects/p1/traceability"]}>
        <Routes>
          <Route path="/projects/:projectId/traceability" element={<ActivityLog />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("the activity log", () => {
  it("shows a spinner while the log is on its way, then the log for this project", async () => {
    await show();
    expect(screen.getByRole("status", { name: "Loading the activity" })).toBeTruthy();
    expect(await screen.findByText("Test repair applied")).toBeTruthy();
    const { activityApi } = await import("./api");
    expect(activityApi.list).toHaveBeenCalledWith("p1");
  });
});

describe("the activity log's categories", () => {
  it("files and filters a deployment event under Deployment, as the orchestrator names it", async () => {
    // The page said `deploy` where the orchestrator says `deployment` (and `test`
    // for `testing`): a live deployment event showed its raw category, and the
    // Deployment filter matched nothing.
    await show();
    await screen.findByText("Test repair applied");
    fireEvent.click(screen.getByRole("button", { name: "Deployment" }));
    expect(screen.getByText("Production deployment healthy")).toBeTruthy();
    expect(screen.queryByText("Test repair applied")).toBeNull();
  });
});

/**
 * The log is the newest 200 entries the server sends, and the page called
 * them the total; it also claimed sources it does not read.
 */
describe("what the activity log says it shows", () => {
  it("names its one source, and says how many it shows without calling them all", async () => {
    await show();
    await screen.findByText("Test repair applied");

    expect(screen.getByText(/From this project's audit log/)).toBeTruthy();
    expect(screen.queryByText(/pipeline runs, audit log, and artifact traceability/)).toBeNull();
    expect(screen.queryByText(/total events/)).toBeNull();
  });
});
