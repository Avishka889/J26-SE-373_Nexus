import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { requirementsApi } from "../../api";
import { StageWireframes } from "./StageWireframes";

afterEach(cleanup);

/**
 * Code's screen links opened a stage of its own, which does not show screens;
 * now they come here by the address, and the screen they name opens.
 */
describe("a screen another page links to", () => {
  it("opens its flow at that screen", async () => {
    const snapshot = await requirementsApi.getDesign("p1");
    const flow = snapshot.wireframes.flows.find((one) => one.screens.length > 1)!;
    const linked = flow.screens[1];

    render(
      <StageWireframes
        snapshot={snapshot}
        projectName="NexusPay"
        isDark={false}
        onJump={vi.fn()}
        onRequestRefinement={vi.fn()}
        linkedScreenId={linked.id}
      />,
    );

    const dot = screen.getByRole("button", { name: `Go to ${linked.name}` });
    expect(dot.getAttribute("aria-current")).toBe("true");
  });

  it("opens nothing when no screen is linked", async () => {
    const snapshot = await requirementsApi.getDesign("p1");

    render(
      <StageWireframes
        snapshot={snapshot}
        projectName="NexusPay"
        isDark={false}
        onJump={vi.fn()}
        onRequestRefinement={vi.fn()}
      />,
    );

    expect(screen.queryByText("Click through the flow")).toBeNull();
  });
});
