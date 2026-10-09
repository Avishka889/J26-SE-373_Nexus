import { Brain } from "lucide-react";
import {
  THINKING_LEVELS,
  levelRecorded,
  usePhaseModels,
  type LastRun,
  type PhaseModel,
  type ThinkingLevel,
} from "@/entities/settings";
import { messageOf } from "@/lib/http";
import { Note } from "@/shared/ui/phase";
import { thinkingWords } from "@/shared/utils/modelWords";
import { formatWhen } from "@/shared/utils/time";
import { useChooseThinking } from "../hooks";
import { SettingsPanel } from "./SettingsPanel";

/** Each level as the choice reads, in the words the runs record it in. */
const LEVEL_LABELS: Record<ThinkingLevel, string> = {
  off: "Off",
  low: "On, low effort",
  high: "On, high effort",
  max: "On, max effort",
};

/**
 * The model each phase runs, shown as it is, and how hard each phase thinks,
 * chosen here.
 *
 * The tab once offered OpenAI and Claude, a temperature and a key, and saved a
 * choice nothing read: every run used the model the platform is configured
 * with, and records which one in its "Run started" entry. So the model is
 * shown and not offered. Thinking is offered, because the runs read it (3B):
 * each phase's next run starts at the level chosen here, and a choice is
 * offered only where a level changes what the phase sends.
 */
export function AiTab() {
  const models = usePhaseModels();

  return (
    <SettingsPanel
      icon={Brain}
      title="AI models"
      description="The model each phase runs, which the platform's configuration sets, and how hard each phase thinks, which you choose. Every run records what it used."
    >
      {models.isError ? (
        <Note>The models could not be read: {messageOf(models.error)}</Note>
      ) : !models.data ? (
        <Note>Reading the models...</Note>
      ) : (
        <>
          <dl className="divide-y divide-[color:var(--tp-line)] rounded-xl border border-[color:var(--tp-line)]">
            {models.data.map((one) => (
              // One group per phase, so every term and description sits where a
              // definition list allows; the choice and the last run take a line
              // each.
              <div
                key={one.phase}
                className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 px-3.5 py-2.5"
              >
                <dt className="text-[13px] font-medium text-[color:var(--tp-ink)]">{one.phase}</dt>
                <dd className="font-mono text-[12.5px] text-[color:var(--tp-ink-2)]">
                  {one.model}
                  {!choosable(one) && one.thinking !== undefined && (
                    <span className="font-sans">
                      ,{" "}
                      {one.thinking === null
                        ? "thinking as its service is configured"
                        : thinkingWords(one.thinking)}
                    </span>
                  )}
                </dd>
                {choosable(one) && (
                  <dd className="basis-full">
                    <ThinkingChoice phase={one} />
                  </dd>
                )}
                {one.lastRun !== undefined && (
                  <dd className="tp-den basis-full break-words text-[12px]">
                    {one.lastRun ? (
                      <LastRunLine run={one.lastRun} />
                    ) : (
                      "No run in this phase has recorded what it ran on yet."
                    )}
                  </dd>
                )}
              </div>
            ))}
          </dl>
          {models.data.some(choosable) && (
            <p className="tp-den mt-3 text-[12px] leading-relaxed">
              A level applies from the phase&apos;s next run. A run keeps the level it started at,
              including when changes requested at its review regenerate it. Thinking writes out its
              reasoning before it answers, which is billed as output and takes longer.
            </p>
          )}
        </>
      )}
    </SettingsPanel>
  );
}

/** A level changes what this phase sends, and the server said under which key to save it. */
function choosable(phase: PhaseModel): phase is PhaseModel & { key: NonNullable<PhaseModel["key"]> } {
  return Boolean(phase.thinkingApplies && phase.key);
}

function ThinkingChoice({ phase }: { phase: PhaseModel & { key: NonNullable<PhaseModel["key"]> } }) {
  const choose = useChooseThinking();
  const saving = choose.isPending;
  // Shown as asked while it saves, then as the server reads it back.
  const level = saving ? choose.variables.level : levelRecorded(phase.thinking ?? null);
  const id = `thinking-${phase.key}`;

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
      <label htmlFor={id} className="text-[color:var(--tp-ink-2)]">
        Thinking<span className="sr-only"> for {phase.phase}</span>
      </label>
      <select
        id={id}
        className="min-w-0 rounded-md border border-border bg-background px-2 py-1 text-foreground"
        value={level}
        disabled={saving}
        onChange={(event) =>
          choose.mutate({ key: phase.key, level: event.target.value as ThinkingLevel })
        }
      >
        {THINKING_LEVELS.map((one) => (
          <option key={one} value={one}>
            {LEVEL_LABELS[one]}
          </option>
        ))}
      </select>
      <span className="tp-den text-[12px]" role="status">
        {saving
          ? "Saving..."
          : choose.isError
            ? `Not saved: ${messageOf(choose.error)}`
            : phase.thinkingChosen
              ? "Your choice"
              : "As the platform is configured"}
      </span>
    </div>
  );
}

function LastRunLine({ run }: { run: LastRun }) {
  return (
    <>
      Last run: <span className="font-mono">{run.model}</span>
      {run.thinking ? `, ${thinkingWords(run.thinking)}` : ""}, on {run.project}, {formatWhen(run.startedAt)}.
    </>
  );
}
