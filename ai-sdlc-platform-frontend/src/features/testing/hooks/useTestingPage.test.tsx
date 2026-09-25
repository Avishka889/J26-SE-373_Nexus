import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useSessionStore } from "@/store/session";
import { useTestingPage } from "./useTestingPage";

/**
 * The address says which project's tests are shown. Preferring the session's
 * last project showed project A's tests under project B's address, as the code
 * and deployment phases once did.
 */
afterEach(cleanup);

function Probe() {
  const page = useTestingPage();
  return <p data-testid="shown">{page.projectId}</p>;
}

describe("the Testing page's actions", () => {
  /**
   * A handler that returns its request keeps the button that asked busy until
   * the server answers. Keep, Reject and the proofs' Try again each dropped it
   * (`void apply(...)`), so their buttons stayed clickable with nothing on them.
   */
  it("return their requests, so the button that asked stays busy", async () => {
    const client = new QueryClient();
    const { result } = renderHook(() => useTestingPage(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={["/projects/p1/testing"]}>
            <Routes>
              <Route path="/projects/:projectId/testing" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      ),
    });
    await waitFor(() => expect(result.current.projectId).toBe("p1"));
    const page = result.current;

    for (const request of [
      page.approveRepair("t-1"),
      page.rejectRepair("t-1"),
      page.retryProofs(),
    ]) {
      expect(typeof (request as PromiseLike<unknown> | undefined)?.then).toBe("function");
      await request;
    }
  });
});

describe("the Testing page", () => {
  it("shows the project in its address, whatever was visited last", async () => {
    useSessionStore.getState().setActiveProjectId("p1");
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/projects/p2/testing"]}>
          <Routes>
            <Route path="/projects/:projectId/testing" element={<Probe />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("shown").textContent).toBe("p2"));
    await waitFor(() => expect(useSessionStore.getState().activeProjectId).toBe("p2"));
  });
});
