import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

const state = vi.hoisted(() => ({
  session: { status: "checking" } as { status: string; signedIn?: boolean },
  load: { status: "loading", error: null } as { status: string; error: string | null },
  hydrate: vi.fn(() => Promise.resolve()),
}));

vi.mock("@/entities/account", () => ({
  useSession: () => state.session,
  isSignedIn: (s: { status: string; signedIn?: boolean }) =>
    s.status === "signed-in" || (s.status === "unsupported" && Boolean(s.signedIn)),
}));
vi.mock("@/entities/project", () => ({
  useProjectsLoad: () => state.load,
  hydrateProjects: state.hydrate,
}));

const { AuthGuard } = await import("./AuthGuard");

afterEach(() => {
  cleanup();
  state.hydrate.mockClear();
});

function LoginSays() {
  const from = (useLocation().state as { from?: string } | null)?.from;
  return <p>Sign in, then back to {from}</p>;
}

function at(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<LoginSays />} />
        <Route
          path="*"
          element={
            <AuthGuard>
              <p>The workspace</p>
            </AuthGuard>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

/**
 * The signed-in part of the app waits for the server, and keeps the way back.
 */
describe("the sign-in guard", () => {
  it("waits while the server is asked who is signed in", () => {
    state.session = { status: "checking" };
    at("/projects/p_1/testing");

    expect(screen.getByRole("status")).toBeTruthy();
    expect(state.hydrate).not.toHaveBeenCalled();
  });

  it("sends a signed-out reader to sign in, with the page they asked for", () => {
    state.session = { status: "signed-out" };
    at("/projects/p_1/testing?stage=security-scan");

    expect(screen.getByText("Sign in, then back to /projects/p_1/testing?stage=security-scan")).toBeTruthy();
    expect(state.hydrate).not.toHaveBeenCalled();
  });

  it("opens the page, and reads the project list, once someone is signed in", () => {
    state.session = { status: "signed-in" };
    at("/workspace");

    expect(screen.getByText("The workspace")).toBeTruthy();
    expect(state.hydrate).toHaveBeenCalledTimes(1);
  });
});
