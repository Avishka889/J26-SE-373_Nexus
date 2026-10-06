import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/entities/account", () => ({
  useSession: () => ({ status: "signed-out" }),
  isSignedIn: () => false,
  signIn: vi.fn(),
  register: vi.fn(),
}));

const { Login, Register } = await import("./page");

afterEach(cleanup);

const at = (page: "login" | "register") =>
  render(<MemoryRouter>{page === "login" ? <Login /> : <Register />}</MemoryRouter>);

const password = () => screen.getByLabelText("Password") as HTMLInputElement;

/**
 * A password could not be looked at before it was sent, on either form, and
 * the two forms called the same act "Log In" and "Sign in".
 */
describe("the password field", () => {
  for (const page of ["login", "register"] as const) {
    it(`hides the password until asked, and hides it again, on ${page}`, () => {
      at(page);
      fireEvent.change(password(), { target: { value: "correct horse" } });
      expect(password().type).toBe("password");

      const show = screen.getByRole("button", { name: "Show password" });
      expect(show.getAttribute("aria-pressed")).toBe("false");
      expect(show.getAttribute("type")).toBe("button");
      fireEvent.click(show);

      expect(password().type).toBe("text");
      expect(password().value).toBe("correct horse");
      const hide = screen.getByRole("button", { name: "Hide password" });
      expect(hide.getAttribute("aria-pressed")).toBe("true");
      fireEvent.click(hide);
      expect(password().type).toBe("password");
    });
  }

  it("says when Caps Lock is on, and stops saying it when it is off", () => {
    at("login");
    const caps = (on: boolean) =>
      fireEvent.keyUp(password(), { key: "a", modifierCapsLock: on });

    expect(screen.queryByText("Caps Lock is on.")).toBeNull();
    caps(true);
    expect(screen.getByText("Caps Lock is on.")).toBeTruthy();
    caps(false);
    expect(screen.queryByText("Caps Lock is on.")).toBeNull();
  });
});

describe("the words for signing in", () => {
  it("are Sign in on the sign-in form, which starts in the email field", () => {
    at("login");

    expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /log in/i })).toBeNull();
    expect(document.activeElement).toBe(screen.getByLabelText("Email"));
  });

  it("are Sign in on the registration page's way back", () => {
    at("register");

    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByText(/log in/i)).toBeNull();
  });
});
