import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const state = vi.hoisted(() => ({
  signIn: vi.fn(() => Promise.resolve()),
}));

vi.mock("@/entities/account", () => ({
  useSession: () => ({ status: "signed-out" }),
  isSignedIn: () => false,
  signIn: state.signIn,
  register: vi.fn(),
}));

const { Login } = await import("./page");

afterEach(() => {
  cleanup();
  state.signIn.mockReset();
});

function signInFrom(from: string) {
  render(
    <MemoryRouter initialEntries={[{ pathname: "/login", state: { from } }]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/projects/p_1/testing" element={<p>The testing page</p>} />
        <Route path="/workspace" element={<p>Home</p>} />
      </Routes>
    </MemoryRouter>,
  );
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ada@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct horse battery staple" } });
  fireEvent.click(screen.getByRole("button", { name: /log in/i }));
}

/**
 * Signing in returns to where the reader was going.
 *
 * Login always went to the home page, so a shared link to a project's review
 * landed on Home after signing in.
 */
describe("the sign-in page", () => {
  it("returns to the page that sent the reader here", async () => {
    state.signIn.mockResolvedValue(undefined);
    signInFrom("/projects/p_1/testing");

    expect(await screen.findByText("The testing page")).toBeTruthy();
    expect(state.signIn).toHaveBeenCalledWith("ada@example.com", "correct horse battery staple");
  });

  it("says why it refused, in place, and stays", async () => {
    state.signIn.mockRejectedValue(new Error("That email and password do not match an account."));
    signInFrom("/projects/p_1/testing");

    expect((await screen.findByRole("alert")).textContent).toBe(
      "That email and password do not match an account.",
    );
    expect(screen.queryByText("The testing page")).toBeNull();
  });
});
