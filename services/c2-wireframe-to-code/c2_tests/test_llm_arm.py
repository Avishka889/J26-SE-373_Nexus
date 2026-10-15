"""The LLM arm: the repair loop's hints travel, the loop is bounded, the
comparison counts what happened."""

import json

import pytest
from c2.contract.llm_arm import (
    CouldNotInferContract,
    DraftContract,
    build_contract_agent,
    infer_llm_contract,
    prompt_for,
    to_contract,
)
from c2.contract.merge import compare_arms, merge_contracts
from c2.contract.rule_arm import generate_rule_contract
from c2.contract.rules import ContractContext, validate_contract
from c2.rules.scope import derive_scope
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from .corpus_io import CORPUS_DIR, load_design
from .design_fixture import graph, scope, wireframes


def _context() -> ContractContext:
    return ContractContext(graph=graph(), wireframes=wireframes(), scope=scope())


GOOD_DRAFT = {
    "entities": [
        {
            "name": "Order",
            "fields": [{"name": "total", "type": "number"}],
            "requirement_ids": ["R-1"],
        },
        {
            "name": "Product",
            "fields": [{"name": "name", "type": "string"}],
            "requirement_ids": ["R-3"],
        },
    ],
    "endpoints": [
        {
            "method": "POST",
            "path": "/orders",
            "summary": "Place an order",
            "auth_actors": ["Shopper"],
            "request": {"entity": "Order", "fields": [{"name": "total", "type": "number"}]},
            "response": {"entity": "Order"},
            "screen_ids": ["shop/checkout"],
            "action_ids": ["l2"],
            "story_ids": ["US-1"],
            "requirement_ids": ["R-1"],
        },
        {
            "method": "GET",
            "path": "/orders/{id}",
            "summary": "Read one order",
            "response": {"entity": "Order"},
            "screen_ids": ["shop/done"],
            "story_ids": ["US-1"],
        },
        {
            "method": "GET",
            "path": "/products",
            "summary": "List the products",
            "response": {"entity": "Product"},
            "screen_ids": ["shop/catalog"],
            "action_ids": ["b1"],
            "story_ids": ["US-1"],
        },
    ],
}

#: Two rule breaks a hint can actually fix: a ghost screen id and a duplicate.
BROKEN_DRAFT = {
    "entities": GOOD_DRAFT["entities"],
    "endpoints": [
        {**GOOD_DRAFT["endpoints"][0], "screen_ids": ["shop/ghost"]},
        GOOD_DRAFT["endpoints"][1],
        GOOD_DRAFT["endpoints"][1],
    ],
}


class Recorder:
    """Scripted answers, and every prompt kept for the assertions."""

    def __init__(self, drafts: list[dict]) -> None:
        self.drafts = list(drafts)
        self.prompts: list[str] = []

    def as_function(self) -> FunctionModel:
        def answer(messages, info):
            user_texts = [
                part.content
                for message in messages
                for part in getattr(message, "parts", [])
                if getattr(part, "part_kind", "") == "user-prompt"
            ]
            self.prompts.append(user_texts[-1] if user_texts else "")
            draft = self.drafts.pop(0)
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(draft))])

        return FunctionModel(answer)


def _agent(recorder: Recorder) -> Agent[None, DraftContract]:
    return build_contract_agent(recorder.as_function())


class TestTheRepairLoop:
    async def test_the_hints_travel_and_nothing_leaks_into_the_first_prompt(self) -> None:
        recorder = Recorder([BROKEN_DRAFT, GOOD_DRAFT])
        contract, report = await infer_llm_contract(_agent(recorder), version=1, context=_context())
        assert report.attempts == 2
        assert report.repaired
        assert {e.path for e in contract.endpoints} == {"/orders", "/orders/{id}", "/products"}
        first, second = recorder.prompts
        assert "shop/ghost" not in first
        assert "shop/ghost" in second
        assert "declared twice" not in first
        # The hints, not the reasons: imperative sentences the model can act on.
        assert "Replace" in second or "Merge" in second

    async def test_the_loop_is_bounded_and_the_draft_is_logged(self, caplog) -> None:
        recorder = Recorder([BROKEN_DRAFT, BROKEN_DRAFT, BROKEN_DRAFT])
        with caplog.at_level("ERROR"), pytest.raises(CouldNotInferContract) as error:
            await infer_llm_contract(_agent(recorder), version=1, context=_context())
        assert error.value.attempts == 2
        assert len(recorder.prompts) == 2
        assert "shop/ghost" in caplog.text  # the refused draft, whole

    async def test_errors_per_attempt_is_the_ablation_number(self) -> None:
        recorder = Recorder([BROKEN_DRAFT, GOOD_DRAFT])
        _, report = await infer_llm_contract(_agent(recorder), version=1, context=_context())
        assert report.errors_per_attempt[0] != ()
        assert report.errors_per_attempt[1] == ()


class TestNormalisation:
    def test_ids_origin_and_confidence_are_computed_not_reported(self) -> None:
        contract = to_contract(DraftContract(**GOOD_DRAFT), 1, _context())
        placed = next(e for e in contract.endpoints if e.method == "POST")
        assert placed.id == "post-orders"
        assert placed.origin == "llm"
        assert 50 <= placed.confidence <= 98

    def test_an_unreadable_endpoint_is_skipped_not_invented(self) -> None:
        draft = DraftContract(
            entities=GOOD_DRAFT["entities"],
            endpoints=[{"method": "FETCH", "path": "orders"}],
        )
        contract = to_contract(draft, 1, _context())
        assert contract.endpoints == []


class TestTheComparison:
    def test_agreement_and_exclusives_are_counted(self) -> None:
        context = _context()
        rule = generate_rule_contract(1, graph(), wireframes(), scope())
        llm = to_contract(DraftContract(**GOOD_DRAFT), 1, context)
        comparison = compare_arms(
            rule,
            llm,
            rule_report=validate_contract(rule, context),
            llm_report=validate_contract(llm, context),
            llm_attempts=1,
        )
        assert comparison.rule.endpoints == len(rule.endpoints)
        assert comparison.llm.endpoints == 3
        assert "POST /orders" in comparison.agreed
        assert "GET /orders/{id}" in comparison.agreed
        assert 0.0 < comparison.agreement_rate <= 1.0
        # The union arithmetic holds.
        union = len(comparison.agreed) + len(comparison.rule_only) + len(comparison.llm_only)
        assert union == len({*comparison.agreed, *comparison.rule_only, *comparison.llm_only})

    def test_a_failed_llm_arm_compares_honestly(self) -> None:
        context = _context()
        rule = generate_rule_contract(1, graph(), wireframes(), scope())
        comparison = compare_arms(
            rule,
            None,
            rule_report=validate_contract(rule, context),
            llm_report=None,
            llm_attempts=2,
        )
        assert comparison.llm.endpoints == 0
        assert comparison.agreed == []
        assert comparison.agreement_rate < 1.0


class TestTheMerge:
    def test_shared_keys_keep_the_rule_version_with_unioned_traces(self) -> None:
        context = _context()
        rule = generate_rule_contract(1, graph(), wireframes(), scope())
        llm = to_contract(DraftContract(**GOOD_DRAFT), 1, context)
        merged = merge_contracts(rule, llm)
        placed = next(e for e in merged.endpoints if e.id == "post-orders")
        assert placed.origin == "merged"
        assert "shop/checkout" in placed.traces.screen_ids
        # And the union has no duplicate canonical keys.
        keys = [f"{e.method} {e.path}" for e in merged.endpoints]
        assert len(keys) == len(set(keys))


class TestTheScopeTheModelIsShown:
    """C2-4, for the model arm: it is shown the actions this sprint's stories
    trace, the same ones the rule arm takes, so the two arms are compared on
    one scope and neither is invited to build the backlog."""

    def test_the_prompt_lists_only_the_actions_in_scope(self) -> None:
        design = load_design(CORPUS_DIR / "cold_chain_design.json")
        prompt = prompt_for(
            design.graph, design.wireframes, derive_scope(design.sprint, design.wireframes)
        )
        assert "reconstructs history from AuditRecord" in prompt
        assert "reassigns stop on Route" not in prompt
        assert "exports AuditRecord" not in prompt
