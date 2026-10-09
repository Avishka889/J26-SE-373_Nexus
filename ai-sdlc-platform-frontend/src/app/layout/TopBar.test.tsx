import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { createRef } from "react";

vi.mock("@/entities/attention", () => ({ useAttention: () => [] }));

const { TopBar } = await import("./TopBar");

afterEach(cleanup);

function bar() {
  render(
    <MemoryRouter initialEntries={["/workspace"]}>
      <TopBar onOpenMobileNav={() => undefined} mobileOpen={false} menuTriggerRef={createRef()} />
      <p>The page</p>
    </MemoryRouter>,
  );
  return screen.getByRole("button", { name: /^Notifications/ });
}

const panel = () => screen.queryByRole("region", { name: "Notifications" });

/**
 * The bell's panel cut off whatever did not fit, and only its X closed it.
 */
describe("the notifications panel", () => {
  it("opens from the bell, which says whether it is open", () => {
    const bell = bar();
    expect(bell.getAttribute("aria-expanded")).toBe("false");
    expect(panel()).toBeNull();

    fireEvent.click(bell);

    expect(bell.getAttribute("aria-expanded")).toBe("true");
    expect(panel()).not.toBeNull();
  });

  it("scrolls its list, so a long one can be read to the end", () => {
    fireEvent.click(bar());

    const list = screen.getByRole("list");
    expect(list.className.split(/\s+/)).toEqual(expect.arrayContaining(["max-h-80", "overflow-y-auto"]));
    expect(list.querySelectorAll("li").length).toBeGreaterThan(0);
  });

  it("closes on a press outside it", () => {
    fireEvent.click(bar());
    fireEvent.mouseDown(screen.getByText("The page"));

    expect(panel()).toBeNull();
  });

  it("stays open on a press inside it", () => {
    fireEvent.click(bar());
    fireEvent.mouseDown(screen.getByRole("list"));

    expect(panel()).not.toBeNull();
  });

  it("closes on Escape and gives the bell the focus back", () => {
    const bell = bar();
    fireEvent.click(bell);
    fireEvent.keyDown(document, { key: "Escape" });

    expect(panel()).toBeNull();
    expect(document.activeElement).toBe(bell);
  });

  it("closes from its own button, which has a name", () => {
    fireEvent.click(bar());
    fireEvent.click(screen.getByRole("button", { name: "Close notifications" }));

    expect(panel()).toBeNull();
  });
});
