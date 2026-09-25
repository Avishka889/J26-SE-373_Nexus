import { useState } from "react";
import { coverageTrendCaption } from "../../model/process";
import { Activity, FileCheck, FlaskConical, TrendingUp } from "lucide-react";
import { Progress } from "@/shared/ui/primitives";
import { Bar, Metric, Note, Panel } from "../bits/index";
import type { Quality } from "../../fixtures/types";
import type { TestingView } from "../../model/view";

function TrendChart({ trend }: { trend: Quality["trend"] }) {
  // Nothing to draw before a run reports, and the label beside the last point
  // would read a point that is not there.
  if (trend.length === 0) return <Note>Nothing measured yet.</Note>;
  // One measurement is a point, and a chart of one point is two dots and an
  // axis too small to read. It says what was measured, and when a line will
  // have something to join.
  if (trend.length === 1) {
    const only = trend[0];
    return (
      <Note>
        Measured once, at test version {only.build}: line coverage {only.line}%, branch coverage{" "}
        {only.branch}%. The chart is drawn once there are two measurements to join.
      </Note>
    );
  }
  const w = 640;
  const h = 190;
  const padL = 40;
  const padR = 46;
  const padT = 14;
  const padB = 34;
  // The floor follows the lowest value, never above 55: a fixed 55 drew a
  // suite at 20% below the chart's bottom edge, where nobody could see it.
  const lowest = Math.min(...trend.flatMap((p) => [p.line, p.branch]));
  const min = Math.min(55, Math.max(0, Math.floor((lowest - 5) / 10) * 10));
  const max = 100;
  const ticks = [80, 60, 40, 20, 0].filter((tick) => tick >= min).reverse().concat(100);

  const x = (i: number) =>
    padL + (i * (w - padL - padR)) / Math.max(1, trend.length - 1);
  const y = (v: number) => padT + ((max - v) / (max - min)) * (h - padT - padB);

  const path = (key: "line" | "branch") =>
    trend.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)} ${y(p[key])}`).join(" ");
  const last = trend[trend.length - 1];

  return (
    <div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="h-auto w-full"
        role="img"
        aria-label="Coverage by test version"
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={padL}
              x2={w - padR}
              y1={y(tick)}
              y2={y(tick)}
              stroke="var(--tp-line)"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <text
              x={padL - 8}
              y={y(tick) + 3.5}
              textAnchor="end"
              fontSize={10}
              fill="var(--tp-muted)"
            >
              {tick}%
            </text>
          </g>
        ))}

        <path
          d={path("branch")}
          fill="none"
          stroke="#94a3b8"
          strokeWidth={1.5}
          strokeDasharray="4 3"
        />
        <path d={path("line")} fill="none" stroke="#2563eb" strokeWidth={2} />

        {trend.map((p, i) => (
          <g key={p.build}>
            <title>{`Test version ${p.build}: line ${p.line}%, branch ${p.branch}%`}</title>
            <circle cx={x(i)} cy={y(p.branch)} r={2.5} fill="#94a3b8" />
            <circle cx={x(i)} cy={y(p.line)} r={3} fill="#2563eb" />
            <text
              x={x(i)}
              y={h - 14}
              textAnchor="middle"
              fontSize={10}
              fill="var(--tp-muted)"
            >
              {p.build}
            </text>
            <rect
              x={x(i) - 14}
              y={padT}
              width={28}
              height={h - padT - padB}
              fill="transparent"
            >
              <title>{`Test version ${p.build}: line ${p.line}%, branch ${p.branch}%`}</title>
            </rect>
          </g>
        ))}

        <text
          x={w - padR + 6}
          y={y(last.line) + 3.5}
          fontSize={11}
          fill="#2563eb"
          fontWeight={600}
        >
          {last.line}%
        </text>
        <text
          x={w - padR + 6}
          y={y(last.branch) + 3.5}
          fontSize={11}
          fill="var(--tp-muted)"
        >
          {last.branch}%
        </text>
        <text x={padL} y={h - 2} fontSize={9} fill="var(--tp-muted)">
          TEST VERSION
        </text>
      </svg>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="tp-den flex items-center gap-1.5">
          <span className="h-[2px] w-4 rounded-full bg-blue-600" /> line
          coverage
        </span>
        <span className="tp-den flex items-center gap-1.5">
          <span className="h-[2px] w-4 rounded-full bg-slate-400" /> branch
          coverage
        </span>
      </div>
    </div>
  );
}

/** A reason as a sentence: the server's begin in lower case, to follow "no mutation score:". */
function sentence(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return trimmed;
  const capital = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}

/** How many files show before "Show all": a generated app has dozens. */
const MODULES_SHOWN = 8;

/** A file's folder and its name apart, so three files called `index.ts` can be told apart. */
function folderAndFile(path: string): [string, string] {
  const at = path.lastIndexOf("/");
  return at < 0 ? ["", path] : [path.slice(0, at + 1), path.slice(at + 1)];
}

export function StepQuality({ view }: { view: TestingView }) {
  const { quality } = view;
  const byModule = [...quality.byModule].sort((a, b) => a.line - b.line);
  const [everyModule, setEveryModule] = useState(false);
  const modules = everyModule ? byModule : byModule.slice(0, MODULES_SHOWN);

  return (
    // Columns by the stage column's width, and each card its own height. By
    // the window's width the cards sat two across beside the conversation in a
    // column too narrow for it, and a card beside a longer one stretched to
    // match: the trend card was 2,800 pixels of white beside 29 files.
    <div className="@container space-y-4">
      <div className="grid grid-cols-1 items-start gap-4 @4xl:grid-cols-2">
        <Panel
          icon={<Activity className="h-4 w-4 text-blue-400" />}
          label="Coverage"
          title="How much of the code the tests execute"
          meta={`Measured at test version ${view.build}`}
        >
          <div className="space-y-5">
            <div>
              <Metric
                source={`test report, test version ${view.build}`}
                label="Line coverage"
                value={`${quality.line.percent}%`}
                denominator={`${quality.line.covered.toLocaleString()} of ${quality.line.total.toLocaleString()} lines`}
              />
              <div className="mt-2">
                <Bar value={quality.line.percent} />
              </div>
            </div>
            <div>
              <Metric
                source={`test report, test version ${view.build}`}
                label="Branch coverage"
                value={`${quality.branch.percent}%`}
                denominator={`${quality.branch.covered.toLocaleString()} of ${quality.branch.total.toLocaleString()} branches`}
              />
              <div className="mt-2">
                <Bar value={quality.branch.percent} tone="muted" />
              </div>
            </div>
            <Note className="text-xs">
              Line coverage counts lines the tests ran. Branch coverage counts
              the decisions inside them - the second number is the harder one,
              and the one that tells you whether the edge cases are tested.
            </Note>
          </div>
        </Panel>

        <Panel
          icon={<FlaskConical className="h-4 w-4 text-blue-400" />}
          label="Mutation testing"
          title="Small bugs planted on purpose, then the suite runs again"
          meta={quality.tool}
        >
          {quality.mutationRan === false ? (
            // Said, not measured: the page showed "0%" for a run that never happened.
            <Note>{sentence(quality.mutationSkippedReason || "Mutation did not run.")}</Note>
          ) : (
            <MutationResults quality={quality} />
          )}
          {quality.mutationRan !== false &&
            (quality.mutationNotMeasured ?? []).map((one) => (
              // Each app is mutated on its own; one that gave no score is not in the score.
              <Note key={one.app} className="mt-3">
                {`${one.app} was not mutated: ${one.reason}.`}
              </Note>
            ))}
          {quality.findings && quality.findings.length > 0 && (
            <div className="mt-4">
              <p className="tp-label">What the quality checks found</p>
              <ul className="mt-2 space-y-2">
                {quality.findings.map((finding, index) => (
                  <li key={`${finding.location}-${index}`} className="border-l-2 border-amber-500/40 pl-3">
                    <p className="font-mono text-[11.5px]">{finding.location}</p>
                    <p className="tp-prose text-[12.5px]">
                      {finding.change}. {finding.note}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
      </div>

      <div className="grid grid-cols-1 items-start gap-4 @4xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Panel
          icon={<FileCheck className="h-4 w-4 text-blue-400" />}
          label="Coverage by module"
          title="Weakest first"
          meta={
            byModule.length > MODULES_SHOWN && !everyModule
              ? `The ${MODULES_SHOWN} least covered of ${byModule.length} files`
              : "Line and branch coverage per file"
          }
          bodyClassName="p-0"
        >
          <ul className="divide-y divide-slate-100 dark:divide-white/[0.04]">
            {modules.map((m) => {
              const [folder, file] = folderAndFile(m.path ?? m.name);
              return (
              <li
                key={m.path ?? m.name}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-2.5"
              >
                <div className="min-w-[180px] flex-1">
                  <p className="truncate font-mono text-xs" title={m.path ?? m.name}>
                    {folder && <span className="text-[color:var(--tp-muted)]">{folder}</span>}
                    {file}
                  </p>
                  <p className="tp-den mt-0.5">
                    {m.covered.toLocaleString()} of {m.total.toLocaleString()}{" "}
                    lines
                  </p>
                </div>
                <div className="flex w-full items-center gap-3 sm:w-auto">
                  <div className="w-24 sm:w-32">
                    <Bar
                      value={m.line}
                      tone={m.line < 75 ? "caution" : "pass"}
                    />
                  </div>
                  <span className="w-[38px] text-right text-[13px] tabular-nums">
                    {m.line}%
                  </span>
                  <span className="tp-den w-[86px] text-right">
                    {/* A file with no decisions has no branch coverage to
                        speak of: it read "branch 0%", as if every branch
                        were missed. */}
                    {m.branches === 0 ? "no branches" : `branch ${m.branch}%`}
                  </span>
                </div>
              </li>
              );
            })}
          </ul>
          {byModule.length > MODULES_SHOWN && (
            <button
              type="button"
              onClick={() => setEveryModule((now) => !now)}
              className="w-full border-t border-slate-100 px-5 py-2.5 text-left text-xs font-medium text-blue-600 underline underline-offset-2 dark:border-white/[0.04] dark:text-blue-400"
            >
              {everyModule ? `Show the ${MODULES_SHOWN} least covered` : `Show all ${byModule.length} files`}
            </button>
          )}
        </Panel>

        <Panel
          icon={<TrendingUp className="h-4 w-4 text-blue-400" />}
          label="Coverage by test version"
          title="Where coverage has moved"
          meta={coverageTrendCaption(quality.trend.length)}
        >
          <TrendChart trend={quality.trend} />
        </Panel>
      </div>
    </div>
  );
}

/** How many survivors show before "Show all": the list can run to dozens. */
const SURVIVORS_SHOWN = 8;

function MutationResults({ quality }: { quality: Quality }) {
  const [all, setAll] = useState(false);
  const shown = all ? quality.survivors : quality.survivors.slice(0, SURVIVORS_SHOWN);
  return (
    <>
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
          <p className="text-2xl font-bold tabular-nums text-emerald-700 dark:text-emerald-400">
            {quality.mutation.killed}
          </p>
          <p className="tp-label mt-0.5">Mutants killed</p>
          <p className="tp-den mt-1">the tests caught these</p>
        </div>
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
          <p className="text-2xl font-bold tabular-nums text-red-700 dark:text-red-400">
            {quality.mutation.survived}
          </p>
          <p className="tp-label mt-0.5">Mutants survived</p>
          <p className="tp-den mt-1">planted bugs no test noticed</p>
        </div>
      </div>

      <div className="mt-4">
        <div className="mb-1.5 flex items-baseline justify-between gap-3">
          <span className="tp-label">Mutation score</span>
          <span className="tp-den">
            <span className="text-sm font-semibold text-[color:var(--tp-ink)]">
              {quality.mutation.score}%
            </span>{" "}
            · {quality.mutation.killed} killed ÷ {quality.mutation.total} planted
          </span>
        </div>
        <Progress value={quality.mutation.score} color="#2563eb" />
      </div>

      {quality.survivors.length > 0 && (
        <div className="mt-4">
          <p className="tp-label">What survived</p>
          <ul className="mt-2 space-y-2">
            {shown.map((s, index) => (
              <li key={`${s.location}-${index}`} className="border-l-2 border-red-500/40 pl-3">
                <p className="font-mono text-[11.5px]">{s.location}</p>
                <p className="tp-prose text-[12.5px]">
                  {s.change}. {s.note}
                </p>
              </li>
            ))}
          </ul>
          {quality.survivors.length > SURVIVORS_SHOWN && (
            <button
              type="button"
              onClick={() => setAll((now) => !now)}
              className="mt-2 text-[12.5px] font-medium text-blue-700 hover:underline dark:text-blue-300"
            >
              {all ? "Show fewer" : `Show all ${quality.survivors.length}`}
            </button>
          )}
        </div>
      )}
    </>
  );
}
