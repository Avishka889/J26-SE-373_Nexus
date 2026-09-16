import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { CodeSnapshot } from "../api/types";
import { PreviewPanel } from "./PreviewPanel";

const mutations = vi.hoisted(() => ({
  start: { isPending: false, mutate: () => {} },
  stop: { isPending: false, mutate: () => {} },
}));

vi.mock("../hooks/useCode", () => ({
  usePreview: () => ({ data: { status: "none" } }),
  usePreviewMutations: () => mutations,
}));

afterEach(() => {
  cleanup();
  mutations.start.isPending = false;
});

/**
 * Run the app was disabled while its request was in flight, with nothing on it
 * to say so: the click read as doing nothing, as Run tests did on the live run.
 */
describe("the preview's Run the app", () => {
  const show = () =>
    render(
      <PreviewPanel
        projectId="p9"
        snapshot={{ codeVersion: 1 } as CodeSnapshot}
        buildPassed
      />,
    );

  it("shows it is busy while the start request is in flight", () => {
    mutations.start.isPending = true;
    show();

    const button = screen.getByRole("button", { name: /run the app/i });
    expect(button.getAttribute("aria-busy")).toBe("true");
  });

  it("is ready to click otherwise", () => {
    show();

    const button = screen.getByRole("button", { name: /run the app/i }) as HTMLButtonElement;
    expect(button.getAttribute("aria-busy")).toBeNull();
    expect(button.disabled).toBe(false);
  });
});
