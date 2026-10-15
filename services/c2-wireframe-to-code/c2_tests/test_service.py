"""Component 2 as the orchestrator sees it: one method per stage.

The pieces are all tested on their own elsewhere. What is only testable here
is the surface: every stage returns something the contract accepts, a
sentence a reader can read, and notes the evaluation can count, and every
model armed path degrades honestly when the model misbehaves.

Scripted models throughout, because the point is the wiring.
"""

import json
import shutil

import pytest
from c2.codegen.fill import page_digest
from c2.service import C2
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import BuildReport, BuildStepReport, EarlierPage, ParsedRequirement

from .design_fixture import graph, scope, sprint, wireframes
from .test_llm_arm import BROKEN_DRAFT, GOOD_DRAFT


def scripted(*payloads: dict) -> FunctionModel:
    """A model that answers the given payloads in order, repeating the last."""
    remaining = list(payloads)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        payload = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(payload))])

    return FunctionModel(respond)


def compiler(install: str = "passed", check: str = "passed", tail: str = ""):
    """A scripted compile, for the check that puts back what does not compile."""

    def build(sources: dict[str, str], *, steps=()) -> BuildReport:
        return BuildReport(
            toolchain="scripted",
            isolation="scripted",
            steps=[
                BuildStepReport(name="install", command="npm install", outcome=install),
                BuildStepReport(
                    name="typecheck",
                    command="npm run typecheck",
                    outcome=check if install == "passed" else "not-run",
                    log_tail=tail,
                ),
            ],
        )

    return build


def filling(body: str) -> FunctionModel:
    """A fill model that does what a fill model is told.

    The instructions say to keep the `implements` header comments exactly as
    they are, and the post check refuses a fill that drops one, because the
    agreement checker reads those lines to decide which endpoints are
    implemented. A double that answered with a fixed string would be modelling
    a model that ignores its instructions, which is worth a test of its own and
    is not this one: it echoes the headers out of the prompt it was given, and
    keeps a page reading its record from its address where the page did.
    """

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = "".join(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(getattr(part, "content", None), str)
        )
        headers = [line for line in prompt.splitlines() if line.strip().startswith("// implements")]
        # And it keeps reading the record from the address where the page did.
        record = ["const { id } = useParams();"] if "useParams(" in prompt else []
        content = "\n".join([*headers, *record, body])
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, json.dumps({"content": content}))]
        )

    return FunctionModel(respond)


def c2_answering(*payloads: dict) -> C2:
    """A component whose agents all speak the same script; each test drives
    one stage, so only that stage's agent is ever called."""
    return C2(scripted(*payloads))


class TestScope:
    async def test_rules_only_with_a_readable_summary(self) -> None:
        component = c2_answering({})
        result = await component.derive_scope(sprint(), wireframes())
        assert result.artefact.in_scope_ids == ["US-1"]
        assert "1 story" in result.summary and "3 screens" in result.summary
        assert result.notes == {"stories_total": 2, "stories_in_scope": 1}


class TestStack:
    async def test_the_explanation_lands_on_the_recommended_candidate(self) -> None:
        component = c2_answering({"rationale": "One team, one deploy, one language."})
        result = await component.propose_stack(graph())
        recommended = next(
            c for c in result.artefact.candidates if c.id == result.artefact.recommended_id
        )
        assert recommended.explanation == "One team, one deploy, one language."
        assert result.notes["explained"] is True

    async def test_an_inventing_explainer_is_refused_and_the_arithmetic_ships(self) -> None:
        component = c2_answering({"rationale": "supports 10,000 concurrent users"})
        result = await component.propose_stack(graph())
        assert all(c.explanation == "" for c in result.artefact.candidates)
        assert result.notes["explained"] is False
        assert "explainer_error" in result.notes
        # The scores are still there: the model never owned them.
        assert all(c.score >= 0 for c in result.artefact.candidates)


class TestContract:
    async def test_both_arms_and_the_comparison_when_the_model_behaves(self) -> None:
        component = c2_answering(GOOD_DRAFT)
        result = await component.infer_contract(1, graph(), wireframes(), scope(), arm="llm")
        artefact = result.artefact
        assert artefact.llm_arm is not None and artefact.llm_failure is None
        assert artefact.chosen == "llm"
        assert artefact.contract == artefact.llm_arm
        assert artefact.comparison is not None
        assert result.notes["llm_attempts"] == 1

    async def test_a_failed_llm_arm_is_recorded_and_the_rule_arm_stands(self) -> None:
        component = c2_answering(BROKEN_DRAFT)
        result = await component.infer_contract(1, graph(), wireframes(), scope(), arm="llm")
        artefact = result.artefact
        assert artefact.llm_arm is None and artefact.llm_failure
        assert artefact.chosen == "rule"
        assert artefact.contract == artefact.rule_arm
        assert result.notes["requested_arm"] == "llm"
        assert "the rule arm stands" in result.summary

    async def test_the_rule_arm_s_own_findings_are_kept_when_the_model_fails(
        self, monkeypatch
    ) -> None:
        # Kept only inside the comparison, which a failed model arm leaves out,
        # so the page showed the rule arm with no violations (review item C2-3).
        from c2 import service
        from c2.rules.findings import Finding, report

        planted = Finding(
            rule_id="screen-action-has-an-endpoint",
            severity="error",
            reason="screen shop/checkout is a form with 2 fields and no write endpoint traces to it",
            hint="Add the POST endpoint that screen shop/checkout's form submits to.",
            subject="shop/checkout",
        )
        monkeypatch.setattr(
            service, "validate_contract", lambda contract, context: report([planted])
        )
        component = c2_answering(BROKEN_DRAFT)

        result = await component.infer_contract(1, graph(), wireframes(), scope(), arm="llm")

        assert result.artefact.comparison is None
        assert [
            (one.rule_id, one.severity, one.subject, one.reason)
            for one in result.artefact.rule_findings
        ] == [("screen-action-has-an-endpoint", "error", "shop/checkout", planted.reason)]

    async def test_merged_takes_the_union_with_rule_winning_shared_keys(self) -> None:
        component = c2_answering(GOOD_DRAFT)
        result = await component.infer_contract(1, graph(), wireframes(), scope(), arm="merged")
        artefact = result.artefact
        assert artefact.chosen == "merged"
        rule_keys = {f"{e.method} {e.path}" for e in artefact.rule_arm.endpoints}
        merged_keys = {f"{e.method} {e.path}" for e in artefact.contract.endpoints}
        assert rule_keys <= merged_keys


class TestFieldRules:
    """What the design's constraints and the sprint's criteria say a field may hold
    was words in a handler's comment, and the app took any value."""

    async def test_every_arm_carries_the_bounds_the_criteria_state(self) -> None:
        component = c2_answering(GOOD_DRAFT)
        criterion = (
            "Given an order whose total is at most 1000. When it is placed. Then it is kept."
        )

        result = await component.infer_contract(
            1, graph(), wireframes(), scope(), arm="merged", criteria=[criterion]
        )

        artefact = result.artefact
        assert artefact.llm_arm is not None
        for contract in (artefact.rule_arm, artefact.llm_arm, artefact.contract):
            [total] = [
                field
                for entity in contract.entities
                if entity.name == "Order"
                for field in entity.fields
                if field.name == "total"
            ]
            assert (total.maximum, total.rules) == (1000, [criterion])
        assert result.notes["bounded_fields"] == 1
        assert "1 field rule read from the design and the criteria" in result.summary

    async def test_a_constraint_with_no_bound_in_it_stays_words(self) -> None:
        """The fixture's one constraint, "An order total never exceeds available stock",
        names a field and no number: nothing to read, and nothing is guessed."""
        component = c2_answering(BROKEN_DRAFT)

        result = await component.infer_contract(1, graph(), wireframes(), scope())

        fields = [field for entity in result.artefact.contract.entities for field in entity.fields]
        assert all(field.maximum is None and not field.rules for field in fields)
        assert result.notes["bounded_fields"] == 0


class TestCodegen:
    async def test_frontend_without_fill_is_rule_and_static_only(self) -> None:
        component = c2_answering({})
        result = await component.generate_frontend(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule"
        )
        manifest = result.artefact.manifest("rule")
        assert {row.generator for row in manifest} <= {"rule", "static"}
        assert any(row.path.startswith("apps/web/src/pages/") for row in manifest)
        assert any(row.path == "packages/contract/src/client.ts" for row in manifest)
        assert result.notes["model_filled"] == 0

    async def test_the_app_carries_the_project_s_own_name(self) -> None:
        """The pipeline builds the frontend here rather than through the monorepo
        helper, and passed no name, so every live app was titled "App"."""
        component = c2_answering({})
        result = await component.generate_frontend(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule"
        )
        assert 'name={"ShopFlow"}' in result.artefact.content_of("apps/web/src/routes.tsx")
        assert "<title>ShopFlow</title>" in result.artefact.content_of("apps/web/index.html")

    async def test_an_accepted_fill_flips_the_manifest_to_model(self) -> None:
        component = C2(
            filling(
                "export default function Page() {\n"
                "  const rows = client.getProducts();\n"
                "  return null;\n"
                "}\n"
            ),
            build=compiler(),
        )
        result = await component.generate_frontend(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule", fill=True
        )
        manifest = result.artefact.manifest("rule")
        pages = [row for row in manifest if row.path.startswith("apps/web/src/pages/")]
        assert pages and all(row.generator == "model" for row in pages)
        assert result.notes["model_filled"] == len(pages)
        # And the headers came through into what shipped, which is what the
        # agreement checker will read back off these files.
        for row in pages:
            body = result.artefact.content_of(row.path)
            for endpoint_id in row.implements:
                if endpoint_id.startswith("shop/"):  # a screen id, not an endpoint
                    continue
                assert f"// implements {endpoint_id}" in body, (
                    f"{row.path} shipped as a model fill without its {endpoint_id} header"
                )

    async def test_a_refused_fill_ships_the_rule_body_and_says_so(self) -> None:
        component = c2_answering({"content": 'void fetch("/api/around-the-client");'})
        result = await component.generate_frontend(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule", fill=True
        )
        manifest = result.artefact.manifest("rule")
        pages = [row for row in manifest if row.path.startswith("apps/web/src/pages/")]
        assert pages and all(row.generator == "rule" for row in pages)
        assert result.notes["fill_refused"] == len(pages)
        assert result.notes["model_filled"] == 0

    async def test_backend_files_carry_contract_tests(self) -> None:
        component = c2_answering({})
        result = await component.generate_backend(_contract())
        paths = [f.path for f in result.artefact.files]
        assert any("__tests__" in path for path in paths)
        assert "contract test" in result.summary


class TestAgreementAndBuild:
    async def test_the_generated_set_agrees_with_its_contract(self) -> None:
        component = c2_answering({})
        contract = _contract()
        front = await component.generate_frontend(
            "ShopFlow", contract, wireframes(), scope(), design_version=1, arm="rule"
        )
        back = await component.generate_backend(contract)
        sources = {f.path: f.content for f in front.artefact.files + back.artefact.files}
        result = await component.check_agreement(contract, sources)
        assert result.notes["errors"] == 0
        assert result.notes["agreement_rate"] == 1.0
        assert "100% implemented" in result.summary

    async def test_build_runs_off_the_event_loop_and_reports(self, monkeypatch) -> None:
        import c2.service as service_module

        def fake_build(sources, *, on_step=None):
            from sdlc_contracts import BuildReport, BuildStepReport

            if on_step is not None:
                on_step("install")
            return BuildReport(
                toolchain="node test / npm test",
                isolation="a stub",
                steps=[
                    BuildStepReport(
                        name="install", command="true", outcome="passed", duration_seconds=0.1
                    ),
                    BuildStepReport(name="typecheck", command="false", outcome="failed"),
                    BuildStepReport(name="unit tests", command="true", outcome="not-run"),
                ],
            )

        monkeypatch.setattr(service_module, "run_build", fake_build)
        component = c2_answering({})
        beats: list[str] = []
        result = await component.build({"README.md": "x"}, on_step=beats.append)
        assert beats == ["install"]
        assert result.notes["passed"] is False
        assert "typecheck failed" in result.summary

    async def test_push_without_a_connection_is_an_outcome(self) -> None:
        component = c2_answering({})
        outcome = await component.push({"README.md": "x"}, name="shopflow", token=None, message="m")
        assert outcome.pointer is None
        assert outcome.reason and "no GitHub connection" in outcome.reason


def _contract():
    from c2.contract.rule_arm import generate_rule_contract

    return generate_rule_contract(1, graph(), wireframes(), scope())


class TestThePageWriter:
    """A page rewritten for what it is for, and compiled before it ships.

    The writer was told only to improve a page it saw as fields and a button, so a
    calculator could only ever be restyled; and nothing compiled what it wrote, so
    a page with a type error failed the build two stages later, reading as the
    app's fault.
    """

    BODY = "export default function Page() {\n  return null;\n}\n"

    async def _frontend(self, component: C2, wires=None, **options):
        return await component.generate_frontend(
            "ShopFlow",
            _contract(),
            wires or wireframes(),
            scope(),
            design_version=1,
            arm="rule",
            fill=True,
            **options,
        )

    async def test_it_is_told_what_the_screen_is_for_and_what_to_build_from(self) -> None:
        prompts: list[str] = []
        model = filling(self.BODY)
        answer = model.function

        def recording(messages, info):
            prompts.append(
                "".join(
                    part.content
                    for message in messages
                    for part in message.parts
                    if isinstance(getattr(part, "content", None), str)
                )
            )
            return answer(messages, info)

        component = C2(FunctionModel(recording), build=compiler())
        wires = wireframes()
        wires.flows[0].traces = ["R-1", "R-2"]
        said = [
            ParsedRequirement(
                id=rid,
                text=f"what {rid} asks for",
                type="functional",
                priority="must",
                confidence=80,
            )
            for rid in ("R-1", "R-2", "R-9")
        ]

        await self._frontend(component, wires, requirements=said)

        assert prompts
        assert all("- what R-1 asks for" in prompt for prompt in prompts)
        assert not any("R-9" in prompt for prompt in prompts), "not this flow's requirement"
        assert all('The components in "../ui"' in prompt for prompt in prompts)

    async def test_a_page_the_compiler_names_goes_back_with_its_reason(self) -> None:
        tail = (
            "src/pages/ShopCatalogPage.tsx(3,7): error TS2304: Cannot find name 'client'.\n"
            "Found 1 error."
        )
        component = C2(filling(self.BODY), build=compiler(check="failed", tail=tail))

        result = await self._frontend(component)

        reverted = result.notes["fill_reverted"]
        assert list(reverted) == ["apps/web/src/pages/ShopCatalogPage.tsx"]
        assert "Cannot find name 'client'" in reverted["apps/web/src/pages/ShopCatalogPage.tsx"]
        by_path = {row.path: row.generator for row in result.artefact.manifest("rule")}
        assert by_path["apps/web/src/pages/ShopCatalogPage.tsx"] == "rule"
        assert by_path["apps/web/src/pages/ShopCheckoutPage.tsx"] == "model"
        assert "put back for not compiling" in result.summary

    async def test_nothing_the_compiler_could_not_check_ships(self) -> None:
        component = C2(filling(self.BODY), build=compiler(install="failed"))

        result = await self._frontend(component)

        pages = [row for row in result.artefact.manifest("rule") if "/pages/" in row.path]
        assert all(row.generator == "rule" for row in pages)
        assert result.notes["model_filled"] == 0
        assert all(
            "could not be asked" in reason for reason in result.notes["fill_reverted"].values()
        )

    async def test_errors_that_name_no_written_page_put_them_all_back(self) -> None:
        tail = "src/routes.tsx(1,1): error TS2307: Cannot find module './pages/Gone'."
        component = C2(filling(self.BODY), build=compiler(check="failed", tail=tail))

        result = await self._frontend(component)

        assert result.notes["model_filled"] == 0
        assert len(result.notes["fill_reverted"]) == 3


@pytest.mark.sandbox
@pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")
class TestAnUnchangedPage:
    """A page whose inputs have not changed keeps what an earlier generation made of it.

    Each regeneration asked the model to rewrite every page afresh, so pages for
    stories nobody had touched came out different every time (the model does not
    answer the same twice), a reviewer had them to read again, and each was paid
    for again.
    """

    BODY = TestThePageWriter.BODY

    def _counting(self, body: str) -> tuple[FunctionModel, list[int]]:
        calls: list[int] = []
        answer = filling(body).function

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            return answer(messages, info)

        return FunctionModel(respond), calls

    async def _frontend(self, model: FunctionModel, earlier=()):
        return await C2(model, build=compiler()).generate_frontend(
            "ShopFlow",
            _contract(),
            wireframes(),
            scope(),
            design_version=1,
            arm="rule",
            fill=True,
            earlier=list(earlier),
        )

    @staticmethod
    def _pages(result) -> dict:
        return {
            row.path: row
            for row in result.artefact.manifest("rule")
            if row.path.startswith("apps/web/src/pages/")
        }

    def _earlier(self, result, *, version: int = 1, **changes) -> list[EarlierPage]:
        return [
            EarlierPage(
                path=row.path,
                written_from=changes.get("written_from", row.written_from),
                generator=changes.get("generator", row.generator),
                content=changes.get("content", result.artefact.content_of(row.path)),
                version=version,
            )
            for row in self._pages(result).values()
        ]

    async def test_it_keeps_the_earlier_rewrite_without_asking_the_model(self) -> None:
        first_model, _ = self._counting(self.BODY)
        first = await self._frontend(first_model)
        # A second answer that would differ: what ships has to be the first.
        second_model, calls = self._counting("export default function Other() { return null; }")

        second = await self._frontend(second_model, self._earlier(first, version=4))

        assert calls == [], "an unchanged page was rewritten again"
        pages = self._pages(second)
        assert pages and all(row.generator == "model" for row in pages.values())
        assert all(row.reused_from_version == 4 for row in pages.values())
        for path in pages:
            assert second.artefact.content_of(path) == first.artefact.content_of(path)
        assert second.notes["fill_reused"] == len(pages)

    async def test_a_page_whose_inputs_changed_is_written_again(self) -> None:
        first_model, _ = self._counting(self.BODY)
        first = await self._frontend(first_model)
        model, calls = self._counting(self.BODY)

        second = await self._frontend(model, self._earlier(first, written_from="0" * 64))

        assert len(calls) == len(self._pages(second))
        assert all(row.reused_from_version == 0 for row in self._pages(second).values())

    async def test_an_earlier_refusal_is_kept_without_asking_again(self) -> None:
        """Asking again would only flip the page between the rule page and a rewrite."""
        first_model, _ = self._counting(self.BODY)
        first = await self._frontend(first_model)
        model, calls = self._counting(self.BODY)

        second = await self._frontend(
            model, self._earlier(first, generator="rule", content="ignored")
        )

        assert calls == []
        pages = self._pages(second)
        assert all(row.generator == "rule" for row in pages.values())
        assert all(row.reused_from_version == 1 for row in pages.values())

    async def test_an_earlier_rewrite_that_fails_todays_checks_is_written_again(self) -> None:
        first_model, _ = self._counting(self.BODY)
        first = await self._frontend(first_model)
        stale = [
            page.model_copy(update={"content": page.content + "\nclient.removedLongAgo();\n"})
            for page in self._earlier(first)
        ]
        model, calls = self._counting(self.BODY)

        second = await self._frontend(model, stale)

        assert len(calls) == len(self._pages(second))
        assert all(row.reused_from_version == 0 for row in self._pages(second).values())

    async def test_a_page_the_compiler_put_back_keeps_its_digest(self) -> None:
        """So the next generation keeps the refusal rather than asking again."""
        model, _ = self._counting(self.BODY)
        result = await C2(model, build=compiler(check="failed")).generate_frontend(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule", fill=True
        )

        pages = self._pages(result)
        assert pages and all(row.generator == "rule" for row in pages.values())
        assert all(row.written_from for row in pages.values())

    def test_the_digest_follows_what_the_page_depends_on(self) -> None:
        base = {"model": "deepseek:deepseek-flash", "thinking": "off"}
        digest = page_digest("body", ["what it is for"], **base)

        assert digest == page_digest("body", ["what it is for"], **base)
        assert digest != page_digest("another body", ["what it is for"], **base)
        assert digest != page_digest("body", ["what it is for, reworded"], **base)
        assert digest != page_digest("body", ["what it is for"], **{**base, "thinking": "high"})
        assert digest != page_digest(
            "body", ["what it is for"], **{**base, "model": "openai:gpt-4o-mini"}
        )


class TestAFailedPageWriterCall:
    """One failed call took the whole Frontend Code stage down with it.

    A provider error after its retries, or an answer that never parsed, escaped
    the stage, which then stored no files at all, the shared contract package
    among them, so the backend's install failed later. The writer only improves
    a page that already works, so a failed call ships that page as generated.
    """

    BODY = TestThePageWriter.BODY

    @staticmethod
    def _failing(body: str, *, on_call: int, status: int = 500) -> tuple[FunctionModel, list[int]]:
        from pydantic_ai.exceptions import ModelHTTPError

        calls: list[int] = []
        answer = filling(body).function

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            if len(calls) == on_call:
                raise ModelHTTPError(status_code=status, model_name="scripted", body={"org": "x"})
            return answer(messages, info)

        return FunctionModel(respond), calls

    async def _frontend(self, model: FunctionModel):
        return await C2(model, build=compiler()).generate_frontend(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule", fill=True
        )

    async def test_that_page_ships_as_generated_and_the_stage_goes_on(self) -> None:
        model, _ = self._failing(self.BODY, on_call=2)

        result = await self._frontend(model)

        paths = [one.path for one in result.artefact.files]
        assert "packages/contract/src/client.ts" in paths, "the shared package is there"
        [failed] = result.notes["fill_failed"]
        page = failed.split(":", 1)[0]
        row = next(one for one in result.artefact.files if one.path == page)
        assert row.generator == "rule"
        assert row.written_from == "", "nothing was refused, so the next generation asks again"
        assert "the provider answered 500" in failed
        assert "org" not in failed, "the provider's body stays out of the notes"
        assert "1 kept as generated because the model call failed" in result.summary
        assert result.notes["model_filled"] >= 1, "the other pages were still written"

    async def test_a_stage_that_asks_no_model_reports_no_failed_call(self) -> None:
        """The orchestrator's client suite found the notes naming a list only
        the page writer's branch had made."""
        result = await c2_answering({}).generate_frontend(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule"
        )

        assert result.notes["fill_failed"] == []

    async def test_a_rate_limit_stops_the_asking(self) -> None:
        model, calls = self._failing(self.BODY, on_call=1, status=429)

        result = await self._frontend(model)

        assert len(calls) == 1, "every call after the first 429 would be refused the same way"
        assert result.notes["model_filled"] == 0
        assert len(result.notes["fill_failed"]) == len(
            [one for one in result.artefact.files if one.path.startswith("apps/web/src/pages/")]
        )
        assert all("rate limiting" in one for one in result.notes["fill_failed"])


class TestThePageWriterOnTheRealCompiler:
    async def test_pages_that_do_not_compile_go_back_with_the_compiler_s_words(self) -> None:
        component = C2(
            filling(
                "export default function Page() {\n"
                '  const count: number = "not a number";\n'
                "  return count;\n"
                "}\n"
            )
        )

        result = await component.generate_frontend(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule", fill=True
        )

        assert result.notes["model_filled"] == 0
        reasons = result.notes["fill_reverted"]
        assert reasons and all("the compiler refused it" in one for one in reasons.values())
        assert all("TS2322" in one for one in reasons.values())
