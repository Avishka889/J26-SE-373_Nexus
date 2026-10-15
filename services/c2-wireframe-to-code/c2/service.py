"""Component 2 as something the orchestrator can call, one stage at a time.

The same split as C1, for the same reasons: the orchestrator owns the process
(which stages exist, their order, the gate), this component owns the
generation. Per stage rather than one generate_everything(), so each stage
flips generating then complete on its own and a crash costs one stage.

Agents are built once and kept, because each owns a provider connection. The
model armed stages (the LLM contract arm, the stack explanation, the optional
body fills) all degrade honestly: a failed LLM arm is recorded beside the rule
arm that always exists, a refused explanation ships the arithmetic alone, and
a refused fill ships the rule body with the manifest still saying `rule`.
"""

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from types import TracebackType
from typing import Any, Literal, Self

import httpx
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from sdlc_contracts import (
    ApiContract,
    ApiContractArtefact,
    ArchitectureGraph,
    ArchitectureRecommendation,
    BuildReport,
    ContractAgreement,
    ContractRuleFinding,
    EarlierPage,
    ParsedRequirement,
    RepositoryPointer,
    SprintPlan,
    SprintScope,
    TechStackArtefact,
    WireframesArtefact,
)

from .codegen.api_gen import api_app
from .codegen.client_gen import contract_package
from .codegen.fill import (
    build_handler_filler,
    build_page_filler,
    check_page_fill,
    dropped_headers,
    fill_handler,
    fill_page,
    lost_the_record,
    page_digest,
)
from .codegen.manifest import FileSet, GeneratedFile
from .codegen.monorepo import scaffold
from .codegen.naming import client_method_name
from .codegen.web_gen import page_flows, web_app
from .contract.field_rules import with_field_rules
from .contract.llm_arm import (
    CouldNotInferContract,
    build_contract_agent,
    infer_llm_contract,
)
from .contract.merge import compare_arms, merge_contracts
from .contract.rule_arm import generate_rule_contract
from .contract.rules import ContractContext, validate_contract
from .model_use import reports_model_use
from .repo.github import LandResult, PushResult, land, push_monorepo
from .rules.scope import derive_scope as derive_scope_by_rules
from .sandbox import BuildStep, run_build
from .stack.explain import build_stack_explainer, prompt_for
from .stack.scoring import gather_stack_facts, score_stacks

Arm = Literal["rule", "llm", "merged"]

log = logging.getLogger(__name__)


def _call_failed(error: BaseException) -> str:
    """Why a model call failed, in words, without the provider's body.

    A body can carry the account's organisation, its tier and its quota, none
    of which belongs in a stage's notes.
    """
    if isinstance(error, ModelHTTPError):
        if error.status_code == 429:
            return "the provider is rate limiting this account"
        return f"the provider answered {error.status_code}"
    if isinstance(error, UnexpectedModelBehavior):
        return "the model's answer never came in the shape asked for"
    return f"the call failed ({type(error).__name__})"


@dataclass(frozen=True)
class StageResult[T]:
    """What one stage produced, and what it cost."""

    artefact: T
    #: The one line posted into the thread when the stage finishes.
    summary: str
    #: Honesty metrics for the evaluation: attempts, refusals, failures.
    #: Recorded in the audit log, never in the artefact.
    notes: dict[str, Any] = field(default_factory=dict)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


#: What compiling a model's pages takes: the install, and the web app's typecheck.
COMPILE_STEPS = (
    BuildStep(name="install", command=("npm", "install", "--no-audit", "--no-fund")),
    BuildStep(name="typecheck", command=("npm", "run", "typecheck", "--workspace", "@app/web")),
)

#: A compiler error line, as tsc prints it from inside `apps/web`.
_TSC_ERROR = re.compile(r"^(src/[^(\s]+)\(\d+,\d+\): (error TS\d+: .*)$", re.MULTILINE)


class C2:
    """Component 2, in process. One instance per orchestrator process."""

    def __init__(
        self,
        model: str | Model,
        *,
        build: Callable[..., BuildReport] = run_build,
        thinking: str = "off",
    ) -> None:
        self.model = model
        #: How hard the stages ask the model to think (`agents.THINKING_LEVELS`).
        self.thinking = thinking
        #: What compiles a model's pages before they ship; tests script it.
        self._build = build
        self._contract_agent = build_contract_agent(model, thinking=thinking)
        self._explainer = build_stack_explainer(model, thinking=thinking)
        self._page_filler = build_page_filler(model, thinking=thinking)
        self._handler_filler = build_handler_filler(model, thinking=thinking)
        #: For the GitHub push; opened with the agents, closed with them.
        self._http = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self) -> Self:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        for agent in (
            self._contract_agent,
            self._explainer,
            self._page_filler,
            self._handler_filler,
        ):
            await self._stack.enter_async_context(agent)
        await self._stack.enter_async_context(self._http)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        stack = getattr(self, "_stack", None)
        if stack is not None:
            await stack.__aexit__(exc_type, exc, tb)
            self._stack = None

    async def derive_scope(
        self, sprint: SprintPlan, wireframes: WireframesArtefact
    ) -> StageResult[SprintScope]:
        """Rules only: the proposed sprint, traced to screens. No model call."""
        scope = derive_scope_by_rules(sprint, wireframes)
        in_scope = [story for story in scope.stories if story.id in scope.in_scope_ids]
        screens = {screen for story in in_scope for screen in story.traces.screen_ids}
        return StageResult(
            artefact=scope,
            summary=(
                f"Sprint scope proposed: {_plural(len(in_scope), 'story', 'stories')} "
                f"across {_plural(len(screens), 'screen')}"
            ),
            notes={"stories_total": len(scope.stories), "stories_in_scope": len(in_scope)},
        )

    @reports_model_use
    async def propose_stack(
        self,
        graph: ArchitectureGraph,
        recommendation: ArchitectureRecommendation | None = None,
    ) -> StageResult[TechStackArtefact]:
        """Arithmetic over counted facts; the explanation is guarded prose."""
        facts = gather_stack_facts(graph, recommendation)
        artefact = score_stacks(facts)

        recommended = next(c for c in artefact.candidates if c.id == artefact.recommended_id)
        explainer_error = None
        try:
            reasons = [part.label for part in recommended.score_breakdown if part.points]
            result = await self._explainer.run(
                prompt_for(recommended.name, facts, reasons), deps=facts
            )
            explained = recommended.model_copy(update={"explanation": result.output.rationale})
            artefact = artefact.model_copy(
                update={
                    "candidates": [
                        explained if c.id == recommended.id else c for c in artefact.candidates
                    ]
                }
            )
        except Exception as error:  # The arithmetic ships either way.
            explainer_error = f"{type(error).__name__}: {error}"

        summary = f"Tech stack proposed: {recommended.name} (score {recommended.score})"
        if not recommended.available:
            summary += ", recommended but not generatable yet"
        return StageResult(
            artefact=artefact,
            summary=summary,
            notes={
                "explained": explainer_error is None,
                **({"explainer_error": explainer_error} if explainer_error else {}),
            },
        )

    @reports_model_use
    async def infer_contract(
        self,
        version: int,
        graph: ArchitectureGraph,
        wireframes: WireframesArtefact,
        scope: SprintScope,
        *,
        arm: Arm = "rule",
        criteria: Sequence[str] = (),
    ) -> StageResult[ApiContractArtefact]:
        """Both arms, always: the rule arm cannot fail, the LLM arm may, and a
        failure is recorded beside the arm that worked rather than replacing it.

        `criteria` are the acceptance criteria of the stories in the build. With
        the design's constraints, they are read for the bounds they state on a
        field (`with_field_rules`), the same way over every arm: those bounds
        were words in a handler's comment, and the app took any value.
        """
        rules = [node.label for node in graph.nodes if node.kind == "constraint"] + list(criteria)
        rule = with_field_rules(generate_rule_contract(version, graph, wireframes, scope), rules)
        context = ContractContext(graph=graph, wireframes=wireframes, scope=scope)
        rule_report = validate_contract(rule, context)

        llm: ApiContract | None = None
        llm_failure: str | None = None
        llm_attempts = 0
        llm_notes: dict[str, Any] = {}
        try:
            llm, report = await infer_llm_contract(
                self._contract_agent, version=version, context=context
            )
            llm = with_field_rules(llm, rules)
            llm_attempts = report.attempts
            llm_notes = {"llm_attempts": report.attempts, "llm_repaired": report.repaired}
        except CouldNotInferContract as error:
            llm_failure = str(error)
        except Exception as error:  # Provider errors are failures of the arm, not the stage.
            llm_failure = f"{type(error).__name__}: {error}"

        comparison = (
            compare_arms(
                rule,
                llm,
                rule_report=rule_report,
                llm_report=validate_contract(llm, context),
                llm_attempts=llm_attempts,
            )
            if llm is not None
            else None
        )
        chosen: Arm = arm
        if llm is None and arm != "rule":
            # The requested arm needs the model's output and there is none.
            chosen = "rule"
        contract = {
            "rule": rule,
            "llm": llm if llm is not None else rule,
            "merged": with_field_rules(merge_contracts(rule, llm), rules)
            if llm is not None
            else rule,
        }[chosen]
        bounded = sum(
            1
            for entity in contract.entities
            for one in entity.fields
            if one.minimum is not None
            or one.maximum is not None
            or one.min_length is not None
            or one.max_length is not None
            or one.one_of
        )

        artefact = ApiContractArtefact(
            version=version,
            rule_arm=rule,
            llm_arm=llm,
            llm_failure=llm_failure,
            chosen=chosen,
            contract=contract,
            comparison=comparison,
            rule_findings=[
                ContractRuleFinding(
                    rule_id=finding.rule_id,
                    severity=finding.severity,
                    reason=finding.reason,
                    subject=finding.subject,
                )
                for finding in rule_report.findings
            ],
        )
        summary = (
            f"API contract inferred: {_plural(len(contract.endpoints), 'endpoint')} "
            f"from the {chosen} arm"
        )
        if comparison is not None:
            summary += f", arms agree on {comparison.agreement_rate:.0%} of the union"
        if llm_failure is not None:
            summary += ", the LLM arm failed and the rule arm stands"
        if bounded:
            summary += f", {_plural(bounded, 'field rule')} read from the design and the criteria"
        return StageResult(
            artefact=artefact,
            summary=summary,
            notes={
                "rule_endpoints": len(rule.endpoints),
                "bounded_fields": bounded,
                "chosen": chosen,
                "requested_arm": arm,
                **llm_notes,
                **({"llm_failure": llm_failure} if llm_failure else {}),
            },
        )

    @reports_model_use
    async def generate_frontend(
        self,
        project_name: str,
        contract: ApiContract,
        wireframes: WireframesArtefact,
        scope: SprintScope,
        *,
        design_version: int,
        arm: str,
        fill: bool = False,
        requirements: list[ParsedRequirement] | None = None,
        earlier: Sequence[EarlierPage] = (),
    ) -> StageResult[FileSet]:
        """The scaffold, the contract package and the web app, by rule; page
        bodies optionally rewritten by the model under post checked constraints.

        A rewritten page is told what its flow's requirements say, and the app is
        compiled once they are all written: a page the compiler refuses goes back
        to the rule page, with the compiler's words recorded as the reason.

        `earlier` is what the previous generation made of each page. A page
        whose inputs have not changed since keeps it, rewrite or refusal, without
        asking the model again (`_fill_pages`): each regeneration rewrote every
        page afresh, so pages for stories nobody had touched came out different
        every time, and each was paid for again.
        """
        files = scaffold(project_name, design_version=design_version, arm=arm)
        files.extend(contract_package(contract, f"{arm} arm"))
        files.extend(web_app(contract, wireframes, scope, project_name))

        filled, refused, reused = 0, 0, 0
        unasked: list[str] = []
        reverted: dict[str, str] = {}
        if fill:
            allowed = {client_method_name(endpoint.id) for endpoint in contract.endpoints}
            texts = {one.id: one.text for one in requirements or []}
            said = {
                path: [texts[rid] for rid in flow.traces if rid in texts]  # type: ignore[attr-defined]
                for path, flow in page_flows(wireframes, scope).items()
            }
            originals = {
                one.path: one.content
                for one in files.files
                if one.path.startswith("apps/web/src/pages/") and one.generator == "rule"
            }
            filled, refused, reused, unasked = await self._fill_pages(
                files, originals, said, allowed, {one.path: one for one in earlier}
            )
            if filled:
                reverted = await self._compile_filled(files, originals)

        pages = sum(1 for f in files.files if f.path.startswith("apps/web/src/pages/"))
        summary = f"Frontend generated: {_plural(pages, 'page')}, typed client included"
        kept = filled - len(reverted)
        if fill:
            summary += (
                f", {kept} written by the model"
                + (f", {refused} refused" if refused else "")
                + (f", {reused} unchanged since an earlier version" if reused else "")
                + (
                    f", {len(unasked)} kept as generated because the model call failed"
                    if unasked
                    else ""
                )
            )
            if reverted:
                summary += f", {len(reverted)} put back for not compiling"
        return StageResult(
            artefact=files,
            summary=summary,
            notes={
                "files": len(files.files),
                "model_filled": kept,
                "fill_refused": refused,
                "fill_reverted": reverted,
                "fill_reused": reused,
                "fill_failed": unasked,
            },
        )

    async def _compile_filled(self, files: FileSet, originals: dict[str, str]) -> dict[str, str]:
        """Compile the app with the model's pages in it; put back each page it refuses.

        The fill's own checks read the text: which client methods it calls, that
        its headers stayed. None of them compiles it, and a rewritten page that
        does not compile fails the build two stages later, reading as the app's
        fault. The compiler is asked once for the whole web app. A page it names
        goes back to its rule page; when it fails and names none of them, or
        cannot be asked at all, every rewritten page goes back, because shipping
        a page nothing compiled is the thing this check exists to stop.
        """
        written = [
            one.path for one in files.files if one.generator == "model" and one.path in originals
        ]
        report = await asyncio.to_thread(
            self._build,
            {one.path: one.content for one in files.files},
            steps=COMPILE_STEPS,
        )
        install, check = report.steps[0], report.steps[-1]
        if check.outcome == "passed":
            return {}
        if install.outcome != "passed":
            reasons = {
                path: f"the compiler could not be asked ({install.outcome} install), so the "
                "model's page does not ship"
                for path in written
            }
        else:
            errors: dict[str, list[str]] = {}
            for relative, line in _TSC_ERROR.findall(check.log_tail):
                errors.setdefault(f"apps/web/{relative}", []).append(line.strip())
            named = [path for path in written if path in errors]
            reasons = {
                path: "the compiler refused it: " + "; ".join(errors[path][:3]) for path in named
            } or {
                path: "the app did not compile and the errors name no page the model wrote, "
                "so none of them ships"
                for path in written
            }
        for index, one in enumerate(files.files):
            if one.path in reasons:
                # The digest stays: the model was asked, and this is what came of
                # it, which the next generation keeps while nothing changes.
                files.files[index] = replace(
                    one, content=originals[one.path], generator="rule", reused_from_version=0
                )
        return reasons

    @reports_model_use
    async def generate_backend(
        self, contract: ApiContract, *, fill: bool = False
    ) -> StageResult[FileSet]:
        """Models, repositories, routes and per endpoint contract tests, by
        rule; handler bodies optionally refined under the repository whitelist."""
        files = api_app(contract)

        filled, refused = 0, 0
        if fill:
            filled, refused = await self._fill(
                files,
                prefix="apps/api/src/routes/",
                run=lambda generated: fill_handler(
                    self._handler_filler, rule_body=generated.content
                ),
            )

        routes = sum(1 for f in files.files if f.path.startswith("apps/api/src/routes/"))
        summary = f"Backend generated: {_plural(routes, 'route file')} with contract tests"
        if fill:
            summary += f", {filled} model refined" + (f", {refused} refused" if refused else "")
        return StageResult(
            artefact=files,
            summary=summary,
            notes={"files": len(files.files), "model_filled": filled, "fill_refused": refused},
        )

    async def _fill_pages(
        self,
        files: FileSet,
        originals: dict[str, str],
        said: dict[str, list[str]],
        allowed: set[str],
        earlier: dict[str, EarlierPage],
    ) -> tuple[int, int, int, list[str]]:
        """Rewrite every rule page, or keep what an earlier generation made of an unchanged one.

        Unchanged means the same digest (`page_digest`): the same rule page, the
        same requirements, the same instructions, model, level and settings. An
        earlier rewrite is checked against today's client methods and headers
        before it is kept, as a new one is, and the compile that follows covers
        it too; an earlier refusal is kept as the rule page it shipped, because
        asking again would only flip the page between the two. Every page the
        model was asked about records its digest, whatever the answer was.

        A call that fails (a provider error after its own retries, an answer
        that never parsed) ships that page as the rule generated it, as a
        refusal does, and the stage goes on. The page writer improves a page
        that already works, and one failed call took the whole stage down: no
        files at all, the shared contract package among them, which the
        backend's install then failed on. No digest is recorded for it,
        because nothing was refused, so the next generation asks again. A
        provider rate limiting the account is not asked about the pages left
        either: every call would be refused the same way, and the lanes that
        must stop on the first refusal stop there.

        Returns the pages written by the model, refused, and kept from earlier,
        and why each page the model was not asked about, or could not answer,
        shipped as generated.
        """
        filled, refused, reused = 0, 0, 0
        unasked: list[str] = []
        limited = ""
        for index, generated in enumerate(files.files):
            if generated.path not in originals:
                continue
            requirements = said.get(generated.path, [])
            digest = page_digest(
                generated.content, requirements, model=self.model, thinking=self.thinking
            )
            before = earlier.get(generated.path)
            if before is not None and before.written_from == digest:
                if before.generator == "rule":
                    files.files[index] = replace(
                        generated, written_from=digest, reused_from_version=before.version
                    )
                    refused += 1
                    reused += 1
                    continue
                if (
                    not check_page_fill(before.content, allowed)
                    + dropped_headers(generated.content, before.content)
                    + lost_the_record(generated.content, before.content)
                ):
                    files.files[index] = replace(
                        generated,
                        content=before.content,
                        generator="model",
                        written_from=digest,
                        reused_from_version=before.version,
                    )
                    filled += 1
                    reused += 1
                    continue
            if limited:
                unasked.append(f"{generated.path}: {limited}")
                continue
            try:
                outcome = await fill_page(
                    self._page_filler,
                    rule_body=generated.content,
                    allowed_methods=allowed,
                    requirements=requirements,
                )
            except Exception as error:
                reason = _call_failed(error)
                if isinstance(error, ModelHTTPError) and error.status_code == 429:
                    limited = reason
                log.warning("the page writer failed on %s: %s", generated.path, reason)
                unasked.append(f"{generated.path}: {reason}")
                continue
            if outcome.accepted:
                files.files[index] = replace(
                    generated, content=outcome.content, generator="model", written_from=digest
                )
                filled += 1
            else:
                files.files[index] = replace(generated, written_from=digest)
                refused += 1
        return filled, refused, reused, unasked

    async def _fill(self, files: FileSet, *, prefix: str, run) -> tuple[int, int]:
        """Run the fill over every rule generated file under the prefix. An
        accepted fill replaces the content and the manifest says `model`; a
        refused fill changes nothing, which keeps the manifest a fact."""
        filled, refused = 0, 0
        for index, generated in enumerate(files.files):
            if not generated.path.startswith(prefix) or generated.generator != "rule":
                continue
            outcome = await run(generated)
            if outcome.accepted:
                files.files[index] = GeneratedFile(
                    path=generated.path,
                    content=outcome.content,
                    stage=generated.stage,
                    generator="model",
                    implements=generated.implements,
                    summary=generated.summary,
                )
                filled += 1
            else:
                refused += 1
        return filled, refused

    async def check_agreement(
        self, contract: ApiContract, sources: dict[str, str]
    ) -> StageResult[ContractAgreement]:
        """Static, before anything runs. Pure parsing; no model, no subprocess."""
        from .validate.agreement import check_agreement

        agreement = check_agreement(contract, sources)
        errors = [f for f in agreement.findings if f.severity == "error"]
        warnings = [f for f in agreement.findings if f.severity == "warning"]
        rate = agreement.counts.agreement_rate
        summary = f"Contract agreement checked: {rate:.0%} implemented"
        if errors:
            summary += f", {_plural(len(errors), 'error')} to fix"
        elif warnings:
            summary += f", {_plural(len(warnings), 'warning')} to read"
        return StageResult(
            artefact=agreement,
            summary=summary,
            notes={
                "errors": len(errors),
                "warnings": len(warnings),
                "agreement_rate": rate,
            },
        )

    async def build(
        self,
        sources: dict[str, str],
        *,
        on_step: Callable[[str], None] | None = None,
    ) -> StageResult[BuildReport]:
        """The sandboxed install, typecheck and tests, off the event loop.

        `on_step` is the in process heartbeat hook; over HTTP the caller has no
        callback and leans on the component's longer stale window instead.
        """
        import asyncio

        report = await asyncio.to_thread(run_build, sources, on_step=on_step)
        outcomes = [step.outcome for step in report.steps]
        summary = (
            "Build passed: install, typecheck and tests all green"
            if report.passed
            else "Build failed: " + ", ".join(f"{s.name} {s.outcome}" for s in report.steps)
        )
        return StageResult(
            artefact=report,
            summary=summary,
            notes={"passed": report.passed, "outcomes": outcomes},
        )

    async def push(
        self,
        files: dict[str, str],
        *,
        name: str,
        token: str | None,
        message: str,
        branch: str | None = None,
    ) -> PushResult:
        """The GitHub push; a missing connection is an outcome, not an error."""
        return await push_monorepo(
            files, name=name, token=token, client=self._http, message=message, branch=branch
        )

    async def land(
        self, pointer: RepositoryPointer, *, token: str | None, message: str
    ) -> LandResult:
        """Move the default branch to an approved version; see `repo.github.land`."""
        return await land(pointer, token=token, client=self._http, message=message)
