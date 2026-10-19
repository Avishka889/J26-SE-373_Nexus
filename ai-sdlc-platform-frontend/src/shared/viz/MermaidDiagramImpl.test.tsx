import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * A fresh copy of the component and of mermaid, so each test meets mermaid as
 * a page does on first load: not configured yet.
 */
async function fresh() {
  vi.resetModules();
  const { default: mermaid } = await import("mermaid");
  const { MermaidDiagramImpl } = await import("./MermaidDiagramImpl");
  return { mermaid, MermaidDiagramImpl };
}

// Seen on a live project, 2026-10-17: the component showed its own message in
// the diagram's place, and mermaid's "Syntax error in text" picture sat at the
// end of the page as well, outside the layout, one for every failed render.
// Each test loads mermaid afresh, which is seconds on a busy machine.
describe("a diagram mermaid cannot read", { timeout: 20_000 }, () => {
  it("shows its own message in place, and leaves nothing of mermaid's at the end of the page", async () => {
    const { MermaidDiagramImpl } = await fresh();

    render(
      <MermaidDiagramImpl
        id="broken"
        isDark={false}
        chart={"sequenceDiagram\n  A->>B: stored; here is its id"}
      />,
    );

    expect(await screen.findByText("Unable to render diagram preview")).toBeTruthy();
    expect(document.body.textContent).not.toContain("Syntax error");
    expect(document.querySelector('[id^="dmermaid-broken"]')).toBeNull();
  });
});

describe("the first diagram on a dark page", { timeout: 20_000 }, () => {
  it("configures mermaid in the dark theme rather than leaving it on its own defaults", async () => {
    const { mermaid, MermaidDiagramImpl } = await fresh();
    const initialize = vi.spyOn(mermaid, "initialize");

    render(<MermaidDiagramImpl id="first" isDark chart={"graph TD\n  A-->B"} />);

    expect(initialize).toHaveBeenCalledWith(
      expect.objectContaining({ theme: "dark", suppressErrorRendering: true }),
    );
  });
});
