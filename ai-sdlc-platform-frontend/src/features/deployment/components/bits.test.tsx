import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { StateChip } from "./bits";

afterEach(cleanup);

describe("a deployment's state chip", () => {
  // A release whose rollback a person declined after its traffic moved serves on,
  // unverified. It read as failed, as if it had never gone out (review item C4-5).
  it("says a release kept after a declined rollback is kept, unverified", () => {
    render(<StateChip state="kept-unverified" />);

    expect(screen.getByText("kept, unverified")).toBeTruthy();
  });
});
