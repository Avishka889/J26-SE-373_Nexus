import type { ReactElement } from "react";
import { cleanup, fireEvent, render as renderPlain, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Project } from "@/types/project";
import { extractDocument } from "@/entities/document/api";
import type { PhaseModel } from "@/entities/settings";
import { RequirementsInput } from "./RequirementsInput";

// Explicit because this suite runs without vitest's globals, which is what
// Testing Library's own automatic cleanup hooks itself onto: without this the
// first render stays in the document and the second query finds two composers.
afterEach(cleanup);

/**
 * A read that never finishes by default, so the window between picking a file
 * and having its text can be asserted on. In the product that window is
 * seconds: a PDF goes to the orchestrator with a sixty second timeout, and the
 * composer unmounts on submit, taking the in flight read with it.
 *
 * Wrapped in `vi.fn()`, not a bare arrow function, so one test below can let a
 * single call through with a real resolved read: the composed-versus-typed
 * distinction only exists once a document's text has actually arrived, and a
 * read that never finishes can never demonstrate that.
 */
vi.mock("@/entities/document/api", () => ({
  extractDocument: vi.fn(() => new Promise(() => {})),
}));

const project: Project = {
  id: "p1",
  name: "Pharmacy",
  description: "",
  status: "draft",
  createdAt: "2026-08-14T09:00:00.000Z",
  updatedAt: "2026-08-14T09:00:00.000Z",
  requirementText: "",
  requirementChat: [],
  files: [],
  reqPhase: "input",
  progress: 0,
  techStack: [],
  color: "blue",
};

const phases = vi.hoisted(() => ({ models: [] as PhaseModel[] }));

vi.mock("@/entities/settings/models", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/entities/settings/models")>()),
  phaseModels: vi.fn(async () => phases.models),
}));

/** The box reads the phases' models, through a query, and links to Settings. */
function render(ui: ReactElement) {
  return renderPlain(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    ),
  });
}

function attach(container: HTMLElement) {
  const input = container.querySelector('input[type="file"]');
  if (!input) throw new Error("The composer has no file input.");
  fireEvent.change(input, {
    target: { files: [new File(["# Brief"], "brief.md", { type: "text/markdown" })] },
  });
}

describe("RequirementsInput", () => {
  it("will not submit while a document is still being read", () => {
    const onSubmit = vi.fn();
    const { container } = render(<RequirementsInput project={project} onSubmit={onSubmit} />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "Record a dispense." } });

    attach(container);

    // The composed text is the typed sentence alone at this instant, so a
    // submit here would start the run on it and drop the document without
    // recording that it existed.
    const submit = screen.getByRole("button", { name: /reading/i });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(submit);
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the typed text when nothing is being read", () => {
    const onSubmit = vi.fn();
    render(<RequirementsInput project={project} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Record a dispense." } });

    const submit = screen.getByRole("button", { name: /analyze/i });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);

    expect(onSubmit).toHaveBeenCalledWith("Record a dispense.", [], "Record a dispense.");
  });

  it("hands over the typed text, not the composed string, when a document is attached", async () => {
    // This composer's third argument has no consumer yet: its only caller,
    // `features/requirements/page.tsx`, takes two arguments and drops it, so
    // unlike the sibling composer nothing here derives a name or a description
    // from it. What this pins is the composer's half of the contract, which is
    // the half that has to already be right on the day a caller reads it. Every
    // test above either attaches nothing or never lets the read resolve, so in
    // all of them the composed string and the typed string are the same value;
    // only a resolved read, joined onto typed text, can tell the two apart.
    const onSubmit = vi.fn();
    const { container } = render(<RequirementsInput project={project} onSubmit={onSubmit} />);

    const file = new File(["Dispensing must be recorded."], "brief.md", { type: "text/markdown" });
    // The real extractor, not a hand written stand in for its output: this
    // module is otherwise mocked never to resolve, so one call is let through
    // with the real shape rather than a guess at what `Attachment` looks like.
    const real = await vi.importActual<typeof import("@/entities/document/api")>(
      "@/entities/document/api",
    );
    vi.mocked(extractDocument).mockResolvedValueOnce(await real.extractDocument(file));

    const input = container.querySelector('input[type="file"]');
    if (!input) throw new Error("The composer has no file input.");
    fireEvent.change(input, { target: { files: [file] } });

    // The chip shows the filename the instant a file is picked, reading or
    // not, so it cannot say the read is done. The submit button's accessible
    // name can: it only stops saying "Reading" once `readingCount` is back to
    // zero, which is the same condition the disabled test above relies on.
    const submit = await screen.findByRole("button", { name: /analyze/i });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Pharmacy system." } });
    fireEvent.click(submit);

    expect(onSubmit).toHaveBeenCalledWith(
      "Pharmacy system.\n\nDispensing must be recorded.",
      ["brief.md"],
      "Pharmacy system.",
    );
  });
});

/**
 * What the run a send starts runs on, said under the box, as other chat tools
 * name their model in the box: sending starts the project's design run.
 */
describe("the requirements box, and what the run it starts runs on", () => {
  afterEach(() => {
    phases.models = [];
  });

  it("says the design phase's model and level, with a way to where the level is chosen", async () => {
    phases.models = [
      {
        phase: "Requirements and Design",
        key: "design",
        model: "deepseek:deepseek-flash",
        thinking: "high",
        thinkingChosen: true,
        thinkingApplies: true,
      },
    ];
    render(<RequirementsInput project={project} onSubmit={vi.fn()} />);

    expect(
      await screen.findByText("Next run: deepseek:deepseek-flash, thinking on, high effort."),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Choose how hard each phase thinks, in Settings" }),
    ).toBeTruthy();
  });
});
