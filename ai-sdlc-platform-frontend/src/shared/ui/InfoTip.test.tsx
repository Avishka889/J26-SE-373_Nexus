import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { InfoTip } from "./InfoTip";

/**
 * The bubble opens to the right of its icon, above it. Where that would cross
 * the right edge of the window it slides left, its arrow still at the icon; where
 * there is no room above, it opens below.
 */
afterEach(cleanup);

function placed(box: Partial<DOMRect>, run: () => void) {
  const measure = HTMLElement.prototype.getBoundingClientRect;
  const width = window.innerWidth;
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement) {
    return this.getAttribute("role") === "tooltip"
      ? ({ ...box } as DOMRect)
      : measure.call(this);
  };
  Object.defineProperty(window, "innerWidth", {
    value: 390,
    configurable: true,
  });
  try {
    run();
  } finally {
    HTMLElement.prototype.getBoundingClientRect = measure;
    Object.defineProperty(window, "innerWidth", {
      value: width,
      configurable: true,
    });
  }
}

describe("where the bubble opens", () => {
  it("slides left by what would cross the window's edge, and opens below with no room above", () => {
    placed({ left: 200, right: 520, top: 2, bottom: 60 }, () => {
      render(
        <InfoTip text="A long hint" label="About Service account client ID" />,
      );
      fireEvent.focus(
        screen.getByRole("button", { name: "About Service account client ID" }),
      );

      const tip = screen.getByRole("tooltip");
      // 520 - (390 - 8) = 138 past the edge, so it slides 138px left.
      expect(tip.style.transform).toBe("translateX(-146px)");
      expect(tip.className).toContain("top-full");
      const arrow = tip.querySelector<HTMLElement>("[aria-hidden='true']");
      expect(arrow?.style.left).toBe("148px");
    });
  });

  it("stays where it opened when it fits", () => {
    placed({ left: 40, right: 300, top: 120, bottom: 170 }, () => {
      render(<InfoTip text="A short hint" label="About Cluster" />);
      fireEvent.focus(screen.getByRole("button", { name: "About Cluster" }));

      const tip = screen.getByRole("tooltip");
      expect(tip.style.transform).toBe("translateX(-8px)");
      expect(tip.className).toContain("bottom-full");
    });
  });
});
