import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { FlowScreen } from "../../api/types";
import { ScreenPreview } from "./ScreenPreview";

afterEach(cleanup);

/**
 * A screen that is used rather than filled in: a read-out and its keys. With
 * only fields, rows and lists every wireframe was a form or a table.
 */
const keypad = {
  id: "s1",
  name: "Calculator",
  crumbs: [],
  terminal: false,
  links: [{ id: "l1", label: "History", targetId: "s2", variant: "text" }],
  blocks: [
    { id: "d1", kind: "display", label: "Result", value: "42", tone: null, linkId: null },
    { id: "k7", kind: "button", label: "7", value: "7", tone: null, linkId: null },
    { id: "kp", kind: "button", label: "+", value: "+", tone: null, linkId: null },
    { id: "kh", kind: "button", label: "History", value: null, tone: null, linkId: "l1" },
  ],
} as unknown as FlowScreen;

describe("a wireframe with a display and keys", () => {
  it("draws the read-out and one key per button", () => {
    render(<ScreenPreview screen={keypad} isDark={false} />);

    expect(screen.getByText("Result")).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.getByRole("button", { name: "7" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "+" })).toBeTruthy();
  });

  it("lets a key with a link go where it leads", () => {
    const onNavigate = vi.fn();
    render(<ScreenPreview screen={keypad} isDark={false} onNavigate={onNavigate} />);

    fireEvent.click(screen.getAllByRole("button", { name: "History" })[0]);

    expect(onNavigate).toHaveBeenCalledWith("s2");
  });
});
