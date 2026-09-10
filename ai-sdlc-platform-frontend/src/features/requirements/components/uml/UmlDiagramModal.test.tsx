import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { UmlDiagramModal } from "./UmlDiagramModal";
import type { UmlDiagram } from "../../api/types";

/**
 * The modal's controls: the zoom arithmetic, the ways out, and that a save which
 * cannot happen says so instead of going quiet. Mermaid itself is stubbed, since
 * what is under test is the frame around the drawing.
 */

vi.mock("@/shared/viz", () => ({
  MermaidDiagram: () => <div data-testid="diagram" />,
}));

afterEach(cleanup);

const DIAGRAM: UmlDiagram = {
  id: "d1",
  kind: "class",
  title: "Class Diagram",
  description: "Entities and how they relate.",
  source: null,
  useCaseId: null,
  traces: [],
};

function open(onClose = vi.fn()) {
  render(
    <UmlDiagramModal
      diagram={DIAGRAM}
      source="classDiagram\n  Order --> Payment"
      projectName="ShopFlow"
      version={2}
      isDark={false}
      onClose={onClose}
    />,
  );
  return { onClose };
}

const zoomLabel = () => screen.getByText(/%$/).textContent;

describe("UmlDiagramModal", () => {
  it("opens at actual size", () => {
    open();
    expect(zoomLabel()).toBe("100%");
  });

  it("zooms in and out in steps", () => {
    open();
    fireEvent.click(screen.getByLabelText("Zoom in"));
    expect(zoomLabel()).toBe("125%");
    fireEvent.click(screen.getByLabelText("Zoom out"));
    expect(zoomLabel()).toBe("100%");
  });

  it("stops rather than shrinking past legibility", () => {
    open();
    for (let i = 0; i < 12; i += 1)
      fireEvent.click(screen.getByLabelText("Zoom out"));
    expect(zoomLabel()).toBe("50%");
    expect(screen.getByLabelText("Zoom out")).toHaveProperty("disabled", true);
  });

  it("stops at the top of its range too", () => {
    open();
    for (let i = 0; i < 20; i += 1)
      fireEvent.click(screen.getByLabelText("Zoom in"));
    expect(zoomLabel()).toBe("300%");
    expect(screen.getByLabelText("Zoom in")).toHaveProperty("disabled", true);
  });

  it("resets in one press, however far a reader has gone", () => {
    open();
    fireEvent.click(screen.getByLabelText("Zoom in"));
    fireEvent.click(screen.getByLabelText("Zoom in"));
    fireEvent.click(screen.getByLabelText("Reset zoom"));
    expect(zoomLabel()).toBe("100%");
  });

  it("closes on the button, the backdrop and Escape", () => {
    const a = vi.fn();
    render(
      <UmlDiagramModal
        diagram={DIAGRAM}
        source="x"
        projectName="ShopFlow"
        version={2}
        isDark={false}
        onClose={a}
      />,
    );
    fireEvent.click(screen.getByLabelText("Close"));
    expect(a).toHaveBeenCalledOnce();
    cleanup();

    const b = vi.fn();
    render(
      <UmlDiagramModal
        diagram={DIAGRAM}
        source="x"
        projectName="ShopFlow"
        version={2}
        isDark={false}
        onClose={b}
      />,
    );
    fireEvent.click(screen.getByLabelText("Close the diagram"));
    expect(b).toHaveBeenCalledOnce();
    cleanup();

    const c = vi.fn();
    render(
      <UmlDiagramModal
        diagram={DIAGRAM}
        source="x"
        projectName="ShopFlow"
        version={2}
        isDark={false}
        onClose={c}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(c).toHaveBeenCalledOnce();
  });

  it("says so when there is no drawing to save yet", () => {
    // The mocked diagram renders no <svg>, which is also the real state for the
    // moment before mermaid finishes. Silence would leave a reader waiting for a
    // file that is never coming.
    open();
    fireEvent.click(screen.getByText("Download SVG"));
    expect(screen.getByText(/has not finished drawing/)).toBeTruthy();
  });

  it("offers SVG and not a raster", () => {
    // PNG was offered and removed: rasterising a vector goes soft the moment
    // anyone zooms it, and the worse format gets picked simply by being there.
    open();
    expect(screen.getByText("Download SVG")).toBeTruthy();
    expect(screen.queryByText("PNG")).toBeNull();
  });
});
