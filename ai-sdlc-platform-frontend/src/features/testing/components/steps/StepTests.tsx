import { useState } from "react";
import { AlertTriangle, ArrowUpRight, FileCode2, FlaskConical } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Td, Th } from "@/shared/ui/primitives";
import { VSCodeFileTree } from "@/shared/code-viewer/VSCodeFileTree";
import { VSCodeEditor, type EditorTab } from "@/shared/code-viewer/VSCodeEditor";
import type { FileEntry } from "@/shared/code-viewer/buildFileTree";
import { Bar, Console, Note, Panel } from "../bits/index";
import type { StepId, TestingView } from "../../model/view";
import { readableTranscript } from "../../model/transcript";
import { StageSection } from "@/shared/ui/stage";
import type { TestFileMeta } from "../../fixtures/types";
import { formatWhen } from "@/shared/utils/time";

export function StepTests({
  view,
  testFiles,
  testFileMeta,
  testFileContents,
  caption,
  onGoTo,
  onOpenFailure,
  tabs,
  activePath,
  highlight,
  onSelectFile,
  onSelectTab,
  onCloseTab,
  viewerRef,
}: {
  view: TestingView;
  testFiles: FileEntry[];
  testFileMeta: Record<string, TestFileMeta>;
  testFileContents: Record<string, string>;
  /** Which runners the suites ran on, said in one sentence. */
  caption: string;
  onGoTo: (step: StepId) => void;
  onOpenFailure: (failureId: string) => void;
  tabs: EditorTab[];
  activePath: string;
  highlight?: { path: string; line: number; label?: string };
  onSelectFile: (path: string) => void;
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
  viewerRef: React.RefObject<HTMLDivElement | null>;
}) {
  const meta = testFileMeta[activePath];
  const failure = meta?.failureId ? view.failures.find((f) => f.id === meta.failureId) : undefined;
  const healed = meta?.healedId ? view.failures.find((f) => f.id === meta.healedId) : undefined;
  // The transcript with its runs of npm warnings folded, until every line is asked for.
  const [everyLine, setEveryLine] = useState(false);
  const transcript = readableTranscript(view.transcript, { all: everyLine });
  const foldable = everyLine || transcript.folded > 0;

  return (
    <div className="space-y-4">
      {view.unproven.length > 0 && (
        // A run that measured nothing reads as an empty table, and the page
        // said "every proof passed" over it.
        <div className="flex items-start gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/5 px-3.5 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
              This run did not prove everything: {view.unproven.join(" · ")}
            </p>
            {view.runSummary && <Note className="mt-1">The test run said: {view.runSummary}.</Note>}
          </div>
        </div>
      )}
      {/* One under the other. Side by side, the table lost its last column
          beside the conversation, and the transcript, a fixed height beside a
          table three times as tall, left the rest of its column blank. */}
      <StageSection id="run-failures">
        <Panel
          icon={<FlaskConical className="h-4 w-4 text-blue-400" />}
          label="Suite results"
          title="Unit and API tests, by module"
          meta={`${view.totals.run} tests run · ${view.totals.skipped} skipped · ${view.duration}`}
          bodyClassName="p-0"
        >
          <div className="w-full overflow-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr>
                  <Th>Module</Th>
                  <Th className="text-right">Passed</Th>
                  <Th className="text-right">Failed</Th>
                  <Th className="text-right">Skipped</Th>
                  <Th className="text-right">Pass rate</Th>
                </tr>
              </thead>
              <tbody>
                {view.modules.map((m) => {
                  const run = m.passed + m.failed;
                  const rate = run === 0 ? 0 : (m.passed / run) * 100;
                  return (
                    <tr key={m.id}>
                      <Td>
                        <p className="text-[13px] font-medium">{m.name}</p>
                        <p className="tp-den mt-0.5">
                          {[
                            m.runner,
                            // Nothing after "protects" for a test that came
                            // with the code and traces to no requirement.
                            m.requirements.length > 0 && `protects ${m.requirements.join(", ")}`,
                            // What this version wrote apart from what it carried
                            // (C3-10): said only when something was carried, since
                            // "3 new, 0 carried" on a first version says nothing.
                            (m.carried ?? 0) > 0 &&
                              `${m.fresh ?? 0} new at this version, ${m.carried} carried from earlier`,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      </Td>
                      <Td className="text-right tabular-nums">{m.passed}</Td>
                      <Td className="text-right">
                        {m.failed > 0 ? (
                          <button
                            type="button"
                            onClick={() => onOpenFailure(m.failureIds[0])}
                            className="inline-flex items-center gap-1 font-medium tabular-nums text-red-600 underline decoration-red-200 underline-offset-2 hover:decoration-red-500 dark:text-red-400 dark:decoration-red-500/40"
                            title={`Open ${m.failed} ${m.failed === 1 ? "failure" : "failures"} in the inbox`}
                          >
                            {m.failed}
                            <ArrowUpRight className="h-3 w-3" />
                          </button>
                        ) : (
                          <span className="tabular-nums text-slate-500 dark:text-slate-400">0</span>
                        )}
                      </Td>
                      <Td className="text-right tabular-nums text-slate-500 dark:text-slate-400">{m.skipped}</Td>
                      <Td>
                        <div className="flex items-center justify-end gap-2">
                          <div className="hidden w-16 sm:block">
                            <Bar value={rate} tone={m.failed > 0 ? "caution" : "pass"} />
                          </div>
                          <span className="w-[52px] text-right tabular-nums">{rate.toFixed(1)}%</span>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr>
                  <Td className="font-semibold">All modules</Td>
                  <Td className="text-right font-semibold tabular-nums">{view.totals.passed}</Td>
                  <Td
                    className={cn(
                      "text-right font-semibold tabular-nums",
                      view.totals.failed > 0 && "text-red-600 dark:text-red-400"
                    )}
                  >
                    {view.totals.failed}
                  </Td>
                  <Td className="text-right tabular-nums text-slate-500 dark:text-slate-400">{view.totals.skipped}</Td>
                  <Td className="text-right font-semibold tabular-nums">{view.totals.passRate.toFixed(1)}%</Td>
                </tr>
              </tfoot>
            </table>
          </div>
          {/* They were called integration tests. None of them touches a
              database: the generated test setup keeps the app on its
              in-memory store (review item C3-12). */}
          <Note className="border-t border-[color:var(--tp-line)] px-4 py-2.5">
            The API tests run the app in process, on the app's in-memory store. None of them uses
            the database a cloud release keeps its records in: Deployment's staging step is what
            runs a release against one.
          </Note>
          {view.obsolete.length > 0 && (
            // They still run and still count, so a pass among them would read as
            // evidence for this build unless it said otherwise (C3-10).
            <div className="border-t border-[color:var(--tp-line)] bg-amber-500/5 px-4 py-2.5">
              <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
                Tests that no longer test this build: {view.obsolete.length}
              </p>
              <p className="tp-den mt-0.5">
                Each was written for a story or a criterion the build no longer has. They still run and
                still count.
              </p>
              <ul className="mt-1.5 space-y-1">
                {view.obsolete.map((one) => (
                  <li key={one.id} className="text-[13px]">
                    <span className="font-medium text-[color:var(--tp-ink)]">{one.name}</span>
                    <span className="tp-den block">
                      {one.module} · {one.reason}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {view.awaitingRerun > 0 && (
            <p className="tp-den flex flex-wrap items-center gap-1 border-t border-[color:var(--tp-line)] bg-blue-500/5 px-4 py-2.5 leading-relaxed">
              <span>
                {view.awaitingRerun} approved {view.awaitingRerun === 1 ? "repair is" : "repairs are"} counted as passing
                because the guard ran {view.awaitingRerun === 1 ? "it" : "them"} against this version&apos;s code. The
                next run records {view.awaitingRerun === 1 ? "it" : "them"}.
              </span>
              <button
                type="button"
                onClick={() => onOpenFailure(view.failures.find((f) => f.awaitingRerun)?.id ?? "")}
                className="text-blue-600 underline underline-offset-2 dark:text-blue-400"
              >
                Show {view.awaitingRerun === 1 ? "it" : "them"}
              </button>
            </p>
          )}
          <p className="tp-den border-t border-[color:var(--tp-line)] px-4 py-2.5 leading-relaxed">
            Pass rate is passed ÷ run. Skipped tests are not counted as run. Coverage is a different measure - how much
            of the code the tests execute - and it lives in{" "}
            <button
              type="button"
              onClick={() => onGoTo("test-quality")}
              className="text-blue-600 underline underline-offset-2 dark:text-blue-400"
            >
              Test Quality
            </button>
            .
          </p>
        </Panel>
      </StageSection>

      <StageSection id="run-transcript">
        <Console
          lines={transcript.lines}
          streaming={view.streaming}
          meta={
            view.streaming
              ? `test version ${view.build} · running`
              : `test version ${view.build} · recorded ${formatWhen(view.finishedAt)} · ${view.duration}`
          }
          action={
            foldable && (
              <button
                type="button"
                onClick={() => setEveryLine((now) => !now)}
                className="tp-mono text-[11px] underline underline-offset-2"
                style={{ color: "var(--tp-console-muted)" }}
              >
                {everyLine ? "Fold the warnings" : `Show all ${view.transcript.length} lines`}
              </button>
            )
          }
          className="h-[260px] sm:h-[320px]"
        />
      </StageSection>


      <StageSection id="run-files">
      <Panel
        icon={<FileCode2 className="h-4 w-4 text-blue-400" />}
        label="Generated tests"
        title="The repository, filtered to test files"
        meta={caption}
        bodyClassName="p-0"
      >
        <div ref={viewerRef} className="grid grid-cols-1 gap-4 p-3 sm:p-4 lg:h-[560px] lg:grid-cols-[minmax(0,290px)_minmax(0,1fr)]">
          <div className="h-[220px] min-h-0 min-w-0 lg:h-auto">
            <VSCodeFileTree
              title="Explorer"
              files={testFiles}
              collapseChains
              selectedPath={activePath}
              onSelect={onSelectFile}
              tagTitle={() => "Open the repair in the failure inbox"}
              onTagClick={(path) => {
                const healedId = testFileMeta[path]?.healedId;
                if (healedId) onOpenFailure(healedId);
              }}
            />
          </div>
          <div className="h-[360px] min-h-0 min-w-0 sm:h-[420px] lg:h-auto">
            <VSCodeEditor
              tabs={tabs}
              activePath={activePath}
              contents={testFileContents}
              onSelectTab={onSelectTab}
              onCloseTab={onCloseTab}
              highlight={highlight}
              showLanguage
              copyable
              statusBar={
                meta && (
                  <>
                    <span className="tp-mono">
                      Protects {meta.requirement} · {meta.requirementTitle}
                    </span>
                    {failure && (
                      <button
                        type="button"
                        onClick={() => onOpenFailure(failure.id)}
                        className="inline-flex items-center gap-1 text-red-600 underline underline-offset-2 dark:text-red-400"
                      >
                        <FileCode2 className="h-3 w-3" />
                        Open the failure
                      </button>
                    )}
                    {healed && (
                      <button
                        type="button"
                        onClick={() => onOpenFailure(healed.id)}
                        className="inline-flex items-center gap-1 text-emerald-700 underline underline-offset-2 dark:text-emerald-400"
                      >
                        Healed - open the repair
                      </button>
                    )}
                  </>
                )
              }
            />
          </div>
        </div>
      </Panel>
      </StageSection>
    </div>
  );
}
