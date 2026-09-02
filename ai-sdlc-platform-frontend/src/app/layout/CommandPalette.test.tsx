import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { projectsApi } from "@/entities/project";
import { useUiStore } from "@/store/ui";
import { CommandPalette } from "./CommandPalette";

beforeEach(() => useUiStore.setState({ commandPaletteOpen: false }));
afterEach(cleanup);

function palette() {
  render(
    <MemoryRouter>
      <button type="button">Opened from here</button>
      <CommandPalette />
    </MemoryRouter>,
  );
  const opener = screen.getByRole("button", { name: "Opened from here" });
  opener.focus();
  act(() => useUiStore.getState().setCommandPaletteOpen(true));
  return { opener, dialog: screen.getByRole("dialog", { name: "Search projects and pages" }) };
}

/**
 * The palette searched the eight newest projects only, because it cut the list
 * before matching; and it was not a dialog to a screen reader, kept no focus
 * inside, and left focus nowhere when it closed.
 */
describe("the command palette", () => {
  it("finds a project beyond the eight newest", async () => {
    // A tick apart: the demo store names a project by the millisecond it was made.
    for (let n = 1; n <= 10; n += 1) {
      await projectsApi.create(`Archive ${n}`);
      await new Promise((resolve) => setTimeout(resolve, 2));
    }
    const { dialog } = palette();

    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search projects and pages" }), {
      target: { value: "archive 1" },
    });

    expect(within(dialog).getByText("Archive 1")).toBeTruthy();
    expect(within(dialog).getByText("Archive 10")).toBeTruthy();
  });

  it("keeps Tab inside, closes on Escape, and gives focus back", () => {
    const { opener, dialog } = palette();
    const controls = within(dialog).getAllByRole("button");
    const last = controls[controls.length - 1];

    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(dialog.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});
