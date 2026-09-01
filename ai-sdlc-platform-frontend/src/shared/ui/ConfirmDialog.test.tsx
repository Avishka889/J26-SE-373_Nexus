import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ConfirmDialog } from "./ConfirmDialog";

/**
 * The guard on an irreversible action.
 *
 * Deleting a project was one click on a trash icon that only appeared on hover,
 * and artefacts cascade from projects, so it destroyed every stored version of
 * every artefact. In this repository those are the evaluation record.
 */

afterEach(cleanup);

function dialog(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      title="Delete this project?"
      body="Cold Chain and everything generated for it will be removed."
      confirmLabel="Delete project"
      isDark={false}
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onConfirm, onCancel };
}

describe("ConfirmDialog", () => {
  it("says what will happen, in the reader's terms", () => {
    dialog();
    expect(screen.getByText(/Cold Chain and everything generated/)).toBeTruthy();
  });

  it("confirms only when the confirm button is pressed", () => {
    const { onConfirm } = dialog();
    fireEvent.click(screen.getByText("Delete project"));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("cancels on the cancel button", () => {
    const { onCancel, onConfirm } = dialog();
    fireEvent.click(screen.getByText("Cancel"));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("cancels on Escape", () => {
    const { onCancel, onConfirm } = dialog();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("does not put the destructive action under the initial focus", () => {
    // Opened by accident, Enter should cancel rather than delete.
    const { onConfirm } = dialog();
    expect(document.activeElement?.textContent).toBe("Cancel");
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("announces itself as needing an answer", () => {
    dialog();
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });
});
