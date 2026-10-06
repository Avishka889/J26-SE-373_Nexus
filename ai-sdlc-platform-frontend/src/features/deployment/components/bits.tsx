import type { ReactNode } from "react";
import { Chip, type ChipTone } from "@/shared/ui/phase";
import { cn } from "@/shared/utils/cn";
import type { RiskLevel } from "../api/types";
import { levelLabel, type VoteView } from "../model/view";

/**
 * The chips and small blocks this phase's stages are built from.
 *
 * Tones come from literal lookup maps, never string building, so the class
 * scanner sees every one of them. A level is never shown by colour alone: the
 * word is always on the chip.
 */

const LEVEL_TONE: Record<RiskLevel, ChipTone> = {
  high: "fail",
  medium: "caution",
  low: "pass",
};

export function LevelChip({ level, title }: { level: RiskLevel | null; title?: string }) {
  return (
    <Chip tone={level ? LEVEL_TONE[level] : "neutral"} title={title}>
      {levelLabel(level)}
    </Chip>
  );
}

/** All three signals' votes, each with the reason code wrote for it on hover. */
export function VoteChips({ votes }: { votes: VoteView[] }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {votes.map((vote) => (
        <Chip
          key={vote.signal}
          tone={vote.level ? LEVEL_TONE[vote.level] : "neutral"}
          title={vote.level ? vote.rationale : vote.abstained}
        >
          {vote.label}: {vote.level ? levelLabel(vote.level) : "no vote"}
        </Chip>
      ))}
    </span>
  );
}

const OUTCOME_TONE: Record<string, ChipTone> = {
  passed: "pass",
  succeeded: "pass",
  healthy: "pass",
  failed: "fail",
  down: "fail",
  "timed-out": "fail",
  "awaiting-rollback-approval": "fail",
  degraded: "caution",
  "cold-start": "caution",
  compensated: "caution",
  "rolled-back": "caution",
  "kept-unverified": "caution",
  running: "info",
  pending: "neutral",
  "not-run": "neutral",
  skipped: "neutral",
  unknown: "neutral",
};

const OUTCOME_WORDS: Record<string, string> = {
  "awaiting-rollback-approval": "waiting on a rollback decision",
  "rolled-back": "rolled back",
  "kept-unverified": "kept, unverified",
  "not-run": "did not run",
  "timed-out": "timed out",
  "cold-start": "cold start",
};

/** A step's, a deployment's or a window's state, in words and a tone. */
export function StateChip({ state }: { state: string }) {
  return <Chip tone={OUTCOME_TONE[state] ?? "neutral"}>{OUTCOME_WORDS[state] ?? state}</Chip>;
}

/** Hashes, paths and commands: monospace, and allowed to break anywhere at phone widths. */
export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("break-all font-mono text-[12px]", className)}>{children}</span>;
}

/**
 * A live address, opened in a new tab. The release's addresses were plain text,
 * so opening the released app meant copying them.
 */
export function Address({ href }: { href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="break-all font-mono text-[12px] text-blue-600 underline underline-offset-2 dark:text-blue-400"
    >
      {href}
    </a>
  );
}

/** Label and value pairs, two columns where there is room and one where there is not. */
export function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="tp-label">{label}</dt>
          <dd className="mt-1 min-w-0 break-words text-[13px] text-[color:var(--tp-ink)]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** What an empty section is waiting on, or why it is empty. */
export function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-xl border border-dashed border-[color:var(--tp-line-strong)] px-3.5 py-3 text-[13px] text-[color:var(--tp-ink-2)]">
      {children}
    </p>
  );
}

const CLAIM_TONE: Record<string, ChipTone> = {
  breaking: "fail",
  removal: "fail",
  behavioural: "caution",
  deprecation: "caution",
  security: "caution",
};

/** A verified release note claim, quoted exactly, with where it came from. */
export function Quote({
  quote,
  version,
  sourceUrl,
  kind,
}: {
  quote: string;
  version: string;
  sourceUrl: string;
  kind: string;
}) {
  return (
    <figure className="min-w-0 border-l-2 border-blue-500/50 py-1.5 pl-3">
      <blockquote className="break-words text-[13px] text-[color:var(--tp-ink)]">{quote}</blockquote>
      <figcaption className="tp-den mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <Chip tone={CLAIM_TONE[kind] ?? "neutral"}>{kind}</Chip>
        <span>release {version}</span>
        <a
          href={sourceUrl}
          target="_blank"
          rel="noreferrer"
          className="break-all text-blue-600 underline underline-offset-2 dark:text-blue-400"
        >
          source
        </a>
      </figcaption>
    </figure>
  );
}
