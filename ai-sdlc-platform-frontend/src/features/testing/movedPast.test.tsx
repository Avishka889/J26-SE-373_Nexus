import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { testingApi } from "./api";
import { TestingSecurity } from "./page";

// The whole page, which watches its sections scroll; jsdom has neither.
const scrollIntoView = Element.prototype.scrollIntoView;
beforeAll(() => {
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    },
  );
  Element.prototype.scrollIntoView = () => {};
});
afterAll(() => {
  vi.unstubAllGlobals();
  Element.prototype.scrollIntoView = scrollIntoView;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const WAITING_RUN = {
  id: "run-1",
  state: "awaiting_gate" as const,
  model: "deepseek:deepseek-flash",
  thinking: "disabled",
  startedAt: "2026-10-04T09:00:00+00:00",
  finishedAt: null,
  stoppedAt: null,
  error: null,
};

/**
 * A fix applied before the test review was decided moved the code on, and the
 * review was then of code no longer current. The page did not offer to decide
 * it, the chat box said no review was waiting, and running the tests again was
 * refused. Running them again now closes it, and the page says so.
 */
describe("a test review the code has moved past", () => {
  it("says to run the tests again, and that is what the page offers", async () => {
    const base = await testingApi.getTesting("p1");
    const current = base.testedCodeVersion + 1;
    vi.spyOn(testingApi, "getTesting").mockResolvedValue({
      ...base,
      codeVersion: current,
      codeMovedOn: true,
      run: { ...WAITING_RUN, version: base.testVersion },
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/projects/p1/testing"]}>
          <Routes>
            <Route path="/projects/:projectId/testing" element={<TestingSecurity />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText(new RegExp(`Run the tests again to test version ${current}`)),
    ).toBeTruthy();
    const again = screen.getByRole("button", { name: /Run tests again/ }) as HTMLButtonElement;
    expect(again.disabled).toBe(false);
    // The whole page, first rendered in a cold worker: it took 5.6 to 9 seconds in
    // seven full runs on 2026-10-09 and 10, past the default five, and one second alone.
  }, 20_000);
});
