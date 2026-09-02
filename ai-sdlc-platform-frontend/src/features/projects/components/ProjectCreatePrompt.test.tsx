import type { ReactElement } from "react";
import { cleanup, fireEvent, render as renderPlain, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { extractDocument } from "@/entities/document/api";
import type { PhaseModel } from "@/entities/settings";
import { ProjectCreatePrompt } from "./ProjectCreatePrompt";

// Explicit because this suite runs without vitest's globals, which is what
// Testing Library's own automatic cleanup hooks itself onto: without this the
// first render stays in the document and the second query finds two composers.
afterEach(cleanup);

/**
 * A read that never finishes by default, so the window between picking a file
 * and having its text can be asserted on. Enter submits this composer, so that
 * window is one keystroke wide.
 *
 * Wrapped in `vi.fn()`, not a bare arrow function, so one test below can let a
 * single call through with a real resolved read: the composed-versus-typed
 * distinction only exists once a document's text has actually arrived, and a
 * read that never finishes can never demonstrate that.
 */
vi.mock("@/entities/document/api", () => ({
  extractDocument: vi.fn(() => new Promise(() => {})),
}));

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

describe("ProjectCreatePrompt", () => {
  it("will not submit while a document is still being read", () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <ProjectCreatePrompt firstName="Alex" isDark={false} onSubmit={onSubmit} />,
    );
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "Record a dispense." } });

    attach(container);

    // Both paths, because Enter reaches the same handler the button does and
    // this composer creates the project and navigates away: whatever was still
    // being read is gone with the composer.
    const submit = screen.getByRole("button", { name: /waiting/i });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(submit);
    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the typed text when nothing is being read", () => {
    const onSubmit = vi.fn();
    render(<ProjectCreatePrompt firstName="Alex" isDark={false} onSubmit={onSubmit} />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "Record a dispense." } });

    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(onSubmit).toHaveBeenCalledWith("Record a dispense.", [], "Record a dispense.");
  });

  it("hands over what was typed, not just whether anything was", async () => {
    // The composed string cannot say which part of itself the reader wrote once a
    // document's text is joined onto it, so the composer passes the typed text
    // through. Both the name and the description are derived from it.
    const onSubmit = vi.fn();
    render(<ProjectCreatePrompt firstName="Alex" isDark={false} onSubmit={onSubmit} />);

    const box = screen.getByPlaceholderText(/Describe a product/i);
    fireEvent.change(box, { target: { value: "Build a pharmacy dispensing system." } });
    fireEvent.keyDown(box, { key: "Enter" });

    expect(onSubmit).toHaveBeenCalledWith(
      "Build a pharmacy dispensing system.",
      [],
      "Build a pharmacy dispensing system.",
    );
  });

  it("hands over the typed text, not the composed string, when a document is attached", async () => {
    // The whole point of the third argument. Every test above either attaches
    // nothing or never lets the read resolve, so in all of them the composed
    // string and the typed string are the same value: passing `composed` in
    // place of `typed` would pass every one of them and silently reship the
    // exact bug this task exists to fix. Only a resolved read, joined onto
    // typed text, can tell the two apart.
    const onSubmit = vi.fn();
    const { container } = render(
      <ProjectCreatePrompt firstName="Alex" isDark={false} onSubmit={onSubmit} />,
    );

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
    // name can: it only stops saying "Waiting" once `readingCount` is back to
    // zero, which is the same condition the disabled tests above rely on.
    const box = screen.getByPlaceholderText(/Describe a product/i);
    await screen.findByRole("button", { name: "Analyze requirements" });
    fireEvent.change(box, { target: { value: "Pharmacy system." } });
    fireEvent.keyDown(box, { key: "Enter" });

    expect(onSubmit).toHaveBeenCalledWith(
      "Pharmacy system.\n\nDispensing must be recorded.",
      ["brief.md"],
      "Pharmacy system.",
    );
  });
});

/**
 * A refused create said nothing: the composer's comment said "the caller shows
 * the error" and neither caller did. And it offered Plan and a microphone that
 * did nothing, and a "From repo" start for an import that does not exist.
 */
describe("ProjectCreatePrompt when the create fails, and what it offers", () => {
  it("says the project was not created, why, and keeps the text", async () => {
    const onSubmit = vi.fn(() => Promise.reject(new Error("The server is restarting.")));
    render(<ProjectCreatePrompt firstName="Alex" isDark={false} onSubmit={onSubmit} />);
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Record a dispense." } });

    fireEvent.click(screen.getByRole("button", { name: "Analyze requirements" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "The project was not created. The server is restarting.",
    );
    expect(textarea.value).toBe("Record a dispense.");
    expect((screen.getByRole("button", { name: "Analyze requirements" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("offers only what works", () => {
    render(<ProjectCreatePrompt firstName="Alex" isDark={false} onSubmit={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /plan/i })).toBeNull();
    expect(screen.queryByText("From repo")).toBeNull();
    for (const button of screen.getAllByRole("button")) {
      // Every control says what it is: the microphone had no name and no use.
      expect(button.getAttribute("aria-label") || button.textContent?.trim() || button.title).toBeTruthy();
    }
  });
});

/**
 * What the run a send starts runs on, said under the box, as other chat tools
 * name their model in the box: a project's first run is its design's.
 */
describe("The start screen's prompt, and what the run it starts runs on", () => {
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
    render(<ProjectCreatePrompt firstName="Alex" isDark={false} onSubmit={vi.fn()} />);

    expect(
      await screen.findByText("Next run: deepseek:deepseek-flash, thinking on, high effort."),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Choose how hard each phase thinks, in Settings" }),
    ).toBeTruthy();
  });
});
