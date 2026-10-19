"""How the orchestrator reaches Component 3.

The same seam C1 and C2 have: one protocol, two implementations, chosen by
configuration, with the generated contract types crossing the boundary either
way. Nothing in the orchestrator knows how a mutant is injected or how a
finding is scored.

Two shapes here are not C2's, because C3 produces two things a code stage does
not. Test generation writes files, so it answers with bodies to store plus a
manifest, exactly as the code stages do. But healing answers with a report
whose refusals matter as much as its repairs, and scanning answers with a
report whose arms have to stay distinguishable, so both cross as their whole
artefact rather than as a summary the orchestrator would have to reassemble.

`StageOutcome` is imported rather than copied, as C2 imported it: it is one
shape, and it happened to be written for C1 first.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from sdlc_contracts import (
    ApiContract,
    ChangedCode,
    ContractDiff,
    HealReport,
    ManifestRow,
    PatchHunk,
    RemediationProposal,
    RequirementDiff,
    Reverification,
    SprintPlan,
    TestReport,
    ValidationReport,
)

from .c1 import StageOutcome
from .thinking import Levelled, thinking_sent

#: A testing run does real work in a sandbox: an npm install, a Maven wrapper
#: fetching the world on a cold cache, a mutation pass. Longer than C2's stage
#: timeout for the same reason C2's is longer than C1's.
STAGE_TIMEOUT_SECONDS = 900.0


@dataclass(frozen=True)
class TestFilesOutcome:
    """What test generation produced.

    The bodies are stored and served from their own route, and the manifest is
    what the snapshot carries: the snapshot is polled while a run is in flight
    and a generated suite is tens of files.
    """

    files: dict[str, str]
    manifest: list[ManifestRow]
    summary: str
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetRef:
    """Which repository a stage should work on.

    A reference rather than a path, because the three kinds of target resolve
    differently: the generated monorepo comes out of the file store at a code
    version, the Spring sample is checked into this repository, and a benchmark
    is a checkout the evaluation made. The component resolves it; the
    orchestrator only says which one it means.
    """

    kind: str
    #: The generated monorepo's code version, when kind says so.
    code_version: int | None = None
    #: A path, for the sample and for benchmark checkouts.
    path: str = ""


class C3Client(Protocol):
    """The six stage calls Component 3 answers.

    Per stage for C1's reason: each is a stage the reader watches move, and a
    crash should cost the stage that was running rather than the run.

    Generation and execution are separate calls because one spends model calls
    and the other does not. Execution and quality are separate because mutation
    is minutes where a run is seconds, and a reader should see the suite go
    green before the mutants have finished dying.
    """

    #: What produced the artefacts, for the record on a run.
    model: str

    async def generate_tests(
        self,
        target: TargetRef,
        sprint: SprintPlan,
        contract: ApiContract,
        openapi: dict[str, Any],
        *,
        version: int,
    ) -> TestFilesOutcome: ...

    async def run_tests(
        self, target: TargetRef, *, version: int, declared: TestReport | None = None
    ) -> StageOutcome[TestReport]: ...

    async def measure_quality(
        self, target: TargetRef, report: TestReport, scope: list[str], *, version: int
    ) -> StageOutcome[TestReport]: ...

    async def heal(
        self,
        target: TargetRef,
        report: TestReport,
        *,
        from_code_version: int,
        to_code_version: int,
        contract_diff: ContractDiff | None,
        requirement_diff: RequirementDiff | None,
        changed_code: Sequence[ChangedCode] = (),
        version: int,
        from_test_version: int | None = None,
    ) -> StageOutcome[HealReport]: ...

    async def scan(self, target: TargetRef, *, version: int) -> StageOutcome[ValidationReport]: ...

    async def propose_remediation(
        self,
        target: TargetRef,
        report: ValidationReport,
        *,
        tests: TestReport | None = None,
        contract: ApiContract | None = None,
    ) -> StageOutcome[list[RemediationProposal]]: ...

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
    ) -> StageOutcome[Reverification | None]: ...

    def targets(self) -> list[dict[str, str]]:
        """What this component can be pointed at. Not a run, so not async."""
        ...

    async def decide_test(
        self, source: str, name: str, *, decision: str, by: str, reason: str, on: str
    ) -> str | None:
        """A person's decision about one failing test, made in its file.

        The file as it should now read, or None when it does not hold the test
        as the decision needs it. C3's, because the test files are.
        """
        ...


class StageNotApplicable(RuntimeError):
    """This stage has nothing to do on this target, and that is not an error.

    The component raises its own `NotBuilt` and this client translates it,
    which is where the translation belongs: the orchestrator agrees with C3 on
    attribute names and nothing else, and importing the component's exception
    class into the graph would make the seam a shared type again.

    Carried rather than swallowed, because a stage that did not apply and does
    not say so is indistinguishable from one that quietly did nothing.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InProcessC3:
    """The component, imported and called directly.

    The import is deferred to construction, so an orchestrator deployed to talk
    to C3 over HTTP does not need the component's dependencies installed.
    """

    def __init__(
        self,
        model: Any,
        *,
        arms: str = "scanner",
        trained_model_dir: str = "",
        thinking: str = "off",
    ) -> None:
        try:
            from c3.agents import settings_for
            from c3.detect import build_detector
            from c3.service import C3
        except ModuleNotFoundError as exc:  # pragma: no cover - deployment shape
            # Only when `c3` itself is absent. C2's version of this caught every
            # ModuleNotFoundError, so a broken import *inside* the component
            # reported itself as "the component is not installed", which sent
            # the reader to their dependencies instead of to the real missing
            # module. It cost ten minutes here the first time it happened.
            if (exc.name or "").split(".")[0] != "c3":
                raise
            raise RuntimeError(
                "C3_MODE is 'inprocess' but the component is not installed. "
                "Install the sdlc-c3 package, or set C3_MODE=http and C3_BASE_URL."
            ) from exc
        named = {one.strip() for one in arms.split(",") if one.strip()}

        # Built here rather than inside the component, because deciding to
        # spend tokens on every run is a deployment's decision and the
        # component should not be able to make it for itself.
        def build(level: str) -> Any:
            return C3(
                model,
                detector=build_detector(model, thinking=level) if "llm" in named else None,
                trained_model_dir=trained_model_dir if "trained" in named else "",
                thinking=level,
            )

        # One component per thinking level, as C1's client keeps them (3B).
        self._levels = Levelled(build, thinking, opens=False)
        self._model = model
        self._settings_for = settings_for
        self.model = model if isinstance(model, str) else str(model)
        #: The configured level, which a run uses where its account chose none.
        self.level = thinking
        # What every agent's request says about thinking, as C1's client reads it.
        self.thinking = self.thinking_for(thinking)

    @property
    def _component(self) -> Any:
        """The component at the configured level."""
        return self._levels.configured

    def thinking_for(self, level: str) -> str:
        """What this component's requests say about thinking at a level, as a run records it."""
        return thinking_sent(self._settings_for(self._model, thinking=level))

    @staticmethod
    @asynccontextmanager
    async def _translating() -> AsyncIterator[None]:
        """Turn the component's "not built for this" into the seam's word for it."""
        from c3.service import NotBuilt

        try:
            yield
        except NotBuilt as refusal:
            raise StageNotApplicable(str(refusal)) from refusal

    async def generate_tests(
        self,
        target: TargetRef,
        sprint: SprintPlan,
        contract: ApiContract,
        openapi: dict[str, Any],
        *,
        version: int,
    ) -> TestFilesOutcome:
        async with self._translating():
            outcome = await (await self._levels.current()).generate_tests(
                target, sprint, contract, openapi, version=version
            )
        return TestFilesOutcome(
            files=outcome.files,
            manifest=outcome.manifest,
            summary=outcome.summary,
            notes=outcome.notes,
        )

    async def run_tests(
        self, target: TargetRef, *, version: int, declared: TestReport | None = None
    ) -> StageOutcome[TestReport]:
        async with self._translating():
            answer = await (await self._levels.current()).run_tests(
                target, version=version, declared=declared
            )
        return StageOutcome(artefact=answer.artefact, summary=answer.summary, notes=answer.notes)

    async def measure_quality(
        self, target: TargetRef, report: TestReport, scope: list[str], *, version: int
    ) -> StageOutcome[TestReport]:
        answer = await (await self._levels.current()).measure_quality(
            target, report, scope, version=version
        )
        return StageOutcome(artefact=answer.artefact, summary=answer.summary, notes=answer.notes)

    async def heal(
        self,
        target: TargetRef,
        report: TestReport,
        *,
        from_code_version: int,
        to_code_version: int,
        contract_diff: ContractDiff | None,
        requirement_diff: RequirementDiff | None,
        changed_code: Sequence[ChangedCode] = (),
        version: int,
        from_test_version: int | None = None,
    ) -> StageOutcome[HealReport]:
        answer = await (await self._levels.current()).heal(
            target,
            report,
            from_code_version=from_code_version,
            to_code_version=to_code_version,
            contract_diff=contract_diff,
            requirement_diff=requirement_diff,
            changed_code=changed_code,
            version=version,
            from_test_version=from_test_version,
        )
        return StageOutcome(artefact=answer.artefact, summary=answer.summary, notes=answer.notes)

    async def scan(self, target: TargetRef, *, version: int) -> StageOutcome[ValidationReport]:
        return await (await self._levels.current()).scan(target, version=version)

    async def propose_remediation(
        self,
        target: TargetRef,
        report: ValidationReport,
        *,
        tests: TestReport | None = None,
        contract: ApiContract | None = None,
    ) -> StageOutcome[list[RemediationProposal]]:
        """The proposals, unwrapped from the artefact the component builds.

        C3 returns a whole `RemediationProposals`, carrying a version, a target
        and a timestamp of its own. The seam passes the list, because the
        orchestrator owns the version axis and stamps those three fields from
        run state: two sources for one version number is how a stored artefact
        comes to disagree with the row it is stored in.

        The HTTP client already read `payload["proposals"]`, so this was the
        one implementation of three that answered a different shape. Passing
        the model through made pydantic iterate it into `('version', 1)`
        tuples, which is what the first live run of this stage reported. The
        canned client returns an empty list, so no walk before that one could
        have found it.
        """
        # The run's tests and the contract are what each fix's risk is counted
        # from: without them every statement said no test covers the change
        # and no endpoint moves (review item C3-11).
        outcome = await (await self._levels.current()).propose_remediation(
            target, report, tests=tests, contract=contract
        )
        return StageOutcome(
            artefact=list(outcome.artefact.proposals),
            summary=outcome.summary,
            notes=outcome.notes,
        )

    def targets(self) -> list[dict[str, str]]:
        return self._component.targets()

    async def decide_test(
        self, source: str, name: str, *, decision: str, by: str, reason: str, on: str
    ) -> str | None:
        return self._component.decide_test(source, name, decision, by=by, reason=reason, on=on)

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
    ) -> StageOutcome[Reverification | None]:
        return await (await self._levels.current()).reverify(
            before_validation,
            before_tests,
            after_validation,
            after_tests,
            before_run_id=before_run_id,
            after_run_id=after_run_id,
            finding_id=finding_id,
            patch=patch,
        )


class HttpC3:
    """The component, over the wire.

    Every response is validated into the contract type on arrival, so a service
    answering the wrong shape is caught at the boundary it crossed rather than
    three stages later.
    """

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = f"whatever {self._base_url} is running"
        self._client = client
        self._owned = client is None

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=STAGE_TIMEOUT_SECONDS)
        try:
            answer = await client.post(f"{self._base_url}{path}", json=body)
            answer.raise_for_status()
            return answer.json()
        finally:
            if self._owned:
                await client.aclose()

    @staticmethod
    def _target(target: TargetRef) -> dict[str, Any]:
        return {"kind": target.kind, "codeVersion": target.code_version, "path": target.path}

    async def generate_tests(
        self,
        target: TargetRef,
        sprint: SprintPlan,
        contract: ApiContract,
        openapi: dict[str, Any],
        *,
        version: int,
    ) -> TestFilesOutcome:
        payload = await self._post(
            "/generate-tests",
            {
                "target": self._target(target),
                "sprint": sprint.model_dump(by_alias=True),
                "contract": contract.model_dump(by_alias=True),
                "openapi": openapi,
                "version": version,
            },
        )
        return TestFilesOutcome(
            files=payload["files"],
            manifest=[ManifestRow.model_validate(row) for row in payload["manifest"]],
            summary=payload.get("summary", ""),
            notes=payload.get("notes", {}),
        )

    async def run_tests(
        self, target: TargetRef, *, version: int, declared: TestReport | None = None
    ) -> StageOutcome[TestReport]:
        payload = await self._post(
            "/validate",
            {
                "target": self._target(target),
                "version": version,
                # The generation stage's report for the same version. The runner
                # knows nothing about stories or criteria, so without this the
                # answer carries no traces and the healing classifier has no
                # first signal.
                "declared": None
                if declared is None
                else declared.model_dump(by_alias=True, mode="json"),
            },
        )
        return StageOutcome(
            artefact=TestReport.model_validate(payload["report"]),
            summary=payload.get("summary", ""),
            notes=payload.get("notes", {}),
        )

    async def measure_quality(
        self, target: TargetRef, report: TestReport, scope: list[str], *, version: int
    ) -> StageOutcome[TestReport]:
        payload = await self._post(
            "/validate/quality",
            {
                "target": self._target(target),
                "report": report.model_dump(by_alias=True),
                "scope": scope,
                "version": version,
            },
        )
        return StageOutcome(
            artefact=TestReport.model_validate(payload["report"]),
            summary=payload.get("summary", ""),
            notes=payload.get("notes", {}),
        )

    async def heal(
        self,
        target: TargetRef,
        report: TestReport,
        *,
        from_code_version: int,
        to_code_version: int,
        contract_diff: ContractDiff | None,
        requirement_diff: RequirementDiff | None,
        changed_code: Sequence[ChangedCode] = (),
        version: int,
        from_test_version: int | None = None,
    ) -> StageOutcome[HealReport]:
        payload = await self._post(
            "/self-heal",
            {
                "target": self._target(target),
                "report": report.model_dump(by_alias=True),
                "fromCodeVersion": from_code_version,
                "toCodeVersion": to_code_version,
                "contractDiff": contract_diff.model_dump(by_alias=True) if contract_diff else None,
                "requirementDiff": requirement_diff.model_dump(by_alias=True)
                if requirement_diff
                else None,
                "changedCode": [stretch.model_dump(by_alias=True) for stretch in changed_code],
                "version": version,
                "fromTestVersion": from_test_version,
            },
        )
        return StageOutcome(
            artefact=HealReport.model_validate(payload["report"]),
            summary=payload.get("summary", ""),
            notes=payload.get("notes", {}),
        )

    async def scan(self, target: TargetRef, *, version: int) -> StageOutcome[ValidationReport]:
        payload = await self._post("/scan", {"target": self._target(target), "version": version})
        return StageOutcome(
            artefact=ValidationReport.model_validate(payload["report"]),
            summary=payload.get("summary", ""),
            notes=payload.get("notes", {}),
        )

    async def propose_remediation(
        self,
        target: TargetRef,
        report: ValidationReport,
        *,
        tests: TestReport | None = None,
        contract: ApiContract | None = None,
    ) -> StageOutcome[list[RemediationProposal]]:
        payload = await self._post(
            "/remediate",
            {
                "target": self._target(target),
                "report": report.model_dump(by_alias=True),
                "tests": tests.model_dump(by_alias=True) if tests is not None else None,
                "contract": contract.model_dump(by_alias=True) if contract is not None else None,
            },
        )
        return StageOutcome(
            artefact=[RemediationProposal.model_validate(row) for row in payload["proposals"]],
            summary=payload.get("summary", ""),
            notes=payload.get("notes", {}),
        )

    def targets(self) -> list[dict[str, str]]:
        """The generated application only.

        A component over the wire has its own fixtures directory, and this
        client cannot see it without a round trip that every caller of this
        would have to await. The generated application is the one target that
        is true of any deployment; a remote C3 with samples to offer needs a
        route here and this returning what it answers.
        """
        return [
            {
                "id": "generated",
                "label": "The generated application",
                "stack": "node",
                "detail": "The repository this project's code phase produced.",
            }
        ]

    async def decide_test(
        self, source: str, name: str, *, decision: str, by: str, reason: str, on: str
    ) -> str | None:
        payload = await self._post(
            "/test-decision",
            {
                "source": source,
                "name": name,
                "decision": decision,
                "by": by,
                "reason": reason,
                "on": on,
            },
        )
        return payload.get("source")

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
    ) -> StageOutcome[Reverification | None]:
        payload = await self._post(
            "/reverify",
            {
                "beforeValidation": before_validation.model_dump(by_alias=True),
                "beforeTests": before_tests.model_dump(by_alias=True),
                "afterValidation": after_validation.model_dump(by_alias=True),
                "afterTests": after_tests.model_dump(by_alias=True),
                "beforeRunId": before_run_id,
                "afterRunId": after_run_id,
                "findingId": finding_id,
                "patch": [hunk.model_dump(by_alias=True) for hunk in patch],
            },
        )
        body = payload.get("reverification")
        return StageOutcome(
            # Null when the two passes were not comparable, which is an answer
            # rather than a failure: the notes carry the reason.
            artefact=Reverification.model_validate(body) if body else None,
            summary=payload.get("summary", ""),
            notes=payload.get("notes", {}),
        )


def make_c3_client(
    mode: str,
    *,
    model: str,
    base_url: str,
    arms: str = "scanner",
    trained_model_dir: str = "",
    thinking: str = "off",
) -> C3Client:
    """The client the configuration asks for."""
    if mode == "http":
        return HttpC3(base_url)
    return InProcessC3(model, arms=arms, trained_model_dir=trained_model_dir, thinking=thinking)
