"""One repair, from a real model, through the guard.

    uv run python -m c3.eval.repair_proof google:gemini-3.5-flash-lite
    uv run python -m c3.eval.repair_proof <model> --with-regression
    uv run python -m c3.eval.repair_proof scripted:honest --with-regression --studies <dir>
    uv run python -m c3.eval.repair_proof scripted:weakened --with-regression --studies <dir>

Checkpoint 2 proves what the guard does with two answers written by hand: one
honest repair and one weakened assertion. It proves the fence works. It cannot
prove that a model on a free tier ever produces an answer the fence lets
through, and a guard nothing ever clears is indistinguishable from a guard that
refuses everything.

This runs the same scenario against a provider. The scenario is defined here
and imported by the checkpoint 2 tests, so the live run and the scripted
demonstration are provably the same setup rather than two that look alike.

**Or against no provider at all.** `scripted:honest` and `scripted:weakened`
answer with checkpoint 2's two hand written repairs, so a run spends nothing
and repeats exactly. Only the answer is scripted: the install, the runner, the
classifier and the guard's three checks are the ones a live run uses, so the
report is the guard's own record of what it did with each answer. The epoch 5
report was not. It was written by hand, and a number scored from a report that
no run produced is not a measurement.

**What it measures is the pair, not the model.** An acceptance rate belongs to
a model and a prompt shape together, which is why `--shape` exists and why the
shape that answered is recorded on the outcome. Epoch 1 recorded the pinned
free model answering the whole file request with a single import line, twice.
Whether that was the model or the question is answerable only by asking the
same model the other way.

The report it writes is an ordinary heal report, so `c3.eval --healing` scores
it exactly as it scores a stored one. It is written into its own directory
because a run from a different model on a different day is a different epoch,
and epochs are never pooled.
"""

import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sdlc_contracts import (
    ContractDiff,
    EndpointChange,
    TestCase,
    TestReport,
    TestSuite,
    TestTrace,
)

from ..generate.fill import bodies
from ..harness import Sandbox, TargetRepo, resolve, stage_copy
from ..harness import node_lane as lane
from ..heal.repair import Shape, build_repairer
from ..service import C3

SUITE = "apps/web/src/__tests__/basket.test.ts"

TEST_NAME = "totals the basket"

TEST_ID = f"{SUITE}::{TEST_NAME}"

#: The stale test. It was written when `total` did not round, and the code now
#: rounds, so it fails on a value that is no longer what the code produces.
STALE = """\
import { expect, it } from "vitest";
import { total } from "../total";

it("totals the basket", () => {
  expect(total([{ price: 333, quantity: 3 }])).toBe(998);
});
"""

#: An honest repair: the same assertion, on the value the code now produces.
#: Not sent to the model. It is here because the checkpoint 2 tests use it to
#: show that the static rules accept it and the weakened answer alike.
HONEST = STALE.replace("toBe(998)", "toBe(999)")

#: The cheat the literature documents, and the one this component exists to
#: catch. It passes. It also passes on any program at all.
WEAKENED = STALE.replace(
    "expect(total([{ price: 333, quantity: 3 }])).toBe(998);",
    "expect(total([{ price: 333, quantity: 3 }])).toBeDefined();",
)

#: How a run names one of the two answers instead of a provider's model.
SCRIPTED_PREFIX = "scripted:"

#: The two answers checkpoint 2 is about, by the name a scripted run asks for.
SCRIPTED = {"honest": HONEST, "weakened": WEAKENED}

#: What the classifier is given. `brittle`, and decided by the trace rather
#: than by a model: the endpoint this test traces to changed between the two
#: code versions, which is the platform's own signal.
LABEL = "brittle"

#: The second failure: a real bug, not a stale test.
#:
#: `total` has been correct about quantities all along, and a test that checks
#: it is telling the truth. Nothing it traces to moved between the versions, so
#: the rules call it a regression and the loop must leave it alone. Repairing
#: it would rewrite a test until it agreed with a bug, which is the outcome the
#: whole classifier exists to prevent and the one a repair tool with no notion
#: of provenance cannot avoid.
REGRESSION_NAME = "takes a percentage off"

REGRESSION_ID = f"{SUITE}::{REGRESSION_NAME}"

#: A correct test. `discount(100, 10)` is 90 and always was.
REGRESSION_TEST = """\
it("takes a percentage off", () => {
  expect(discount(100, 10)).toBe(90);
});
"""

#: The bug it catches, put into the production code on purpose. Divides by ten
#: where it should divide by a hundred, so a ten percent discount takes
#: everything. Deliberately in `discount` rather than in `total`: the brittle
#: test measures `total`, and breaking that would make the repair encode the
#: bug, which would prove the opposite of what this runs to show.
BROKEN_DISCOUNT = ("percent / 100", "percent / 10")


def failing_report(version: int = 2, *, with_regression: bool = False) -> TestReport:
    """The run that produced the failure, as the healing stage receives it.

    With `with_regression`, two failures rather than one, and the difference
    between them is only what they trace to. That is the point: the classifier
    is given no hint about which is which beyond the platform's own record of
    what changed.
    """
    cases = [
        TestCase(
            id=TEST_ID,
            name=TEST_NAME,
            outcome="failed",
            message="expected 999, received 998",
            origin="filled",
            traces=TestTrace(story_id="US-1", endpoint_ids=["get-basket"]),
        )
    ]
    if with_regression:
        cases.append(
            TestCase(
                id=REGRESSION_ID,
                name=REGRESSION_NAME,
                outcome="failed",
                message="expected 8, received 2",
                origin="filled",
                # Nothing here moved between the two versions.
                traces=TestTrace(story_id="US-2", endpoint_ids=["get-quantities"]),
            )
        )
    return TestReport(
        version=version,
        generated_at="2026-09-08 10:00",
        target="the node sample",
        isolation="a subprocess",
        suites=[TestSuite(path=SUITE, framework="vitest", cases=cases)],
        mutation_skipped_reason="not this stage's work",
    )


def changed_contract() -> ContractDiff:
    """The endpoint moved, which is what makes the failure brittle."""
    return ContractDiff(
        from_version=1,
        to_version=2,
        changed=[EndpointChange(endpoint_id="get-basket", field="response")],
    )


@dataclass
class Ref:
    """The orchestrator's `TargetRef`, as the seam describes it.

    Described rather than imported, which is the arrangement the whole
    component uses: the two sides agree on attribute names and nothing else.
    """

    kind: str
    code_version: int | None = None
    path: str = ""


SOURCE = "apps/web/src/total.ts"


def prepare(root: Path, *, with_regression: bool = False) -> TargetRepo:
    """The node sample, installed, with the stale test in it.

    A real install and a real runner, because the guard's third check runs the
    repaired test against deliberately broken code and there is no way to fake
    that without faking the thing being measured.

    `with_regression` adds the second failure: a correct test and a real bug
    for it to catch, so the run has one of each and the classifier has to tell
    them apart from what they trace to rather than from how they look.
    """
    repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), root / "ws")
    lane.declare_measurement_tools(repo)
    sandbox = Sandbox(repo.root)
    installed = lane.install(repo, sandbox)
    if not installed.passed:
        raise SystemExit(f"npm install failed: {installed.log_tail[-400:]}")

    suite = STALE
    if with_regression:
        suite = (
            STALE.replace(
                'import { total } from "../total";',
                'import { discount, total } from "../total";',
            )
            + REGRESSION_TEST
        )
        source = repo.read(SOURCE) or ""
        wrong, right = BROKEN_DISCOUNT
        if wrong not in source:
            raise SystemExit(f"{SOURCE} does not contain {wrong!r}, so the bug cannot be seeded")
        repo.write(SOURCE, source.replace(wrong, right, 1))
    repo.write(SUITE, suite)
    return repo


def scripted_repairer(answer: str, *, shape: Shape):
    """A repairer that gives `answer` and asks no provider.

    Under `minimal` it answers with the named test's body, which the loop
    splices back into the file, and under `whole-file` with the file itself, so
    either shape arrives at the file the checkpoint 2 tests write.
    """
    payload = {"body": bodies(answer)[TEST_NAME]} if shape == "minimal" else {"content": answer}

    def respond(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(payload))])

    return build_repairer(FunctionModel(respond), shape=shape)


def component_for(model: str, shape: Shape) -> C3:
    """The component a run asks: a provider's model, or one of the two answers."""
    if model.startswith(SCRIPTED_PREFIX):
        answer = SCRIPTED[model.removeprefix(SCRIPTED_PREFIX)]
        return C3("scripted", repairer=scripted_repairer(answer, shape=shape), repair_shape=shape)
    return C3(model, repair_shape=shape)


def write_study(report, *, model: str, shape: str, directory: Path) -> Path:
    """The heal report and its labels, where the study runner can read them.

    Its own directory per model, because pooling a run from one model with a
    run from another would average two things that are not the same experiment.
    """
    directory.mkdir(parents=True, exist_ok=True)
    name = model.replace(":", "-").replace("/", "-")
    path = directory / f"{name}-{shape}.json"
    path.write_text(json.dumps(report.model_dump(by_alias=True, mode="json"), indent=2) + "\n")
    (directory / "labels.json").write_text(
        json.dumps({TEST_ID: LABEL, REGRESSION_ID: "regression"}, indent=2) + "\n"
    )
    return path


async def prove(
    model: str, *, shape: Shape, studies: Path | None, with_regression: bool = False
) -> int:
    """Ask the model to repair the stale test. Returns a process exit code."""
    print(f"model      {model}")
    if model.startswith(SCRIPTED_PREFIX):
        print("           checkpoint 2's answer, written by hand: no provider is asked")
    print(f"shape      {shape}")
    print(f"scenario   {TEST_ID}, labelled {LABEL}")
    if with_regression:
        print(f"           {REGRESSION_ID}, labelled regression")

    with tempfile.TemporaryDirectory(prefix="c3-repair-proof-") as temporary:
        print("workspace  installing the node sample, which takes a minute")
        repo = prepare(Path(temporary), with_regression=with_regression)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))

        started = time.monotonic()
        try:
            answer = await component_for(model, shape).heal(
                target,
                failing_report(with_regression=with_regression),
                from_code_version=1,
                to_code_version=2,
                contract_diff=changed_contract(),
                version=2,
            )
        except Exception as error:
            # The message is the result: a provider that refuses is a fact
            # about the run, not a crash to hide behind a traceback.
            print(f"call       FAILED: {type(error).__name__}: {error}")
            return 2
        elapsed = time.monotonic() - started

        report = answer.artefact
        print(f"call       finished in {elapsed:.1f}s")
        if not report.attempts:
            print("verdict    NOTHING ATTEMPTED (the failure never reached the repairer)")
            return 1

        for attempt in report.attempts:
            print(f"--- {attempt.test_name}")
            print(f"classified {attempt.classification} by {attempt.classified_by}")
            print(
                f"attempts   {attempt.attempts}, {len(attempt.rejected_drafts)} draft(s) rejected"
            )
            for reason in attempt.rejected_drafts:
                print(f"           rejected: {reason}")
            for check in attempt.checks:
                print(f"{'passed' if check.passed else 'FAILED':10} {check.name}: {check.detail}")
            if attempt.diff:
                for line in attempt.diff.diff.splitlines():
                    print(f"           {line}")
            else:
                print("           no diff, so nothing was rewritten")

        print(f"healed     {report.healed}")
        print(f"refused    {report.refused}")
        print(f"flagged    {report.flagged_regressions} regression(s), never repaired")
        print(f"naive      {report.naive_convergence:.2f}%")
        print(f"strict     {report.strict_convergence:.2f}%")
        attempt = report.attempts[0]

        if studies is not None:
            written = write_study(report, model=model, shape=shape, directory=studies)
            print(f"written    {written}")

        if attempt.accepted:
            who = (
                "the scripted repair"
                if model.startswith(SCRIPTED_PREFIX)
                else "a real model's repair"
            )
            print(f"verdict    ACCEPTED ({who} cleared all three checks)")
            return 0
        print(f"verdict    REFUSED ({attempt.refusal_reason})")
        # Not a failure of the run. A refusal is a result, and on this scenario
        # it is the result the guard exists to produce when the answer is a
        # weakening rather than a repair.
        return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 64
    model = sys.argv[1]
    if model.startswith(SCRIPTED_PREFIX) and model.removeprefix(SCRIPTED_PREFIX) not in SCRIPTED:
        print(f"unknown scripted answer {model!r}: scripted:honest or scripted:weakened")
        return 64
    shape: Shape = "minimal"
    if "--shape" in sys.argv:
        value = sys.argv[sys.argv.index("--shape") + 1]
        if value not in ("minimal", "whole-file"):
            print(f"unknown shape {value!r}: minimal or whole-file")
            return 64
        shape = value  # type: ignore[assignment]
    studies = None
    if "--studies" in sys.argv:
        studies = Path(sys.argv[sys.argv.index("--studies") + 1]).expanduser()
    return asyncio.run(
        prove(
            model,
            shape=shape,
            studies=studies,
            with_regression="--with-regression" in sys.argv,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
