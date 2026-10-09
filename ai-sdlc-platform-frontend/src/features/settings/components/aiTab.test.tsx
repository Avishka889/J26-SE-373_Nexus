import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  forgetSettings,
  getSettingsSnapshot,
  settingsApi,
  type PhaseModel,
} from "@/entities/settings";

const answer = vi.hoisted(() => ({ models: [] as PhaseModel[], reads: 0 }));

vi.mock("@/entities/settings/models", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/entities/settings/models")>()),
  phaseModels: vi.fn(async () => {
    answer.reads += 1;
    return answer.models;
  }),
}));

const { AiTab } = await import("./AiTab");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  forgetSettings();
});

function show() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AiTab />
    </QueryClientProvider>,
  );
}

const FLASH = "deepseek:deepseek-flash";

/** A phase whose requests a level changes, as a DeepSeek phase run in process is. */
function choosable(fields: Partial<PhaseModel>): PhaseModel {
  return {
    phase: "Requirements and Design",
    key: "design",
    model: FLASH,
    thinking: "off",
    thinkingChosen: false,
    thinkingApplies: true,
    ...fields,
  };
}

/**
 * The tab offered OpenAI and Claude and saved a choice nothing read, while
 * every run used the platform's configured model. The model is shown, not
 * offered; thinking is offered, because the runs read it.
 */
describe("the AI model tab", () => {
  it("shows the model each phase runs, and offers nothing to change where nothing would", async () => {
    answer.models = [
      { phase: "Requirements and Design", model: FLASH },
      { phase: "Testing and Security", model: FLASH },
    ];
    show();

    expect(await screen.findByText("Requirements and Design")).toBeTruthy();
    expect(screen.getAllByText(FLASH).length).toBe(2);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: /save/i })).toBeNull();
  });

  // The configuration says what the next run will use; only a run says what
  // one did use, so the tab shows the phase's newest recorded run beside it.
  it("says what each phase's newest recorded run ran on, and when none has", async () => {
    answer.models = [
      {
        phase: "Requirements and Design",
        model: FLASH,
        lastRun: {
          model: FLASH,
          thinking: "disabled",
          startedAt: "2026-10-04T09:12:00+00:00",
          project: "Ledger",
        },
      },
      { phase: "Deployment", model: FLASH, lastRun: null },
    ];
    show();

    expect(await screen.findByText(/thinking off, on Ledger,/)).toBeTruthy();
    expect(screen.getByText("No run in this phase has recorded what it ran on yet.")).toBeTruthy();
  });

  it("says how hard each phase is set to think where no level can be chosen", async () => {
    answer.models = [
      { phase: "Requirements and Design", model: FLASH, thinking: "off" },
      { phase: "Code Generation", model: FLASH, thinking: "high" },
    ];
    show();

    expect(await screen.findByText(", thinking off")).toBeTruthy();
    expect(screen.getByText(", thinking on, high effort")).toBeTruthy();
  });

  // The `ai` section saves whole, so a choice for one phase must not clear
  // another's; and the tab reads the phases again, so it shows what the server
  // holds rather than what was asked for.
  it("offers each phase a level, and saves one with the other phases' choices", async () => {
    await settingsApi.chooseThinking("code", "low");
    answer.models = [
      choosable({}),
      choosable({
        phase: "Code Generation",
        key: "code",
        thinking: "low",
        thinkingChosen: true,
      }),
    ];
    show();

    const design = (await screen.findByLabelText(
      "Thinking for Requirements and Design",
    )) as HTMLSelectElement;
    expect(design.value).toBe("off");
    expect(
      (screen.getByLabelText("Thinking for Code Generation") as HTMLSelectElement).value,
    ).toBe("low");
    expect(screen.getByText("As the platform is configured")).toBeTruthy();
    expect(screen.getByText("Your choice")).toBeTruthy();
    const read = answer.reads;

    fireEvent.change(design, { target: { value: "high" } });

    await waitFor(() =>
      expect(getSettingsSnapshot().ai.thinking).toEqual({
        design: "high",
        code: "low",
        testing: null,
        deployment: null,
      }),
    );
    await waitFor(() => expect(answer.reads).toBeGreaterThan(read));
  });

  it("says a level was not saved, and goes on showing the one the server holds", async () => {
    vi.spyOn(settingsApi, "chooseThinking").mockRejectedValue(
      new Error("503 Service Unavailable"),
    );
    answer.models = [choosable({})];
    show();
    const design = (await screen.findByLabelText(
      "Thinking for Requirements and Design",
    )) as HTMLSelectElement;

    fireEvent.change(design, { target: { value: "max" } });

    expect(await screen.findByText("Not saved: 503 Service Unavailable")).toBeTruthy();
    expect(design.value).toBe("off");
  });

  // A phase run as a separate service thinks as that service is configured, and
  // a provider other than DeepSeek is sent the same request at every level: a
  // choice offered there would be one nothing reads.
  it("offers no level where none changes what a phase sends, and says what it sends", async () => {
    answer.models = [
      choosable({
        phase: "Testing and Security",
        key: "testing",
        model: "openai:gpt-4o-mini",
        thinking: "default",
        thinkingApplies: false,
      }),
      choosable({
        phase: "Deployment",
        key: "deployment",
        model: "whatever http://localhost:8004 is running",
        thinking: null,
        thinkingApplies: false,
      }),
    ];
    show();

    expect(await screen.findByText(", thinking left to the provider")).toBeTruthy();
    expect(screen.getByText(", thinking as its service is configured")).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
