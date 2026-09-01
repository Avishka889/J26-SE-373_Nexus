import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Expandable } from "./Expandable";

afterEach(cleanup);

describe("a list a reader opens when they need it", () => {
  it("shows its summary and keeps the list closed until asked", () => {
    render(
      <Expandable summary="176 verified claims: 3 breaking, 173 fix">
        <p>the first claim</p>
      </Expandable>,
    );
    const toggle = screen.getByRole("button", { name: /176 verified claims: 3 breaking, 173 fix/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("the first claim")).toBeNull();

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("the first claim")).toBeTruthy();

    fireEvent.click(toggle);
    expect(screen.queryByText("the first claim")).toBeNull();
  });
});
