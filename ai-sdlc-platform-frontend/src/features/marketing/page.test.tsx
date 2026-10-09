import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Landing } from "./page";

afterEach(cleanup);

const page = () =>
  render(
    <MemoryRouter>
      <Landing />
    </MemoryRouter>,
  ).container;

/**
 * The landing page promised what the product does not do: monthly plans at
 * $499 and $1,499, SOC 2, SSO and an on-premise option, AWS, Azure and GCP, five
 * language stacks, a sourceless "98.4%", and a phone number and address that
 * were nobody's; its footer links went to the wrong places, and there was no
 * privacy statement at all.
 */
describe("the landing page", () => {
  it("claims nothing the platform does not do", () => {
    const text = page().textContent ?? "";

    for (const claim of ["$499", "$1,499", "SOC 2", "Azure", "GCP", "SSO", "on-premise", "98.4%", "555-0199", "San Francisco"]) {
      expect(text).not.toContain(claim);
    }
    expect(text).toContain("MERN stack");
    expect(text).toContain("What happens to your data");
  });

  it("links only to sections that are on it", () => {
    const container = page();
    const targets = Array.from(container.querySelectorAll<HTMLAnchorElement>('a[href^="#"]')).map((a) =>
      a.getAttribute("href")!.slice(1),
    );

    expect(targets.length).toBeGreaterThan(0);
    for (const id of targets) {
      expect(container.querySelector(`#${id}`), `#${id}`).not.toBeNull();
    }
  });
});
