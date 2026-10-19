import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const state = vi.hoisted(() => ({
  list: [] as unknown[],
  load: { status: "loaded", error: null } as { status: string; error: string | null },
}));

vi.mock("@/entities/project", () => ({
  useProjectsList: () => state.list,
  useProjectsLoad: () => state.load,
  projectHomePath: (p: { id: string }) => `/projects/${p.id}/requirements`,
}));
vi.mock("@/app/layout/AccountMenu", () => ({ AccountMenu: () => null }));

const { Sidebar } = await import("./Sidebar");

beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
});

afterEach(cleanup);

const projects = (count: number) =>
  Array.from({ length: count }, (_, i) => ({ id: `p${i + 1}`, name: `Project ${i + 1}`, color: "#3b82f6", progress: 0 }));

function sidebar() {
  render(
    <MemoryRouter initialEntries={["/workspace"]}>
      <Routes>
        <Route path="/projects" element={<p>Every project</p>} />
        <Route path="*" element={<Sidebar collapsed={false} mobileOpen={false} isMobileViewport={false} />} />
      </Routes>
    </MemoryRouter>,
  );
}

const recent = () => screen.getByRole("list", { name: "Recent projects" });

/**
 * The sidebar listed five projects and no way to the rest but the Projects
 * page, and showed nothing at all while the list was being read.
 */
describe("the sidebar's recent projects", () => {
  it("lists the ten most recent, in a list that scrolls on its own", () => {
    state.list = projects(14);
    state.load = { status: "loaded", error: null };
    sidebar();

    const rows = within(recent()).getAllByRole("button");
    expect(rows.map((row) => row.textContent)).toEqual(
      Array.from({ length: 10 }, (_, i) => `Project ${i + 1}0%`),
    );
    expect(recent().className.split(/\s+/)).toEqual(expect.arrayContaining(["overflow-y-auto", "min-h-0"]));
  });

  it("offers the rest when there are more than it lists", () => {
    state.list = projects(14);
    sidebar();
    fireEvent.click(screen.getByRole("button", { name: "View all 14 projects" }));

    expect(screen.getByText("Every project")).toBeTruthy();
  });

  it("offers nothing more when it lists them all", () => {
    state.list = projects(10);
    sidebar();

    expect(within(recent()).getAllByRole("button")).toHaveLength(10);
    expect(screen.queryByRole("button", { name: /view all/i })).toBeNull();
  });

  it("says the list is being read while it is", () => {
    state.list = [];
    state.load = { status: "loading", error: null };
    sidebar();

    expect(screen.getByRole("status", { name: "Loading your projects" })).toBeTruthy();
  });

  it("shows no placeholder for an account with no projects", () => {
    state.list = [];
    state.load = { status: "loaded", error: null };
    sidebar();

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("list", { name: "Recent projects" })).toBeNull();
  });
});
