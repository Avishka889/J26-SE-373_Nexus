import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { projectsApi } from "@/entities/project";
import { useUiStore } from "@/store/ui";
import { ProjectTitle } from "./ProjectTitle";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * A project's name could not be changed anywhere: the server accepted a new
 * name, and no page sent one.
 */
describe("renaming a project", () => {
  it("saves the new name on Enter", async () => {
    const update = vi.spyOn(projectsApi, "update").mockResolvedValue(undefined);
    render(<ProjectTitle projectId="p1" name="Build a web app for" isDark={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Rename the project" }));
    const field = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(field, { target: { value: "  Book   Tracker " } });
    fireEvent.submit(field.closest("form")!);

    await waitFor(() => expect(update).toHaveBeenCalledWith("p1", { name: "Book Tracker" }));
  });

  it("leaves the name as it was on Escape", () => {
    const update = vi.spyOn(projectsApi, "update");
    render(<ProjectTitle projectId="p1" name="Book Tracker" isDark={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Rename the project" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Project name" }), { key: "Escape" });

    expect(screen.getByRole("heading", { name: "Book Tracker" })).toBeTruthy();
    expect(update).not.toHaveBeenCalled();
  });

  it("says why when the server refuses, and keeps the edit open", async () => {
    useUiStore.setState({ toasts: [] });
    vi.spyOn(projectsApi, "update").mockRejectedValue(new Error("The server is restarting."));
    render(<ProjectTitle projectId="p1" name="Book Tracker" isDark={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Rename the project" }));
    const field = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(field, { target: { value: "Library" } });
    fireEvent.submit(field.closest("form")!);

    await waitFor(() =>
      expect(useUiStore.getState().toasts[0]?.title).toBe("The project was not renamed"),
    );
    expect((screen.getByRole("textbox", { name: "Project name" }) as HTMLInputElement).value).toBe("Library");
  });
});
