import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { MOCK_PROJECTS } from "@/entities/project/fixtures";
import { codeApi } from "./api";
import { CodeWorkspace } from "./components/CodeWorkspace";

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
 * A code review waiting while a newer design was approved is of code that no
 * longer follows the design. Requesting changes there regenerated from the
 * older design, and approving sent that code on to Testing; the server refuses
 * both, and the page says what to do instead before anyone types a note.
 */
describe("a code review the design has moved past", () => {
  async function show(designBlocker: string | null) {
    const project = MOCK_PROJECTS.find((one) => one.id === "p2")!;
    const base = await codeApi.getCode(project.id);
    vi.spyOn(codeApi, "getCode").mockResolvedValue({
      ...base,
      generatedFromDesignVersion: 1,
      designVersion: 2,
      designBlocker,
      run: {
        id: "run-1",
        state: "awaiting_gate",
        version: base.codeVersion,
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
        <MemoryRouter initialEntries={[`/projects/${project.id}/code`]}>
          <CodeWorkspace project={project} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("says to generate again, and offers neither decision on code from the older design", async () => {
    await show(null);

    const said = await screen.findAllByText(/design version 2 has been approved since/);
    expect(said.length).toBe(2); // the chat box and the decision bar, once each
    const request = screen.getByRole("button", { name: /Request changes/ }) as HTMLButtonElement;
    expect(request.disabled).toBe(true);
    const approve = screen.getByRole("button", { name: /Approve code/ }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
  });

  it("leaves changes alone while the newer design is not settled yet", async () => {
    await show("the design changed after it was approved: design version 2 waits on its review");

    await screen.findByText(/This code was generated from design version 1/);
    expect(screen.queryByText(/design version 2 has been approved since/)).toBeNull();
    const request = screen.getByRole("button", { name: /Request changes/ }) as HTMLButtonElement;
    expect(request.disabled).toBe(false);
    const approve = screen.getByRole("button", { name: /Approve code/ }) as HTMLButtonElement;
    expect(approve.disabled).toBe(false);
  });
});
