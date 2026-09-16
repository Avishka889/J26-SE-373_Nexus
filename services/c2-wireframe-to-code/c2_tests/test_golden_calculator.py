"""The calculator golden case: a small design in, the exact contract out.

The truth file was hand checked against the design (three endpoints: record,
list, detail; the divide by zero constraint as validation on the write) and
then frozen. The guards are C1's pair: nothing from any other corpus item may
appear in the generated code (leakage), and the calculator's own vocabulary
must (grounding), because a leakage guard alone passes empty output.
"""

import shutil

import pytest
from c2.codegen.monorepo import generate_monorepo
from c2.contract.rule_arm import generate_rule_contract
from c2.contract.rules import ContractContext, validate_contract
from c2.eval import contract_scores
from c2.rules.scope import derive_scope
from c2.validate.agreement import check_agreement

from .corpus_io import CALCULATOR_STEM, CORPUS_DIR, leaked, load_design, load_truth


def _design():
    return load_design(CORPUS_DIR / "calculator_design.json")


def _generate():
    design = _design()
    scope = derive_scope(design.sprint, design.wireframes)
    contract = generate_rule_contract(1, design.graph, design.wireframes, scope)
    return design, scope, contract


class TestTheContract:
    def test_the_rule_arm_matches_the_truth_exactly(self) -> None:
        _, _, contract = _generate()
        scores = contract_scores(contract, load_truth("calculator"))
        assert scores["endpoints"].f1 == 1.0, scores["endpoints"]
        assert scores["paths"].f1 == 1.0
        assert scores["schema_fields"].f1 == 1.0

    def test_the_constraint_lands_on_the_write_alone(self) -> None:
        _, _, contract = _generate()
        by_id = {e.id: e for e in contract.endpoints}
        assert any("divides by zero" in rule for rule in by_id["post-calculations"].validation)
        assert by_id["get-calculations"].validation == []

    def test_the_contract_passes_its_own_catalogue(self) -> None:
        design, scope, contract = _generate()
        report = validate_contract(
            contract,
            ContractContext(graph=design.graph, wireframes=design.wireframes, scope=scope),
        )
        assert report.ok, [f.reason for f in report.errors]


class TestTheGuards:
    def test_no_other_corpus_vocabulary_leaks_into_the_code(self) -> None:
        design, scope, contract = _generate()
        files = generate_monorepo(
            design.name, contract, design.wireframes, scope, design_version=1, arm="rule"
        )
        for generated in files.files:
            words = leaked(generated.content)
            assert not words, f"{generated.path} leaked {words}"

    def test_the_calculators_own_vocabulary_is_present(self) -> None:
        """The grounded mirror: an empty generation leaks nothing and proves
        nothing. The calculator's stem must appear in the code itself."""
        design, scope, contract = _generate()
        files = generate_monorepo(
            design.name, contract, design.wireframes, scope, design_version=1, arm="rule"
        )
        haystack = "\n".join(generated.content.lower() for generated in files.files)
        assert CALCULATOR_STEM in haystack
        assert haystack.count(CALCULATOR_STEM) > 10, "barely mentioned is barely grounded"

    def test_the_generated_set_agrees_with_the_contract(self) -> None:
        design, scope, contract = _generate()
        files = generate_monorepo(
            design.name, contract, design.wireframes, scope, design_version=1, arm="rule"
        )
        agreement = check_agreement(
            contract, {generated.path: generated.content for generated in files.files}
        )
        assert [f.reason for f in agreement.errors] == []
        assert agreement.counts.agreement_rate == 1.0


@pytest.mark.sandbox
@pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")
class TestTheRealBuild:
    def test_the_calculator_monorepo_builds(self, tmp_path) -> None:
        from c2.sandbox import run_build

        design, scope, contract = _generate()
        files = generate_monorepo(
            design.name, contract, design.wireframes, scope, design_version=1, arm="rule"
        )
        report = run_build(
            {generated.path: generated.content for generated in files.files},
            workdir=str(tmp_path / "calc"),
        )
        transcript = "\n\n".join(
            f"== {step.name} ({step.outcome}) ==\n{step.log_tail}" for step in report.steps
        )
        assert report.passed, transcript
