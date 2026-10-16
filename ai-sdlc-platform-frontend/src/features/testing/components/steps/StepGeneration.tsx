import { FileCode2, ShieldQuestion } from "lucide-react";
import { StageSection } from "@/shared/ui/stage";
import { Metric, Note, Panel } from "../bits/index";
import { counted, type TestingView } from "../../model/view";

/** Each kind of gap as a reader would name it; one with no words of its own reads as its kind. */
const GAP_WORDS: Record<string, string> = {
  "no-way-to-create": "Nothing creates one",
  "validation-not-enforced": "Validation not enforced",
  "auth-not-implemented": "No sign-in to refuse",
};

/**
 * What the generator wrote, and what it could not write.
 *
 * This stage had no place on screen at all before the phase moved onto the
 * shared chrome: the stepper carried six ids of its own over the contract's
 * seven, and generation was folded into the run. That mattered more than it
 * sounds. A generator that writes nothing and a generator that was skipped
 * because the target is a Java repository both looked identical from here,
 * which is to say invisible, and the gaps it reports are half of what this
 * phase is for.
 *
 * It then read the run's totals and nothing the generator said. Over five
 * contract obligations nothing implements it read "Every criterion in scope
 * has a test", and it put thirty tests of three kinds down to "two places".
 * It reads the generator's own report now: where each test came from, and
 * each obligation no test can assert, with its reason.
 */
export function StepGeneration({ view }: { view: TestingView }) {
  const written = view.totals.run;
  const declared = view.totals.skipped;
  const { sources, gaps, gapsReported, summary } = view.generation;
  // What the report lists, or what the stage counted when it lists none.
  const outOfReach = gaps.length > 0 ? gaps.length : gapsReported;
  const source = `test report, test version ${view.build}`;

  return (
    <div className="space-y-4">
      <StageSection id="generation-counts">
        <Panel
          icon={<FileCode2 className="h-4 w-4 text-blue-400" />}
          label="Generated tests"
          title={
            written === 0
              ? "Nothing has been written for this test version yet"
              : `${written} test${written === 1 ? "" : "s"} in the suite`
          }
          meta={summary || undefined}
        >
          <Note className="max-w-3xl">
            One test for each acceptance criterion, written by the model from the criterion and
            named for its story; one for each operation the API contract declares, written by rule;
            and the tests Code Generation shipped with the code. A criterion nothing can observe
            stays declared and unwritten: it reports as a skip, never as a pass.
          </Note>
          {/* `min-w-0` on the grid itself: a grid column defaults to
              min-content, so a long label refuses to shrink below its
              intrinsic width and pushes the column past the viewport. The
              narrow width sweep caught this at 390, six pixels over. */}
          <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-3">
            <Metric
              source={source}
              label="From acceptance criteria"
              value={sources.criteria}
              note={`${sources.filled} written by the model`}
              tone="pass"
            />
            <Metric source={source} label="From the API contract" value={sources.contract} tone="pass" />
            <Metric source={source} label="Shipped with the code" value={sources.shipped} tone="pass" />
          </div>
        </Panel>
      </StageSection>

      <StageSection id="generation-gaps">
        <Panel
          icon={<ShieldQuestion className="h-4 w-4 text-amber-400" />}
          label="What nothing covers"
          title={
            outOfReach > 0
              ? `${counted(outOfReach, "contract obligation", "contract obligations")} no test can assert`
              : declared > 0
                ? `${counted(declared, "criterion", "criteria")} declared and not yet written`
                : "Every criterion has a test, and the contract obliges nothing a test cannot reach"
          }
          meta={
            outOfReach > 0 && declared > 0
              ? `${counted(declared, "criterion", "criteria")} declared and not yet written`
              : undefined
          }
        >
          {gaps.length > 0 ? (
            <>
              <Note className="max-w-3xl">
                The contract obliges each of these, and the application gives a test nothing to
                assert it against: a test written anyway would fail for ever and say the wrong
                thing. They are absent features, not broken ones, and they are not counted as
                passing.
              </Note>
              <ul className="mt-3 divide-y divide-[color:var(--tp-line)] border-t border-[color:var(--tp-line)]">
                {gaps.map((gap, index) => (
                  <li key={`${gap.endpointId}:${gap.kind}:${index}`} className="py-2.5">
                    <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[13px]">
                      <span className="font-mono text-[12px] text-[color:var(--tp-ink)]">{gap.endpointId}</span>
                      <span className="font-medium text-[color:var(--tp-caution)]">
                        {GAP_WORDS[gap.kind] ?? gap.kind}
                      </span>
                    </p>
                    <Note className="mt-0.5 max-w-3xl break-words text-[12.5px]">{gap.detail}</Note>
                  </li>
                ))}
              </ul>
            </>
          ) : outOfReach > 0 ? (
            <Note className="max-w-3xl">
              The generation stage counted them. This run was made before each was listed here:
              run the tests again to see which operations they are and why.
            </Note>
          ) : (
            <Note className="max-w-3xl">
              An unwritten test reports as a skip, never as a pass, so a suite cannot read greener
              than the code it describes.
            </Note>
          )}
        </Panel>
      </StageSection>
    </div>
  );
}
