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

/**
 * What sending a note at the test review does, said as it is.
 *
 * The box read "Say what needs to change about these tests". Nothing reads the
 * note: the tests are written again from the acceptance criteria and the
 * contract, and what differs in the next run is what was decided in Self
 * Healing and whatever the code has become. A reviewer who typed what to fix
 * got the same tests back.
 */
describe("the Testing chat box, while a review waits", { timeout: 20_000 }, () => {
  it("says the phase runs again and that the note is a record, not an instruction", async () => {
    const base = await testingApi.getTesting("p1");
    vi.spyOn(testingApi, "getTesting").mockResolvedValue({
      ...base,
      gate: { ...base.gate, decision: null },
      run: {
        id: "run-1",
        state: "awaiting_gate",
        version: base.testVersion,
        model: "deepseek:deepseek-flash",
        thinking: "disabled",
        startedAt: "2026-10-04T09:00:00+00:00",
        finishedAt: null,
        stoppedAt: null,
        error: null,
      },
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

    const box = await screen.findByPlaceholderText("Why the tests should run again");
    expect(box).toBeTruthy();
    expect(screen.queryByPlaceholderText(/what needs to change about these tests/i)).toBeNull();
    expect(
      screen.getByText(
        new RegExp(
          `Runs again as test version ${base.testVersion + 1}\\. The note does not steer the tests\\.`,
        ),
      ),
    ).toBeTruthy();
  });
});
