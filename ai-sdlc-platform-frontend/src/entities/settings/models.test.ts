import { describe, expect, it } from "vitest";
import {
  THINKING_SETTINGS_PATH,
  levelRecorded,
  runsOn,
  type PhaseModel,
  type RunSetup,
} from "./models";

const FLASH = "deepseek:deepseek-flash";

/** A phase whose requests a level changes, as a DeepSeek phase run in process is. */
function phase(thinking: string, fields: Partial<PhaseModel> = {}): PhaseModel {
  return {
    phase: "Testing and Security",
    key: "testing",
    model: FLASH,
    thinking,
    thinkingChosen: true,
    thinkingApplies: true,
    ...fields,
  };
}

function run(thinking: string | null, model: string | null = FLASH): RunSetup {
  return { model, thinking };
}

/**
 * The chat box says what a send runs on, as a chat box in other tools names
 * its model. A send at a waiting review requests changes, which regenerate in
 * that run at the level it started at; any other send, and the phase's next
 * run, start at the level chosen now (3B). Saying the next run's level while a
 * review waits would tell the reader a send thinks when it does not.
 */
describe("what a phase's chat box says a send runs on", () => {
  it("names the next run's model and level where no review waits, with a way to change it", () => {
    expect(runsOn(phase("high"), null)).toEqual({
      text: `Next run: ${FLASH}, thinking on, high effort.`,
      to: THINKING_SETTINGS_PATH,
    });
  });

  it("names the waiting run's level, and the next run's beside it where a choice since differs", () => {
    expect(runsOn(phase("high"), run("disabled"))?.text).toBe(
      `This run: ${FLASH}, thinking off. Next run: thinking on, high effort.`,
    );
  });

  it("says only the waiting run's where the next run would be the same", () => {
    expect(runsOn(phase("high"), run("high"))?.text).toBe(
      `This run: ${FLASH}, thinking on, high effort.`,
    );
  });

  // The orchestrator regenerates such a run at off, as it reads its record back.
  it("reads a run that recorded no thinking as one that was asked at off", () => {
    expect(runsOn(phase("off"), run(null))?.text).toBe(`This run: ${FLASH}, thinking off.`);
  });

  // The regeneration runs on the phase's model now, which a restart may have changed.
  it("names the model the regeneration will run on, not the one the run started on", () => {
    expect(runsOn(phase("off"), run("disabled", "deepseek:deepseek-chat"))?.text).toBe(
      `This run: ${FLASH}, thinking off.`,
    );
  });

  it("offers no way to change a phase whose requests no level changes, and says what they say", () => {
    const provider = phase("default", { thinkingApplies: false, thinkingChosen: false });
    expect(runsOn(provider, null)).toEqual({
      text: `Next run: ${FLASH}, thinking left to the provider.`,
      to: undefined,
    });
    expect(runsOn(provider, run("default"))?.text).toBe(
      `This run: ${FLASH}, thinking left to the provider.`,
    );
  });

  it("says a phase run as a separate service thinks as that service is configured", () => {
    const service = phase("", {
      model: "whatever http://localhost:8003 is running",
      thinking: null,
      thinkingApplies: false,
      thinkingChosen: false,
    });
    expect(runsOn(service, null)?.text).toBe(
      "Next run: whatever http://localhost:8003 is running, thinking as its service is configured.",
    );
  });

  it("says what the waiting run recorded until the phase has been read, and nothing before either", () => {
    expect(runsOn(undefined, run("high"))).toEqual({
      text: `This run: ${FLASH}, thinking on, high effort.`,
      to: undefined,
    });
    expect(runsOn(undefined, null)).toBeNull();
  });
});

describe("the level a run was asked at, read back from its record", () => {
  it("is the record where the record is a level, and off otherwise", () => {
    expect(levelRecorded("max")).toBe("max");
    expect([levelRecorded("disabled"), levelRecorded("default"), levelRecorded(null)]).toEqual([
      "off",
      "off",
      "off",
    ]);
  });
});
