import type { PhaseThinking } from "@sdlc/contracts-ts";
import { isLive } from "@/lib/env";
import { http } from "@/lib/http";
import { thinkingWords } from "@/shared/utils/modelWords";

/** A phase as the account's settings name it: the keys of `ai.thinking`. */
export type PhaseKey = keyof PhaseThinking;

/** How hard a phase can be asked to think, as the settings save it. */
export type ThinkingLevel = NonNullable<PhaseThinking[PhaseKey]>;

/** In the order a reader meets them: off, then each effort. */
export const THINKING_LEVELS: readonly ThinkingLevel[] = ["off", "low", "high", "max"];

/** Where the levels are chosen, as a link from anywhere a phase's level is shown. */
export const THINKING_SETTINGS_PATH = "/settings?tab=ai";

/**
 * The newest of the owner's runs in a phase that recorded what it ran on: the
 * configuration says what the next run will use, and only a run says what one
 * did use.
 */
export interface LastRun {
  model: string;
  /** "disabled", "default", a level, or null where the run could not say. */
  thinking: string | null;
  startedAt: string;
  project: string;
}

/** One phase, the model it runs, and how hard it thinks. */
export interface PhaseModel {
  phase: string;
  /** The key a choice for this phase is saved under. Absent in the demo. */
  key?: PhaseKey;
  model: string;
  /**
   * Where a choice applies, the level the phase's next run starts at: the
   * account's choice, or as configured. Where none does, what the phase's
   * requests say about thinking at every level, or null where the platform
   * cannot say. Absent in the demo.
   */
  thinking?: string | null;
  /** The level is the account's choice rather than the configuration's. */
  thinkingChosen?: boolean;
  /**
   * A level changes what this phase sends, so a choice means something. False
   * for a phase run as a separate service, and for a model whose provider
   * takes no thinking setting.
   */
  thinkingApplies?: boolean;
  /** Absent in the demo, and null until a run in the phase has recorded it. */
  lastRun?: LastRun | null;
}

/** The demo's answer, for a run on fixtures, where every phase is canned. */
const DEMO_MODELS: PhaseModel[] = [
  { phase: "Requirements and Design", model: "demo (no model)" },
  { phase: "Code Generation", model: "demo (no model)" },
  { phase: "Testing and Security", model: "demo (no model)" },
  { phase: "Deployment", model: "demo (no model)" },
];

export async function phaseModels(): Promise<PhaseModel[]> {
  return isLive("settings") ? http.get<PhaseModel[]>("/settings/models") : DEMO_MODELS;
}

/**
 * The level a run was asked at, read back from what it recorded, as the
 * orchestrator reads it (`level_recorded`): a level is the record itself, and
 * anything else ("disabled", "default", nothing) was off.
 */
export function levelRecorded(thinking: string | null): ThinkingLevel {
  return THINKING_LEVELS.find((level) => level === thinking) ?? "off";
}

/** What a phase snapshot says its run started on. */
export interface RunSetup {
  model: string | null;
  thinking: string | null;
}

/** The line under a phase's chat box, and where its level is chosen when it can be. */
export interface RunsOn {
  text: string;
  to?: string;
}

/**
 * What a phase's chat box says a send runs on, or null where nothing can be said.
 *
 * A send at a waiting review requests changes, and they regenerate inside that
 * run at the level it started at: a choice made since applies from the next
 * run (3B). Any other send, and the phase's next run, start at the phase's
 * level now. So while a review waits the box names the waiting run's setup,
 * and the next run's beside it where that differs; otherwise the next run's.
 */
export function runsOn(phase: PhaseModel | undefined, waiting: RunSetup | null): RunsOn | null {
  const to = phase?.thinkingApplies ? THINKING_SETTINGS_PATH : undefined;
  const next = phase ? nextRun(phase) : null;
  const now = waiting ? waitingRun(phase, waiting) : null;
  if (now) {
    const after = next && !sameSetup(now, next) ? ` Next run: ${words(next, now.model)}.` : "";
    return { text: `This run: ${words(now)}.${after}`, to };
  }
  return next ? { text: `Next run: ${words(next)}.`, to } : null;
}

interface Setup {
  model: string | null;
  /** Words for its thinking, or null where they are not known. */
  thinking: string | null;
}

function nextRun(phase: PhaseModel): Setup {
  return { model: phase.model, thinking: phaseThinking(phase) };
}

/**
 * The waiting run regenerates on the phase's model now, at its own level where
 * a level applies; where none does, as the phase's requests always say.
 */
function waitingRun(phase: PhaseModel | undefined, run: RunSetup): Setup {
  if (!phase) {
    return { model: run.model, thinking: run.thinking ? thinkingWords(run.thinking) : null };
  }
  return {
    model: phase.model,
    thinking: phase.thinkingApplies
      ? thinkingWords(levelRecorded(run.thinking))
      : phaseThinking(phase),
  };
}

function phaseThinking(phase: PhaseModel): string | null {
  if (phase.thinking === undefined) return null;
  // Null where the phase runs as a separate service, which this side cannot read.
  return phase.thinking === null
    ? "thinking as its service is configured"
    : thinkingWords(phase.thinking);
}

function sameSetup(a: Setup, b: Setup): boolean {
  return a.model === b.model && a.thinking === b.thinking;
}

/** "deepseek:deepseek-flash, thinking off", leaving out the model where it was just named. */
function words(setup: Setup, named: string | null = null): string {
  const parts = [setup.model === named ? null : setup.model, setup.thinking].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "not recorded";
}
