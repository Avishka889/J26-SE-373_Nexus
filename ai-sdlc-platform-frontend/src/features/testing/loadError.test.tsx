import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { testingApi } from "./api";
import { TestingSecurity } from "./page";

/**
 * A first read that fails says why. With no snapshot the page returned its
 * loader before it looked at the error, so a failed read said "Loading the
 * tests" for ever.
 */
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the Testing page, when the tests cannot be read", () => {
  it("says why instead of loading for ever", async () => {
    vi.spyOn(testingApi, "getTesting").mockRejectedValue(
      new Error("502 Bad Gateway"),
    );
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <MemoryRouter initialEntries={["/projects/p2/testing"]}>
          <Routes>
            <Route
              path="/projects/:projectId/testing"
              element={<TestingSecurity />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/502 Bad Gateway/)).toBeTruthy();
    expect(screen.queryByText("Loading the tests")).toBeNull();
  });
});
