import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./Sidebar";

/**
 * Exactly one place in the sidebar says "you are here".
 *
 * Entering a requirement lit both Projects and the project's own row, because
 * "/projects" matched "/projects/{id}/requirements" by prefix. A reader cannot
 * be in the list and inside a project at the same time.
 */

// jsdom has no matchMedia, and the sidebar asks it for the viewport width.
beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

// No setup file registers testing-library's automatic cleanup, so without this
// each render stacks on the last and a query finds buttons from earlier tests.
afterEach(cleanup);

function sidebarAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar collapsed={false} mobileOpen={false} isMobileViewport={false} />
    </MemoryRouter>,
  );
}

/**
 * Whether any button carrying this label is marked current.
 *
 * All of them, because the sidebar renders its labels for both the mobile and
 * the desktop layout, and the question is about the label rather than about
 * which copy of it the test happened to find.
 *
 * Matched as whole class tokens, not as substrings. The inactive style carries
 * `hover:bg-blue-50/50`, which contains the active class as a substring, so a
 * substring test reports every button as highlighted.
 */
/** The classes only an active nav button carries, light and dark. */
const ACTIVE_CLASSES = ["bg-blue-50", "bg-white/[0.08]"];

function isHighlighted(label: string): boolean {
  return screen
    .getAllByText(label)
    .map((node) => (node.closest("button")?.className ?? "").split(/\s+/))
    .some((classes) => ACTIVE_CLASSES.some((active) => classes.includes(active)));
}

describe("which nav item is highlighted", () => {
  it("marks Projects on the project list", () => {
    sidebarAt("/projects");
    expect(isHighlighted("Projects")).toBe(true);
  });

  it("marks Projects while creating one, not Home", () => {
    // A new project goes into Projects. Pointing at Home would name somewhere
    // the reader is not.
    sidebarAt("/projects/new");
    expect(isHighlighted("Projects")).toBe(true);
    expect(isHighlighted("Home")).toBe(false);
  });

  it("does not mark Projects once inside a project", () => {
    // The one that was wrong: the project has its own row below, and lighting
    // both said the reader was in two places at once.
    sidebarAt("/projects/p_abc/requirements");
    expect(isHighlighted("Projects")).toBe(false);
  });

  it("marks Home only on Home", () => {
    sidebarAt("/workspace");
    expect(isHighlighted("Home")).toBe(true);
    expect(isHighlighted("Projects")).toBe(false);
  });
});
