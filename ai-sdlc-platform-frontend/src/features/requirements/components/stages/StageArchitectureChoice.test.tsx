import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { requirementsApi } from "../../api";
import { StageArchitectureChoice } from "./StageArchitectureChoice";

afterEach(cleanup);

/**
 * Choosing a candidate disabled every Select while the choice was saved, with
 * nothing on the one that was clicked to say it had been taken.
 */
describe("choosing an architecture", () => {
  it("keeps the chosen candidate's button busy until the server answers", async () => {
    const { architecture } = await requirementsApi.getDesign("p1");
    if (!architecture) throw new Error("the seed recommends an architecture");
    const unchosen = architecture.candidates.find(
      (one) => one.id !== architecture.selectedCandidateId,
    );
    if (!unchosen) throw new Error("the seed has a candidate to choose");
    let answer!: () => void;
    const onSelect = vi.fn(() => new Promise<void>((resolve) => (answer = resolve)));
    render(
      <StageArchitectureChoice
        architecture={{ ...architecture, selectedCandidateId: null }}
        reviewer="A. Chen"
        onSelect={onSelect}
        isSelecting={false}
      />,
    );
    const button = screen.getByRole("button", { name: `Select ${unchosen.name}` });

    fireEvent.click(button);
    fireEvent.click(button);

    expect(onSelect).toHaveBeenCalledOnce();
    expect(onSelect).toHaveBeenCalledWith(unchosen.id);
    expect(button.getAttribute("aria-busy")).toBe("true");
    await act(async () => answer());
    expect(button.getAttribute("aria-busy")).toBeNull();
  });
});
