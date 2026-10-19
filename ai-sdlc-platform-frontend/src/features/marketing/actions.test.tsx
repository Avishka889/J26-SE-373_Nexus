import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const state = vi.hoisted(() => ({ session: { status: "signed-out" } as { status: string } }));

vi.mock("@/entities/account", () => ({
  useSession: () => state.session,
  isSignedIn: (s: { status: string }) => s.status === "signed-in",
}));

const { Landing } = await import("./page");

afterEach(cleanup);

function landing() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<p>The sign-in page</p>} />
        <Route path="/register" element={<p>The registration page</p>} />
        <Route path="/workspace" element={<p>The workspace</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const buttons = (name: RegExp) => screen.queryAllByRole("button", { name });

/**
 * The landing page offered "Upload SRS" four times, each of which sent a
 * visitor to sign in, and no way to create an account; a visitor who was
 * already signed in was offered "Log In", which skipped the sign-in page.
 */
describe("what the landing page offers a visitor", () => {
  it("offers sign-in and an account, and no upload, to a visitor who is signed out", () => {
    state.session = { status: "signed-out" };
    landing();

    expect(buttons(/upload srs/i)).toHaveLength(0);
    expect(buttons(/log in/i)).toHaveLength(0);
    expect(buttons(/^sign in$/i).length).toBeGreaterThan(0);
    expect(buttons(/get started/i).length).toBeGreaterThan(0);
    expect(buttons(/open workspace/i)).toHaveLength(0);
  });

  it("opens the sign-in page from Sign in", () => {
    state.session = { status: "signed-out" };
    landing();
    fireEvent.click(buttons(/^sign in$/i)[0]);

    expect(screen.getByText("The sign-in page")).toBeTruthy();
  });

  it("opens registration from Get started", () => {
    state.session = { status: "signed-out" };
    landing();
    fireEvent.click(buttons(/get started/i)[0]);

    expect(screen.getByText("The registration page")).toBeTruthy();
  });

  it("offers the workspace, and no sign-in, to a visitor who is signed in", () => {
    state.session = { status: "signed-in" };
    landing();

    expect(buttons(/^sign in$/i)).toHaveLength(0);
    expect(buttons(/get started/i)).toHaveLength(0);
    fireEvent.click(buttons(/open workspace/i)[0]);
    expect(screen.getByText("The workspace")).toBeTruthy();
  });
});
