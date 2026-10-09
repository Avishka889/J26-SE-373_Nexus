import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CircleSlash, Clock, History, RefreshCw, Sparkles } from "lucide-react";
import { Button } from "@/shared/ui/primitives";
import { Note, Panel } from "@/shared/ui/phase";
import { isOutdated, type StageChrome, type StageChromeState } from "./types";
import { ModelUseNote } from "./ModelUseNote";
import { Spinner } from "@/shared/ui/Spinner";

/**
 * One guard for every stage, rather than each stage inventing its own empty,
 * generating and failed screens. A stage panel opens with this and only renders
 * its content when there is content to render.
 *
 * Written for the design phase and then needed unchanged by the code phase,
 * which is why the stage id type and the words for a version are parameters.
 *
 * A stage opens at its top. Moving on from the bottom of a long stage, with
 * the footer's Next or a chevron in the pinned rail, left the column where it
 * was, so the next stage opened wherever the last one had been read to. When
 * the stage changes and the column is below the new stage's top, it scrolls
 * back to it, just under the pinned rail; above it, nothing moves.
 */
export function StageShell<Id extends string>(props: {
  chrome: StageChrome<Id>;
  stage: StageChromeState;
  stageId: Id;
  version: number;
  /** May resolve when the server has answered, which keeps Try again busy until then. */
  onRetry: (stageId: Id) => void | Promise<unknown>;
  /** The phase's run stopped, so a stage still pending is one it never reached. */
  notReached?: boolean;
  /**
   * The stages this one reads that were generated again after it was computed,
   * in the phase's words: it still reflects what it read then.
   */
  computedBefore?: string[];
  /**
   * The stage the run is working on, in the phase's words, when it is not this
   * one. A run marks every stage generating from its start, so a stage queued
   * behind the working one says so, rather than showing a spinner of its own.
   */
  waitingFor?: string;
  /**
   * What a stage that has not run yet waits on, when it is not the stage before
   * it: while the design waits on its questions, the stage before has finished.
   */
  pendingNote?: string;
  children: ReactNode;
}) {
  const top = useRef<HTMLDivElement>(null);
  const shown = useRef(props.stageId);
  useEffect(() => {
    if (shown.current === props.stageId) return;
    shown.current = props.stageId;
    const element = top.current;
    const scroller = element?.closest<HTMLElement>("[data-stage-scroller]");
    if (!element || !scroller) return;
    const rail = scroller.querySelector<HTMLElement>("[data-stage-rail]");
    const target =
      element.getBoundingClientRect().top -
      scroller.getBoundingClientRect().top +
      scroller.scrollTop -
      (rail?.offsetHeight ?? 0) -
      12;
    if (scroller.scrollTop > target) scroller.scrollTo({ top: Math.max(0, target) });
  }, [props.stageId]);

  return (
    <div ref={top} data-stage-top>
      <StageBody {...props} />
    </div>
  );
}

/**
 * Busy until the server has answered. A second click while the first request
 * was on its way started a second run of the stage, each paying for its model
 * calls; a refusal makes it usable again, and the page reports the refusal.
 */
/**
 * A stage retried alone regenerates that stage and nothing after it, so the
 * stages that read it went on showing what they computed from the output it
 * replaced. This says so, and computes this one again from what is there now.
 */
function ComputedBeforeBanner({
  stageLabel,
  changed,
  onComputeAgain,
}: {
  stageLabel: string;
  changed: string[];
  onComputeAgain: () => void | Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const computeAgain = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await onComputeAgain();
    } catch {
      // Reported by the page; the button only has to be offered again.
    } finally {
      setBusy(false);
    }
  };
  const names = changed.length === 1 ? changed[0] : `${changed.slice(0, -1).join(", ")} and ${changed[changed.length - 1]}`;
  return (
    <section className="flex flex-wrap items-start gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/5 px-4 py-3.5">
      <History className="mt-0.5 h-4 w-4 shrink-0 text-amber-500 dark:text-amber-400" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
          {stageLabel} was computed before {names} was generated again
        </p>
        <Note className="mt-1">
          It still reflects what it read then. Computing it again reads what is there now; nothing
          else is regenerated.
        </Note>
      </div>
      <Button variant="outline" size="sm" busy={busy} onClick={() => void computeAgain()}>
        <RefreshCw className="h-3.5 w-3.5" />
        Compute again
      </Button>
    </section>
  );
}

function RetryButton({ onRetry }: { onRetry: () => void | Promise<unknown> }) {
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await onRetry();
    } catch {
      // Reported by the page; the button only has to be offered again.
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button variant="primary" size="sm" className="mt-3" busy={busy} onClick={() => void retry()}>
      <RefreshCw className="h-3.5 w-3.5" />
      Try again
    </Button>
  );
}

function StageBody<Id extends string>({
  chrome,
  stage,
  stageId,
  version,
  onRetry,
  notReached,
  computedBefore,
  waitingFor,
  pendingNote,
  children,
}: {
  chrome: StageChrome<Id>;
  stage: StageChromeState;
  stageId: Id;
  /** The phase's current version, for the generating and outdated wording. */
  version: number;
  /** May resolve when the server has answered, which keeps Try again busy until then. */
  onRetry: (stageId: Id) => void | Promise<unknown>;
  notReached?: boolean;
  computedBefore?: string[];
  waitingFor?: string;
  pendingNote?: string;
  children: ReactNode;
}) {
  const meta = chrome.meta[stageId];

  if (stage.status === "pending" && notReached) {
    return (
      <Panel icon={<CircleSlash className="h-4 w-4" />} label={meta.heading} title={meta.blurb}>
        <Note>
          Not reached. The run stopped before this stage, so nothing was generated here. The notice
          above says why, and how to go on.
        </Note>
      </Panel>
    );
  }

  if (stage.status === "pending") {
    return (
      <Panel icon={<Sparkles className="h-4 w-4" />} label={meta.heading} title={meta.blurb}>
        <Note>
          {pendingNote ??
            "This stage has not run yet. It starts once the stage before it finishes, and nothing is created until then."}
        </Note>
      </Panel>
    );
  }

  if (stage.status === "generating") {
    // A first run has written nothing yet, so the server's version is still
    // zero, and "generating from version 0" names a version that does not exist.
    const working = waitingFor
      ? `Starts once ${waitingFor} finishes`
      : version > 0
        ? `Generating from ${chrome.versionNoun} ${version}`
        : "Generating the first version";
    const mark = waitingFor ? (
      <Clock className="h-3.5 w-3.5 text-[color:var(--tp-muted)]" aria-hidden="true" />
    ) : (
      <Spinner size="xs" decorative />
    );
    // What was there stays on screen until it is replaced. The page said so and
    // showed nothing: every stage of a run is generating at once, so "the other
    // stages" it pointed to were empty too.
    if (stage.generatedFromVersion > 0) {
      return (
        <div className="space-y-5">
          <section className="flex flex-wrap items-start gap-3 rounded-2xl border border-blue-500/30 bg-blue-500/5 px-4 py-3.5">
            <span className="mt-0.5">{mark}</span>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">{working}</p>
              <Note className="mt-1">
                Below is {meta.label} as it was at {chrome.versionNoun} {stage.generatedFromVersion},
                until the new one replaces it.
              </Note>
            </div>
          </section>
          {children}
        </div>
      );
    }
    return (
      <Panel
        icon={waitingFor ? <Clock className="h-4 w-4" /> : <Spinner size="sm" tone="accent" decorative />}
        label={meta.heading}
        title={meta.blurb}
      >
        <p className="tp-den flex items-center gap-2">
          {mark}
          {working}
        </p>
        <Note className="mt-3">Nothing was here before, so this fills in when it finishes.</Note>
      </Panel>
    );
  }

  if (stage.status === "skipped") {
    return (
      <Panel icon={<CircleSlash className="h-4 w-4" />} label={meta.heading} title={meta.blurb}>
        <Note>
          {stage.summary?.trim() || "This stage does not apply to what the phase is pointed at."}
        </Note>
        <Note className="mt-3">
          Skipped is not failed and it is not finished. Nothing was produced here and nothing went
          wrong, so there is nothing to retry.
        </Note>
      </Panel>
    );
  }

  if (stage.status === "failed") {
    return (
      <Panel icon={<AlertTriangle className="h-4 w-4" />} label={meta.heading} title={meta.blurb}>
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 px-3.5 py-3">
          <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
            {meta.label} could not be generated
          </p>
          <Note className="mt-1">
            {stage.error ?? "The generator stopped before it produced anything."} Nothing was
            changed, and no decision was recorded.
          </Note>
          <RetryButton onRetry={() => onRetry(stageId)} />
        </div>
      </Panel>
    );
  }

  return (
    <div className="space-y-5">
      {isOutdated(stage, version) && (
        <OutdatedBanner
          stageLabel={meta.label}
          versionNoun={chrome.versionNoun}
          generatedFrom={stage.generatedFromVersion}
          current={version}
        />
      )}
      {computedBefore && computedBefore.length > 0 && (
        <ComputedBeforeBanner
          stageLabel={meta.label}
          changed={computedBefore}
          onComputeAgain={() => onRetry(stageId)}
        />
      )}
      {children}
      {/* Last, under what it describes, so nothing above it moves. */}
      {stage.modelUse && <ModelUseNote use={stage.modelUse} />}
    </div>
  );
}

/**
 * The same treatment the Testing phase uses when a newer build supersedes a
 * decision: amber, an explanation, and no pretence that the stage is wrong,
 * only that it describes an older version.
 */
export function OutdatedBanner({
  stageLabel,
  versionNoun,
  generatedFrom,
  current,
}: {
  stageLabel: string;
  versionNoun: string;
  generatedFrom: number;
  current: number;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-amber-500/30 bg-amber-500/5">
      <div className="flex flex-wrap items-start gap-3 px-4 py-3.5">
        <History className="mt-0.5 h-4 w-4 shrink-0 text-amber-500 dark:text-amber-400" />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
            {stageLabel} was generated from {versionNoun} {generatedFrom}, and it is now at{" "}
            {current}
          </p>
          <Note className="mt-1">
            What you see below still describes the older version. It is kept so nothing
            disappears while the rest catches up.
          </Note>
        </div>
      </div>
    </section>
  );
}
