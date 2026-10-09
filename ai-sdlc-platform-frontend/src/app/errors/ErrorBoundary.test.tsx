import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ErrorBoundary } from "./ErrorBoundary";
import { PageError } from "./PageError";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function Broken({ message = "snapshot.stages is undefined" }: { message?: string }): never {
  throw new Error(message);
}

function page(child: React.ReactNode, resetKey = "/projects/p_1/testing") {
  return (
    <MemoryRouter>
      <nav>Sidebar</nav>
      <ErrorBoundary
        resetKey={resetKey}
        fallback={(error, reset) => <PageError error={error} onRetry={reset} />}
      >
        {child}
      </ErrorBoundary>
    </MemoryRouter>
  );
}

/**
 * A page that fails to render takes only itself down.
 *
 * There was one boundary, at the root, outside the router and the theme, with
 * "Something went wrong." as its whole fallback: one unexpected field in a
 * snapshot blanked the sidebar, the top bar and every route, and only a manual
 * reload recovered.
 */
describe("a page that fails to render", () => {
  it("is replaced by a panel that says so, and the shell around it stays", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(page(<Broken />));

    expect(screen.getByText("Sidebar")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("This page hit a problem");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to projects" }).getAttribute("href")).toBe("/projects");
  });

  it("renders again on Try again", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    let fail = true;
    function Flaky() {
      if (fail) throw new Error("a first render that failed");
      return <p>The tests</p>;
    }
    render(page(<Flaky />));

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(screen.getByText("The tests")).toBeTruthy();
  });

  it("is left behind when the reader moves to another page", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { rerender } = render(page(<Broken />, "/projects/p_1/testing"));

    rerender(page(<p>The code</p>, "/projects/p_1/code"));

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("The code")).toBeTruthy();
  });

  it("asks for a reload when its code was replaced by a newer deploy", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      page(<Broken message="Failed to fetch dynamically imported module: /assets/page-3f2a.js" />),
    );

    expect(screen.getByRole("alert").textContent).toContain("A newer version of the app is available");
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});

describe("the app's last resort", () => {
  it("is a page that says what happened and offers a reload, not a bare sentence", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert").textContent).toContain("The app hit a problem");
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });
});
