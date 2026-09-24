"""Component 3 as the orchestrator sees it: one method per stage.

The surface exists before the stages behind it do, on purpose. Registering the
component early means the run machinery, the gate, the version axis and the
read model isolation are all exercised against a real registry entry rather
than retrofitted around one later, which is how C2's read model hazard was
found before it could bite.

What is not built says so. A stage whose implementation has not landed raises
`NotBuilt` naming itself and the phase that will bring it, rather than
returning an empty report: an empty test report is indistinguishable from a
suite that ran and found nothing, and this component's entire argument is that
those two must never look alike.

Every method takes the version it is producing at. A report that says version 1
while living at version 3 would be a number nobody could attribute, and the one
rule this component holds itself to is that a number carries its provenance
from the moment it is produced.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sdlc_contracts import (
    ApiContract,
    ChangedCode,
    ContractDiff,
    DiffSpan,
    GuardCheck,
    HealAttempt,
    HealReport,
    ManifestRow,
    PatchHunk,
    RemediationProposal,
    RequirementDiff,
    SprintPlan,
    TestCase,
    TestGap,
    TestReport,
    TestSuite,
    TestSummary,
    TestTrace,
    ToolStep,
    ValidationReport,
    with_traces_from,
)

from . import quality
from .agents import settings_for
from .detect import LlmArm, ScannerArm, TrainedArm
from .detect.findings import Merged, merge_findings
from .generate import Generation, generate, origins_in
from .generate.api_tests import GeneratedCase
from .generate.criteria import endpoints_of
from .generate.decisions import carry_quarantines, decide
from .generate.fill import build_filler, declared_names, describe_of
from .generate.filling import FillResult, fill_criteria, fresh_bindings, merge_carried
from .generate.headers import with_header
from .harness import (
    ISOLATION,
    Sandbox,
    StepResult,
    TargetLike,
    java_lane,
    node_lane,
    resolve,
    sample_root,
    samples,
    toolchain,
)
from .harness.node_lane import declare_measurement_tools, install
from .harness.report import case_id
from .heal import guard as guard_module
from .heal import kill_check as kill_module
from .heal.classify import Verdict, classify
from .heal.classify import summarise as summarise_verdicts
from .heal.referee import build_referee, changes_for, referee
from .heal.repair import Shape as RepairShape
from .heal.repair import build_repairer, repair
from .model_use import reports_model_use
from .remediate import (
    MAX_PROPOSALS,
    NotComparable,
    ProposalRun,
    Unproposed,
    build_patcher,
    candidates,
    compare,
    proposal_for,
    propose_patch,
    read_source,
    rollback_advice,
)


class NotBuilt(RuntimeError):
    """A stage that has not been implemented yet, saying which and when.

    Deliberately not a quiet empty result. The reader is told the stage did not
    run, and a run that reaches it fails at that stage with the reason on it,
    which is the same treatment any other stage failure gets.
    """

    def __init__(self, stage: str, phase: str) -> None:
        super().__init__(
            f"{stage} is not built yet: it lands in {phase}. "
            "Nothing was run and nothing was measured."
        )
        self.stage = stage
        self.phase = phase


class StageAnswer:
    """What a stage produced, in the shape the client passes back.

    The orchestrator has a dataclass for this and the component does not import
    it, for the reason the target reference is described rather than imported:
    the two sides agree on attribute names and nothing else.
    """

    def __init__(self, artefact: Any, summary: str, notes: dict[str, Any]) -> None:
        self.artefact = artefact
        self.summary = summary
        self.notes = notes


class GeneratedTests:
    """What generation produced, in the shape the client passes back.

    A small class rather than the client's dataclass, because the component
    does not import the orchestrator: the two agree on attribute names, which
    is the same arrangement the target reference already uses.
    """

    def __init__(
        self,
        files: dict[str, str],
        manifest: list[ManifestRow],
        summary: str,
        notes: dict[str, Any],
    ) -> None:
        self.files = files
        self.manifest = manifest
        self.summary = summary
        self.notes = notes


class C3:
    """The component. One instance per process, agents built once.

    The model is held rather than used for now: the rule stages are
    deterministic and spend nothing, and the stages that do call a model land
    with the phases that need them.
    """

    def __init__(
        self,
        model: Any,
        *,
        filler: Any = None,
        referee: Any = None,
        repairer: Any = None,
        patcher: Any = None,
        detector: Any = None,
        trained_model_dir: str = "",
        repair_shape: RepairShape = "minimal",
        thinking: str = "off",
    ) -> None:
        self._model = model
        #: How hard the stages ask the model to think (`agents.THINKING_LEVELS`).
        self.thinking = thinking
        self._settings = settings_for(model, thinking=thinking)
        # `minimal` by default, and the default is the finding: the whole file
        # shape asks a model to reproduce thirty lines character for character,
        # and epoch 1 recorded the pinned free model answering with a single
        # import line. Both shapes stay so the study can report the acceptance
        # rate of each, which is the only honest way to say whether that run
        # failed on the model or on the prompt.
        self._repair_shape: RepairShape = repair_shape
        # Injected by this package's own tests, which drive the model passes
        # with scripted answers rather than a provider. Built from the model on
        # first use otherwise.
        self._filler = filler
        self._referee = referee
        self._repairer = repairer
        self._patcher = patcher
        # The prompted detection arm. Absent by default, because a stage a
        # pipeline triggers should use the arm that needs no key and spends
        # nothing; supplying one is how a caller says it has decided otherwise.
        self._detector = detector
        # The trained arm, which needs weights on disk and a process to hold
        # torch. Absent by default for the same reason and one more: a
        # directory that is not there is a stage that fails, and most
        # deployments of this platform will not have trained anything.
        self._trained_model_dir = trained_model_dir

    @property
    def model(self) -> str:
        return self._model if isinstance(self._model, str) else str(self._model)

    def targets(self) -> list[dict[str, str]]:
        """What this component can be pointed at, for a person to choose from.

        The generated application first, because it is what the pipeline is
        for. The samples after it, read from disk, because they are how the
        Java lane and the seeded weaknesses are reached at all: the generated
        MERN application has no Spring in it and never will.

        A list rather than a constant on the orchestrator's side: which samples
        exist is a fact about this component's fixtures directory, and a second
        copy of it elsewhere would go stale the first time one is added.
        """
        found = [
            {
                "id": "generated",
                "label": "The generated application",
                "stack": "node",
                "detail": "The repository this project's code phase produced.",
            }
        ]
        for name in samples():
            root = sample_root(name)
            stack = "java" if (root / "pom.xml").is_file() else "node"
            found.append(
                {
                    "id": f"sample:{name}",
                    "label": name.replace("-", " ").capitalize(),
                    "stack": stack,
                    "detail": (
                        "A checked in sample with seeded weaknesses, so the "
                        f"{stack} lane can be measured without waiting on generated code."
                    ),
                }
            )
        return found

    def decide_test(
        self, source: str, name: str, decision: str, *, by: str, reason: str, on: str
    ) -> str | None:
        """A person's decision about one failing test, made in its file (`decisions.py`).

        Not a stage: nothing runs and no model is asked. None when the file
        does not hold the test as the decision needs it, so the caller refuses
        rather than stores a file with the wrong test changed.
        """
        return decide(source, name, decision, by=by, reason=reason, on=on)

    @reports_model_use
    async def generate_tests(
        self,
        target: TargetLike,
        sprint: SprintPlan,
        contract: ApiContract,
        openapi: dict[str, Any],
        *,
        version: int,
    ) -> GeneratedTests:
        """Everything the rules can write, and a report that says it has not run.

        The report is the point of this stage as much as the files are. Every
        case in it is `not-run`, which is the literal truth: the tests exist
        and nothing has executed them. A generation stage that wrote an empty
        report, or one with the cases already green, would be making the exact
        claim this component was built to stop other tools making.
        """
        repo = resolve(target)
        if repo.stack != "node":
            # The rules write TypeScript, because the contract they derive from
            # describes the generated MERN application. Writing it into a Maven
            # project would produce files nothing compiles and a report that
            # counted them.
            raise NotBuilt(
                "test-generation for a java target",
                "a later phase; the Java lane runs the tests a Java project already has",
            )
        # What each side's app exports, which its criteria tests load afresh
        # before every test so no test inherits what another left in a store.
        bound = fresh_bindings(repo)
        produced = generate(sprint, contract, openapi, apps=repo.apps, bound=bound)
        # Tests this run must not write over. A criteria test that already has
        # bodies encodes behaviour somebody observed, and the loop that may
        # change it is the guarded one, not this stage. The file keeps them and
        # gains a todo for each criterion its story has now that nothing covers,
        # so what the report declares is what the file holds.
        merged = merge_carried(repo, produced.files)
        produced = _declaring_what_is_kept(produced, merged, sprint, contract)
        # A quarantine is a person's decision with a reason on the record, and
        # outlives the run that writes the contract tests again from the
        # contract. A criteria file is carried whole, quarantines included.
        for path, content in list(produced.files.items()):
            earlier = None if path in merged else repo.read(path)
            if earlier:
                produced.files[path] = carry_quarantines(earlier, content)
        for path, content in produced.files.items():
            repo.write(path, content)

        fills, fill_note = await self._fill(repo, produced, sprint, contract)
        # Each criteria file opens by saying what it holds now. The model keeps
        # the header it was given, so a file of written tests reached the
        # project's repository saying none of them was written.
        for path, content in list(produced.files.items()):
            current = with_header(content) if path.endswith(".criteria.test.ts") else content
            if current != content:
                produced.files[path] = current
                repo.write(path, current)
        filled_paths = {result.path for result in fills if result.accepted} | {
            path for path, one in merged.items() if one.carried
        }
        report = self._unrun_report(
            produced,
            repo_name=_target_name(target, repo.kind),
            version=version,
            filled=filled_paths,
        )
        moved = sum(1 for one in merged.values() if one.moved)
        return GeneratedTests(
            files=produced.files,
            manifest=_with_fills(produced.manifest, filled_paths),
            summary=_summary(produced, fills)
            + (
                f"; {moved} earlier test file{'' if moved == 1 else 's'} moved to a fresh "
                "application for every test"
                if moved
                else ""
            ),
            notes={
                "report": report.model_dump(by_alias=True, mode="json"),
                "generated": len(produced.files),
                "gaps": [
                    {"endpointId": gap.endpoint_id, "kind": gap.kind, "detail": gap.detail}
                    for gap in produced.gaps
                ],
                "freshApp": {
                    "bound": bound,
                    "moved": sorted(path for path, one in merged.items() if one.moved),
                    "leftShared": {
                        path: one.left_shared for path, one in merged.items() if one.left_shared
                    },
                },
                "fill": fill_note
                or [
                    {
                        "path": result.path,
                        "accepted": result.accepted,
                        "attempts": result.attempts,
                        "filled": len(result.filled),
                        "stillDeclared": len(result.left_declared),
                        "reasons": result.reasons[:3],
                    }
                    for result in fills
                ],
            },
        )

    async def _fill(
        self,
        repo: Any,
        produced: Generation,
        sprint: SprintPlan,
        contract: ApiContract,
    ) -> tuple[list[FillResult], Any]:
        """The model pass, when there is a model and something to fill.

        Skipped rather than faked when neither is true, and the reason travels
        on the report: a stage that quietly did not run is the thing this
        component refuses to be.
        """
        # A carried file is filled too, for the todos it gained. Its written
        # tests are protected by the post checks rather than by skipping the
        # file, so a story whose criteria were reworded gets tests for the new
        # ones without the old ones being touched.
        unwritten = [
            path
            for path, content in produced.files.items()
            if path.endswith(".criteria.test.ts") and declared_names(content)
        ]
        if not unwritten:
            return [], "no acceptance criteria are waiting for a body, so there was nothing to fill"
        agent = self._filler
        if agent is None:
            if ":" not in str(self._model):
                return [], (
                    f"no provider model is configured ({self._model!r}), so the criteria "
                    "stay declared and unwritten"
                )
            agent = build_filler(self._model, thinking=self.thinking)

        sandbox = Sandbox(repo.root)
        declare_measurement_tools(repo)
        step = install(repo, sandbox)
        if not step.passed:
            return [], (
                "the workspace would not install, so no fill could be checked: " + step.tail[-300:]
            )
        return (
            await fill_criteria(
                agent,
                repo,
                sandbox,
                files=produced.files,
                sprint=sprint,
                contract=contract,
            ),
            None,
        )

    @staticmethod
    def _unrun_report(
        produced: Generation, *, repo_name: str, version: int, filled: set[str]
    ) -> TestReport:
        by_suite: dict[str, list[TestCase]] = {}
        for case in produced.cases:
            by_suite.setdefault(case.suite_path, []).append(
                TestCase(
                    id=case.id,
                    name=case.name,
                    outcome="not-run",
                    kind=case.kind,  # type: ignore[arg-type]
                    origin="filled" if case.suite_path in filled else case.origin,  # type: ignore[arg-type]
                    traces=TestTrace(
                        story_id=case.story_id,
                        criterion_id=case.criterion_id,
                        requirement_ids=case.requirement_ids,
                        endpoint_ids=list(case.endpoint_ids),
                    ),
                )
            )
        return TestReport(
            version=version,
            generated_at=datetime.now(UTC).replace(tzinfo=None),
            target=repo_name,
            isolation=ISOLATION,
            suites=[
                TestSuite(path=path, framework="vitest", cases=cases)
                for path, cases in sorted(by_suite.items())
            ],
            mutation_skipped_reason="nothing has been run yet, so nothing has been mutated",
            # On the report, where the stages after this one keep them and the
            # page reads them. They went out in the notes alone, which reach
            # the audit log and nothing else.
            gaps=[
                TestGap(endpoint_id=gap.endpoint_id, kind=gap.kind, detail=gap.detail)
                for gap in produced.gaps
            ],
        )

    async def run_tests(
        self, target: TargetLike, *, version: int, declared: TestReport | None = None
    ) -> "StageAnswer":
        """The suite, executed, reported as it happened.

        No policy about failure. A red suite is this component's normal input:
        the healing loop exists because tests fail, and a stage that treated a
        failure as its own error would take the reader's result away.

        `declared` is the generation stage's report for the same version, and
        passing it is not optional bookkeeping. A runner reports names and
        outcomes and knows nothing about stories or criteria, so without it this
        stage returns a report with no traces at all, and the healing classifier,
        whose first signal is what a failing test traces to, can say nothing
        about any failure: it answers `undecided` every time, which reads like
        caution and is an absence of evidence. `untraced` on the report is the
        count that says so out loud.
        """
        repo = resolve(target)
        sandbox = Sandbox(repo.root)
        authored = origins_in(repo)
        steps: list[ToolStep] = []

        if repo.stack == "node":
            declare_measurement_tools(repo)
            installed = install(repo, sandbox)
            steps.append(_step(installed))
            if not installed.passed:
                # Nothing ran, and the report says so rather than reporting a
                # suite of no tests.
                return StageAnswer(
                    artefact=_empty_report(
                        version, repo, target, steps, "the workspace would not install"
                    ),
                    summary=f"the install {installed.outcome}, so nothing was run",
                    notes={"installed": False},
                )
            run = node_lane.run_tests(repo, sandbox, authored=authored)
        else:
            run = java_lane.build_and_test(repo, sandbox, authored=authored)
        steps.extend(_step(step) for step in run.steps)

        findings = quality.read_findings(repo)
        order = quality.OrderCheck(ran=False, reason="only the node lane shuffles")
        if repo.stack == "node":
            observed, order = quality.order_findings(repo, sandbox, run.suites)
            findings.extend(observed)

        report = TestReport(
            version=version,
            generated_at=_now(),
            target=_target_name(target, repo.kind),
            isolation=ISOLATION,
            steps=steps,
            suites=run.suites,
            coverage=run.coverage,
            quality=findings,
            mutation_skipped_reason="mutation is the quality stage's work, not this one's",
        )
        if declared is not None:
            report = with_traces_from(report, declared)
        return StageAnswer(
            artefact=report,
            summary=(
                f"{report.passed} passed, {report.failed} failed, {report.skipped} skipped"
                if run.ran
                else "the runner reported on no tests at all"
            ),
            notes={
                "failed": report.failed,
                "lineCoverage": report.line_coverage,
                "toolchain": toolchain(),
                "qualityFindings": len(findings),
                "declaredAndUnwritten": quality.unwritten(repo),
                # How many of this component's own tests reached the report
                # saying nothing about what they were written from. Anything
                # above zero is the classifier being handed cases it cannot
                # decide, and it used to be all of them with nothing said.
                "untraced": report.untraced,
                # Said out loud when it did not happen: a suite with no order
                # dependence found and a suite nobody checked look identical
                # in a list of findings.
                "orderChecked": order.ran or order.reason,
            },
        )

    async def measure_quality(
        self, target: TargetLike, report: TestReport, scope: list[str], *, version: int
    ) -> "StageAnswer":
        """Mutants, over the code the tests actually touched.

        The report comes back with its mutation result attached, or with the
        reason there is none. Those are the only two shapes: an absent score
        with no reason reads as a score of zero, and this component would
        rather say "the suite is red so nothing could be measured" than let a
        reader infer that nothing was killed.
        """
        repo = resolve(target)
        sandbox = Sandbox(repo.root)
        lane = node_lane if repo.stack == "node" else java_lane
        outcome = lane.run_mutation(repo, sandbox, scope, suite_is_green=_is_green(report))
        mutation = outcome.result

        # The run that produced the score also says which test killed what, so
        # the tests that kill nothing come out of it for free. This is the
        # detection half of the weak fill gate: the finding and the per arm
        # counts. Acting on it, sending a body back to be rewritten, waits for
        # the honesty guard's own targeted check, which answers the same
        # question for one test without a whole mutation pass.
        #
        # Unless nothing died at all, in which case nothing is accused. A run
        # that killed no mutant cannot tell a suite that asserts nothing from a
        # runner that never activated a mutant, and the second happens: Stryker
        # 10's vitest runner does exactly that against vitest 5, reporting a
        # green suite, most mutants uncovered and a score of zero. Without this
        # the report would have accused every test in the suite of being weak
        # because of somebody else's bug.
        usable, why_not = quality.attribution_is_usable(mutation)
        weak = quality.mutant_findings(report.suites, outcome.attribution) if usable else []
        measured = report.model_copy(
            update={
                "version": version,
                "steps": [*report.steps, *map(_step, outcome.steps or [outcome.step])],
                "mutation": mutation,
                "mutation_skipped_reason": "" if mutation else outcome.skipped_reason,
                "quality": [*report.quality, *weak],
            }
        )
        return StageAnswer(
            artefact=measured,
            summary=(
                f"mutation score {mutation.score}% over {len(mutation.scope)} files"
                + (
                    ", " + ", ".join(one.app for one in mutation.not_measured) + " not measured"
                    if mutation.not_measured
                    else ""
                )
                + (f", {len(weak)} tests killed nothing" if weak else "")
                if mutation
                else f"no mutation score: {outcome.skipped_reason}"
            ),
            notes={
                "mutants": mutation.total if mutation else 0,
                "scope": len(scope),
                # Said out loud when nobody looked: no weak tests found and no
                # mutation run are the same empty list in a report.
                "killsNothing": quality.weak_by_origin(report.suites, outcome.attribution)
                if usable
                else why_not,
            },
        )

    @reports_model_use
    async def heal(
        self,
        target: TargetLike,
        report: TestReport,
        *,
        from_code_version: int,
        to_code_version: int,
        contract_diff: ContractDiff | None = None,
        requirement_diff: RequirementDiff | None = None,
        changed_code: Sequence[ChangedCode] = (),
        version: int,
    ) -> "StageAnswer":
        """Classify every failure, repair only what is stale, judge every repair.

        The order is the argument. Nothing is repaired before it has been
        classified, because repairing a regression hides a bug; nothing is
        accepted before the guard has run, because a repair that passes is not
        the same as a repair that is honest; and a refused repair keeps its diff,
        because the refusals are what this component is judged on.

        `changed_code` is the production code that changed between the two
        versions, which is where the guard's third check breaks the code first.
        """
        repo = resolve(target)
        sandbox = Sandbox(repo.root)
        changes = changes_for(contract_diff, requirement_diff)
        changed: dict[str, set[int]] = {}
        for stretch in changed_code:
            changed.setdefault(stretch.path, set()).update(range(stretch.start, stretch.end + 1))
        aimed = {path: frozenset(lines) for path, lines in changed.items()}
        attempts: list[HealAttempt] = []

        for suite in report.suites:
            for case in suite.cases:
                if case.outcome not in ("failed", "errored"):
                    continue
                attempts.append(
                    await self._one_failure(
                        repo,
                        sandbox,
                        suite=suite,
                        case=case,
                        contract_diff=contract_diff,
                        requirement_diff=requirement_diff,
                        changes=changes,
                        changed=aimed,
                    )
                )

        healed = HealReport(
            version=version,
            generated_at=_now(),
            target=_target_name(target, repo.kind),
            from_code_version=from_code_version,
            to_code_version=to_code_version,
            attempts=attempts,
        )
        return StageAnswer(
            artefact=healed,
            summary=(
                f"{healed.healed} healed, {healed.refused} refused, "
                f"{healed.flagged_regressions} flagged as regressions"
            ),
            notes={
                "healed": healed.healed,
                "refused": healed.refused,
                "regressions": healed.flagged_regressions,
                # The gap between these two is the guard's effect made visible:
                # what a loop without one would have claimed, against what this
                # one stands behind.
                "naiveConvergence": healed.naive_convergence,
                "strictConvergence": healed.strict_convergence,
                "classifiedBy": summarise_verdicts({a.test_id: _as_verdict(a) for a in attempts}),
            },
        )

    async def _one_failure(
        self,
        repo: Any,
        sandbox: Any,
        *,
        suite: TestSuite,
        case: TestCase,
        contract_diff: ContractDiff | None,
        requirement_diff: RequirementDiff | None,
        changes: list[Any],
        changed: dict[str, frozenset[int]] | None = None,
    ) -> HealAttempt:
        """One failing test, from classification to verdict."""
        verdict = classify(case, contracts=contract_diff, requirements=requirement_diff)
        if verdict.needs_referee:
            verdict = await referee(
                self._referee_agent(), case, contracts=contract_diff, requirements=requirement_diff
            )

        base = {
            "test_id": case.id,
            "test_name": case.name,
            "suite_path": suite.path,
            "failure_message": case.message or "the runner reported no message",
            "classification": verdict.classification,
            "classified_by": verdict.classified_by,
            "evidence": verdict.evidence,
        }
        if verdict.classification != "brittle":
            # Flagged and left alone. A regression is the test telling the
            # truth, and an undecided failure is a question for a person.
            return HealAttempt(**base)

        source = repo.read(suite.path)
        repairer = self._repairer or (
            build_repairer(self._model, shape=self._repair_shape, thinking=self.thinking)
            if source is not None
            else None
        )
        if source is None or repairer is None:
            return HealAttempt(
                **base,
                refusal_reason="no-repair-produced",
                checks=[
                    GuardCheck(
                        name="test-code-only",
                        passed=False,
                        detail=(
                            "no repairer is configured, so nothing was attempted"
                            if source is not None
                            else f"{suite.path} is not in the target"
                        ),
                    )
                ],
            )

        outcome = await repair(
            repairer,
            case,
            source=source,
            path=suite.path,
            changes=changes,
            shape=self._repair_shape,
        )
        drafts = [draft.rendered() for draft in outcome.drafts]
        if not outcome.repaired or outcome.content is None:
            return HealAttempt(
                **base,
                attempts=outcome.attempts,
                rejected_drafts=drafts,
                refusal_reason=outcome.refusal_reason or "no-repair-produced",
            )

        before = guard_module.production_files(repo)
        repo.write(suite.path, outcome.content)
        checks = [guard_module.touched_only_test_code(before, guard_module.production_files(repo))]
        checks.append(
            guard_module.passes_unchanged_code(
                repo, sandbox, suite_path=suite.path, test_name=case.name
            )
        )
        killed: list[str] = []
        reached = kill_module.sources_under(repo, suite.path)
        if not reached:
            checks.append(
                GuardCheck(
                    name="kills-a-mutant",
                    passed=False,
                    detail=(
                        f"{suite.path} reaches no production code this pass could find, "
                        "through its imports or the app it loads, so the guard could not "
                        "ask whether it notices a fault"
                    ),
                )
            )
        else:
            for source_path, lines in guard_module.aims(reached, changed or {}):
                check, killed = guard_module.kills_a_mutant_check(
                    repo,
                    sandbox,
                    suite_path=suite.path,
                    test_name=case.name,
                    source_path=source_path,
                    lines=lines,
                )
                if check.passed:
                    break
            checks.append(check)

        refusal = guard_module.refusal_for(checks, unchecked=not reached)
        if refusal is not None:
            # Put the file back. A refused repair must leave no trace in the
            # repository beyond the record of having been refused.
            repo.write(suite.path, source)
        return HealAttempt(
            **base,
            attempts=outcome.attempts,
            rejected_drafts=drafts[:-1],
            diff=DiffSpan(path=suite.path, diff=outcome.diff),
            checks=checks,
            refusal_reason=refusal,
            killed_mutant_ids=killed,
        )

    def _referee_agent(self) -> Any:
        """The referee, built from the model on first use, as the repairer is.

        It was only ever injected, by this package's tests, so in the pipeline a
        failure the rules could not classify never reached it and stayed
        undecided. Built once and kept, at this component's thinking level; it
        asks the model only when something changed to show it (`referee`).
        """
        if self._referee is None:
            self._referee = build_referee(self._model, thinking=self.thinking)
        return self._referee

    def default_arms(self, repo: Any) -> list[Any]:
        """Which arms a stage runs when the caller named none.

        The scanner always, because it costs nothing, needs no key and answers
        the same way every time, which is what a stage a pipeline triggers
        should use. The prompted arm only when a caller supplied a detector
        agent, which is how it says it has decided to spend tokens. The scanner
        stays beside it rather than being replaced: an arm that costs money is
        judged against one that does not, and that comparison is the point.

        Split out so the choice can be tested without running the tools. The
        test that held this property used to read the method's source, which
        broke the moment the prompted arm became reachable, and then ran real
        scanners for four minutes when it was rewritten to run the stage.
        """
        chosen: list[Any] = [ScannerArm(repo=repo)]
        if self._detector is not None:
            chosen.append(LlmArm(agent=self._detector, model_id=self.model))
        if self._trained_model_dir:
            chosen.append(TrainedArm(model_dir=self._trained_model_dir))
        return chosen

    @reports_model_use
    async def scan(
        self,
        target: TargetLike,
        *,
        version: int,
        workspace: Path | str | None = None,
        files: list[str] | None = None,
        arms: list[Any] | None = None,
        tests: TestSummary | None = None,
    ) -> "StageAnswer":
        """The security stage: every arm over the same files, one report.

        `arms` defaults to the scanners alone, and that is a deliberate
        default rather than a placeholder. The scanner arm costs nothing per
        run, needs no key and answers the same way every time, so it is what a
        stage triggered by a pipeline should use. The model arms are handed in
        by a caller that has decided to spend tokens, which is a decision a
        person makes and not one a default makes for them.

        The report is the artefact; the study is a separate command. This
        produces what the pipeline and the gate need to see, and never a
        comparison table, because a table computed from one run of one project
        is not a result.
        """
        # Not `must_run`: the arms read source, and a repository with no
        # recognised build still has source in it.
        repo = resolve(target, workspace=workspace, must_run=False)
        detectors = arms if arms is not None else self.default_arms(repo)
        looked_at = files if files is not None else _source_files(repo)

        results = []
        for detector in detectors:
            results.append(await detector.scan(str(repo.root), looked_at))
        merged = merge_findings(str(repo.root), results, run_id=f"v{version}")

        report = ValidationReport(
            version=version,
            generated_at=_now(),
            target=_target_name(target, repo.kind),
            findings=merged.findings,
            refused_evidence=merged.refused,
            detector_runs=merged.runs,
            tools=merged.tools,
            # Null coverage and a null mutation score when the test stage has
            # not run, rather than zeros: zero coverage is a real measurement
            # and means the tests covered nothing.
            tests=tests or TestSummary(run=0, passed=0, failed=0, skipped=0, line_coverage=0.0),
        )
        return StageAnswer(
            artefact=report,
            summary=_scan_summary(merged, looked_at),
            notes={
                "byOrigin": merged.by_origin,
                "refused": len(merged.refused),
                "failures": merged.failures,
                "filesLookedAt": len(looked_at),
            },
        )

    async def reverify(
        self,
        before_validation: ValidationReport,
        before_tests: TestReport,
        after_validation: ValidationReport,
        after_tests: TestReport,
        *,
        before_run_id: str = "",
        after_run_id: str = "",
        finding_id: str = "",
        patch: Sequence[PatchHunk] = (),
    ) -> "StageAnswer":
        """Did the fix work, answered by subtraction, and is its finding gone.

        C3 measures and the orchestrator stores, which is why this returns a
        comparison rather than writing one. The two passes are refused when
        they were not measured the same way: a before pass with three arms and
        an after pass with one closes findings the patch never touched, and
        subtracting them would report that as a success.
        """
        try:
            result = compare(
                before_validation,
                before_tests,
                after_validation,
                after_tests,
                before_run_id=before_run_id,
                after_run_id=after_run_id,
                finding_id=finding_id,
                patch=patch,
            )
        except NotComparable as refusal:
            return StageAnswer(
                artefact=None,
                summary=f"the two passes cannot be compared: {refusal}",
                notes={"comparable": False, "reason": str(refusal)},
            )
        return StageAnswer(
            artefact=result,
            summary=rollback_advice(result),
            notes={
                "comparable": True,
                "findingsClosed": result.findings_closed,
                "testsBroken": result.tests_broken,
                "worsened": result.worsened,
                "findingClosed": result.finding_closed,
            },
        )

    @reports_model_use
    async def propose_remediation(
        self,
        target: TargetLike,
        report: ValidationReport,
        *,
        version: int = 1,
        workspace: Path | str | None = None,
        tests: TestReport | None = None,
        contract: ApiContract | None = None,
        limit: int = MAX_PROPOSALS,
    ) -> "StageAnswer":
        """A fix per finding worth fixing, for a person to accept or dismiss.

        C3 proposes and C2 applies. Nothing here edits the target: the patch
        travels on the artefact with a decision state, so the change a human
        approves is the change that gets made, and it gets made by the
        component that owns code generation.

        A finding no patch could be produced for stays open with its reason
        recorded. That is the honest outcome and it is deliberately not a
        shorter list: an open finding a reviewer can see is worth more than a
        tidy report that quietly dropped it.
        """
        repo = resolve(target, workspace=workspace, must_run=False)
        chosen, not_reached = candidates(report, limit=limit)
        run = ProposalRun(not_reached=not_reached)

        patcher = self._patcher or (
            build_patcher(self._model, thinking=self.thinking) if chosen else None
        )
        for finding in chosen:
            source = read_source(str(repo.root), finding.evidence.path)
            if source is None:
                run.unproposed.append(
                    Unproposed(
                        finding_id=finding.id,
                        cwe=finding.cwe,
                        reason=f"{finding.evidence.path} could not be read",
                    )
                )
                continue
            if patcher is None:
                run.unproposed.append(
                    Unproposed(
                        finding_id=finding.id,
                        cwe=finding.cwe,
                        reason="no patcher is configured, so nothing was attempted",
                    )
                )
                continue

            outcome = await propose_patch(patcher, finding, source=source)
            if not outcome.patched:
                run.unproposed.append(
                    Unproposed(
                        finding_id=finding.id,
                        cwe=finding.cwe,
                        reason=outcome.gave_up or "no usable patch was produced",
                    )
                )
                continue
            run.proposals.append(
                proposal_for(
                    finding,
                    outcome,
                    at=_now(),
                    tests=tests,
                    contract=contract,
                    source=source,
                )
            )

        artefact = run.artefact(version=version, target=_target_name(target, repo.kind), at=_now())
        return StageAnswer(
            artefact=artefact,
            summary=_remediation_summary(run, len(chosen)),
            notes={
                "proposed": len(run.proposals),
                "unproposed": [
                    {"findingId": item.finding_id, "cwe": item.cwe, "reason": item.reason}
                    for item in run.unproposed
                ],
                "notReached": run.not_reached,
                "byRisk": _by_risk(run),
            },
        )


#: What the arms are shown when nobody narrowed the scan. Source only: a scan
#: of `node_modules` measures somebody else's code and costs the model arms a
#: fortune to do it.
SCANNED_SUFFIXES = (".java", ".ts", ".tsx", ".js", ".jsx", ".py")
SKIPPED_DIRECTORIES = frozenset({"node_modules", "target", "dist", "build", ".git", "coverage"})


def _declaring_what_is_kept(
    produced: Generation, merged: dict, sprint: SprintPlan, contract: ApiContract
) -> Generation:
    """The generation, with each carried file described as it actually is.

    A carried file holds tests written against criteria the story no longer has,
    plus todos for the ones it gained. The cases `generate` built describe only
    the second group, so a report made from them would declare tests the file
    does not contain and omit the ones it does. Every count and every trace in
    the phase is built from these cases, and the run report's traces are matched
    back to them by id, so a case that does not exist is a test that arrives at
    the healing classifier with nothing to say.
    """
    if not merged:
        return produced

    stories = {one.id: one for one in (*sprint.proposed, *sprint.backlog)}
    files = dict(produced.files)
    cases = [case for case in produced.cases if case.suite_path not in merged]
    for path, one in merged.items():
        files[path] = one.content
        known = {case.name: case for case in produced.cases if case.suite_path == path}
        kind = next((case.kind for case in known.values()), "unit")
        describe = describe_of(one.content)
        for name in (*one.carried, *one.declared):
            if name in known:
                cases.append(known[name])
                continue
            story = stories.get(name.split(" ", 1)[0])
            cases.append(
                GeneratedCase(
                    suite_path=path,
                    id=case_id(path, describe, name),
                    name=name,
                    kind=kind,
                    # Written by the model at an earlier version. Calling it a
                    # skeleton would say the rules wrote a body they did not.
                    origin="filled" if name in one.carried else "skeleton",
                    story_id=story.id if story else None,
                    criterion_id=_criterion_in(name),
                    requirement_ids=list(story.traces) if story else [],
                    endpoint_ids=endpoints_of(story, contract) if story else [],
                )
            )
    return replace(produced, files=files, cases=cases)


def _criterion_in(name: str) -> str:
    """The criterion id a generated test's name carries, if it carries one.

    `US-1 AC-1-2: given ...`. Read back rather than looked up, because a carried
    test was written for a criterion its story no longer has, so there is
    nothing left to look it up in. This is what putting the id in the name
    bought.
    """
    head = name.split(":", 1)[0].split()
    return next((one for one in head if one.startswith("AC-")), "")


def _source_files(repo: Any) -> list[str]:
    """Every source file in the target, as the repository names them."""
    found: list[str] = []
    for path in sorted(Path(repo.root).rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        relative = path.relative_to(repo.root)
        if SKIPPED_DIRECTORIES & set(relative.parts):
            continue
        found.append(relative.as_posix())
    return found


def _remediation_summary(run: ProposalRun, looked_at: int) -> str:
    parts = [f"{len(run.proposals)} of {looked_at} findings have a proposed fix"]
    if run.unproposed:
        parts.append(f"{len(run.unproposed)} could not be patched and stay open")
    if run.not_reached:
        parts.append(f"{run.not_reached} more findings were not reached")
    return "; ".join(parts)


def _by_risk(run: ProposalRun) -> dict[str, int]:
    counts: dict[str, int] = {}
    for proposal in run.proposals:
        counts[proposal.risk.level] = counts.get(proposal.risk.level, 0) + 1
    return counts


def _scan_summary(merged: Merged, looked_at: list[str]) -> str:
    counts = merged.by_origin
    where = ", ".join(f"{count} from {origin}" for origin, count in sorted(counts.items()))
    parts = [f"{len(merged.findings)} findings over {len(looked_at)} files"]
    if where:
        parts.append(where)
    if merged.refused:
        parts.append(f"{len(merged.refused)} refused for evidence that did not resolve")
    if merged.failures:
        parts.append(f"{len(merged.failures)} tools did not run")
    return "; ".join(parts)


def _as_verdict(attempt: HealAttempt):
    """A recorded attempt back as a verdict, for counting how each was reached.

    The report is the record; the counts are read off it rather than kept
    beside it, so the two cannot disagree.
    """
    return Verdict(
        classification=attempt.classification,
        classified_by=attempt.classified_by,
        evidence=attempt.evidence,
    )


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _step(step: StepResult) -> ToolStep:
    return ToolStep(
        name=step.name,
        command=step.command,
        outcome=step.outcome,
        duration_seconds=step.duration_seconds,
        log_tail=step.tail,
    )


def _is_green(report: TestReport) -> bool:
    """Whether every case that ran passed, and some did.

    The same rule the lane applies to its own run, applied to a report that
    arrived from somewhere else: no cases is not a clean suite.
    """
    return report.total > 0 and report.failed == 0


def _empty_report(
    version: int, repo: Any, target: TargetLike, steps: list[ToolStep], why: str
) -> TestReport:
    return TestReport(
        version=version,
        generated_at=_now(),
        target=_target_name(target, repo.kind),
        isolation=ISOLATION,
        steps=steps,
        mutation_skipped_reason=why,
    )


def _with_fills(manifest: list[ManifestRow], filled: set[str]) -> list[ManifestRow]:
    """Which generator wrote a file has to stay a fact, per file."""
    return [
        row.model_copy(update={"generator": "llm"}) if row.path in filled else row
        for row in manifest
    ]


def _summary(produced: Generation, fills: list[FillResult]) -> str:
    accepted = sum(1 for result in fills if result.accepted)
    if not fills:
        return produced.summary
    written = sum(len(result.filled) for result in fills if result.accepted)
    return f"{produced.summary}, {written} of them written by the model in {accepted} files"


def _target_name(target: TargetLike, kind: str) -> str:
    """What a report calls the thing it measured.

    Named so a number can never be attributed to the wrong target: the
    generated project says which code version it was, and a sample says which
    sample.
    """
    if kind == "generated":
        return f"the generated app at code version {target.code_version}"
    if kind == "sample":
        return f"the {target.path or 'java'} sample"
    return f"a benchmark checkout at {target.path}"


__all__ = ["C3", "GeneratedTests", "HealReport", "NotBuilt", "RemediationProposal", "TestReport"]
