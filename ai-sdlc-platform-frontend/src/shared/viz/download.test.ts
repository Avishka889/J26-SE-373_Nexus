import { describe, expect, it } from "vitest";
import { diagramFileName, measure, serialise } from "./download";

/** Serialising is all there is: PNG export was written and then removed. */

function svg(attrs: Record<string, string> = {}): SVGSVGElement {
  const element = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [name, value] of Object.entries(attrs)) element.setAttribute(name, value);
  const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
  text.textContent = "Order";
  element.appendChild(text);
  return element;
}

describe("diagramFileName", () => {
  it("says which project, which diagram and which revision", () => {
    // A folder of exports from several projects and revisions still reads.
    expect(diagramFileName("ShopFlow", "class", 2, "svg")).toBe("shopflow-class-v2.svg");
  });

  it("survives punctuation and spaces in a project name", () => {
    expect(diagramFileName("Cold Chain: Distribution & Logistics", "er", 1, "svg")).toBe(
      "cold-chain-distribution-logistics-er-v1.svg",
    );
  });

  it("leaves the version off when the stage never generated", () => {
    // generatedFromVersion is 0 then, and "v0" would claim a revision that does
    // not exist.
    expect(diagramFileName("ShopFlow", "class", 0, "svg")).toBe("shopflow-class.svg");
  });

  it("never produces a name that is only an extension", () => {
    // A project titled with punctuation alone would otherwise save as ".svg",
    // which is a hidden file on every unix desktop.
    expect(diagramFileName("!!!", "???", 0, "svg")).toBe("diagram.svg");
  });

  it("keeps the name short enough to read", () => {
    expect(diagramFileName("word ".repeat(60), "sequence", 3, "svg").length).toBeLessThanOrEqual(80);
  });
});

describe("measure", () => {
  it("falls back to the viewBox when the element has no layout", () => {
    // jsdom reports a zero rect, and so does any element that is not displayed.
    expect(measure(svg({ viewBox: "0 0 640 480" }))).toEqual({ width: 640, height: 480 });
  });

  it("falls back again rather than returning zero", () => {
    // A canvas sized 0x0 draws nothing, and a saved SVG with width="0" opens blank.
    const { width, height } = measure(svg());
    expect(width).toBeGreaterThan(0);
    expect(height).toBeGreaterThan(0);
  });
});

describe("serialise", () => {
  it("carries its own size, because CSS does not travel with the file", () => {
    const out = serialise(svg({ viewBox: "0 0 640 480" }), "#ffffff");
    expect(out).toMatch(/width="640"/);
    expect(out).toMatch(/height="480"/);
  });

  it("declares the namespace, or nothing will open it", () => {
    expect(serialise(svg({ viewBox: "0 0 10 10" }), "#fff")).toContain(
      'xmlns="http://www.w3.org/2000/svg"',
    );
  });

  it("carries a background, since the page's is not part of the diagram", () => {
    // Dark theme text on a reader's white document would otherwise be invisible.
    expect(serialise(svg({ viewBox: "0 0 10 10" }), "rgb(11, 21, 36)")).toMatch(
      /background:\s*rgb\(11,\s*21,\s*36\)/,
    );
  });

  it("does not modify the diagram on screen", () => {
    const original = svg({ viewBox: "0 0 10 10" });
    serialise(original, "#fff");
    expect(original.getAttribute("width")).toBeNull();
    expect(original.style.background).toBe("");
  });
});
