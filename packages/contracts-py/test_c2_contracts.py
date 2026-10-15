"""The C2 contracts refuse dishonest shapes, and the diff is exact.

These are contract tests, not generator tests: each one plants a shape that a
buggy or lazy producer might emit and asserts the model refuses it with a
reason, because the validator is the last line before a lie is stored.
"""

import pytest
from pydantic import ValidationError
from sdlc_contracts import (
    ApiContract,
    ApiContractArtefact,
    ApiEndpoint,
    BuildStepReport,
    CodeRepository,
    CodeSnapshot,
    NextSprint,
    NextSprintStory,
    RepositoryPointer,
    SchemaField,
    ScopeStory,
    StackCandidate,
    StackLayer,
    TechStackArtefact,
    diff_contracts,
)


def _endpoint(id: str, method: str = "GET", path: str = "/orders", **extra) -> ApiEndpoint:
    return ApiEndpoint(id=id, method=method, path=path, **extra)


def _contract(version: int, *endpoints: ApiEndpoint) -> ApiContract:
    return ApiContract(version=version, endpoints=list(endpoints))


class TestTheDiff:
    def test_added_removed_and_changed_are_told_apart(self) -> None:
        before = _contract(
            1,
            _endpoint("get-orders"),
            _endpoint("delete-orders-id", method="DELETE", path="/orders/{id}"),
        )
        after = _contract(
            2,
            _endpoint("get-orders", summary="List the orders"),
            _endpoint("post-orders", method="POST", path="/orders"),
        )
        diff = diff_contracts(before, after)
        assert diff.added == ["post-orders"]
        assert diff.removed == ["delete-orders-id"]
        assert [(c.endpoint_id, c.field) for c in diff.changed] == [("get-orders", "summary")]
        assert diff.changed[0].after == "List the orders"

    def test_identical_contracts_diff_to_nothing(self) -> None:
        contract = _contract(1, _endpoint("get-orders"))
        again = _contract(2, _endpoint("get-orders"))
        diff = diff_contracts(contract, again)
        assert diff.added == [] and diff.removed == [] and diff.changed == []

    def test_an_auth_change_is_a_change(self) -> None:
        before = _contract(1, _endpoint("get-orders"))
        after = _contract(2, _endpoint("get-orders", auth_actors=["Warehouse Operator"]))
        diff = diff_contracts(before, after)
        assert [(c.endpoint_id, c.field) for c in diff.changed] == [("get-orders", "auth")]


class TestTheContractArtefact:
    def test_a_missing_llm_arm_needs_its_failure_written_down(self) -> None:
        contract = _contract(1, _endpoint("get-orders"))
        with pytest.raises(ValidationError, match="without a recorded failure"):
            ApiContractArtefact(version=1, rule_arm=contract, contract=contract)

    def test_the_failed_arm_cannot_be_the_chosen_one(self) -> None:
        contract = _contract(1, _endpoint("get-orders"))
        with pytest.raises(ValidationError, match="cannot be chosen"):
            ApiContractArtefact(
                version=1,
                rule_arm=contract,
                llm_failure="the model never answered",
                chosen="llm",
                contract=contract,
            )

    def test_an_honest_failure_is_storable(self) -> None:
        contract = _contract(1, _endpoint("get-orders"))
        artefact = ApiContractArtefact(
            version=1,
            rule_arm=contract,
            llm_failure="rate limited after 3 attempts",
            chosen="rule",
            contract=contract,
        )
        assert artefact.llm_arm is None


class TestTheRepositoryArtefact:
    def test_a_step_that_did_not_run_carries_no_duration(self) -> None:
        with pytest.raises(ValidationError, match="did not run"):
            BuildStepReport(
                name="unit tests", command="npm test", outcome="not-run", duration_seconds=3.0
            )

    def test_a_pointer_and_a_not_pushed_reason_cannot_coexist(self) -> None:
        pointer = RepositoryPointer(
            owner="vinozhan",
            name="shopflow",
            default_branch="main",
            commit_sha="abc123",
            url="https://github.com/vinozhan/shopflow",
        )
        with pytest.raises(ValidationError, match="cannot also carry"):
            CodeRepository(version=1, repository=pointer, not_pushed_reason="no connection")

    def test_not_pushed_with_a_reason_is_the_honest_shape(self) -> None:
        repo = CodeRepository(version=1, not_pushed_reason="not pushed: no connection")
        assert repo.repository is None


class TestTheStackArtefact:
    @staticmethod
    def _candidate(**overrides) -> StackCandidate:
        base = dict(
            id="mern",
            name="MERN",
            layers=[StackLayer(name="frontend", choice="React 19")],
            score=70,
            available=True,
        )
        base.update(overrides)
        return StackCandidate(**base)

    def test_unavailability_needs_a_reason(self) -> None:
        with pytest.raises(ValidationError, match="without saying why"):
            self._candidate(available=False)

    def test_availability_refuses_a_stale_reason(self) -> None:
        with pytest.raises(ValidationError, match="reason not to be"):
            self._candidate(unavailable_reason="generators not built")

    def test_the_selection_must_be_a_candidate(self) -> None:
        with pytest.raises(ValidationError, match="not a candidate"):
            TechStackArtefact(
                candidates=[self._candidate()],
                recommended_id="mern",
                selected_id="rails",
            )


class TestTheCodeSnapshot:
    def test_every_stage_must_be_present(self) -> None:
        from sdlc_contracts import GateState

        with pytest.raises(ValidationError, match="missing stages"):
            CodeSnapshot(
                project_id="p1",
                code_version=0,
                design_version=1,
                generated_from_design_version=0,
                stages={},
                gate=GateState(),
            )


class TestTheSprintAStoryIsIn:
    def test_a_scope_stored_before_sprints_were_counted_reads_as_the_first(self) -> None:
        stored = {"id": "US-1", "title": "Keep a record", "points": 3, "inScope": True}

        assert ScopeStory.model_validate(stored).sprint == 1

    def test_a_story_out_of_the_build_is_in_no_sprint(self) -> None:
        with pytest.raises(ValidationError, match="out of the build but planned in sprint 2"):
            ScopeStory(id="US-2", title="Share a record", points=8, in_scope=False, sprint=2)

    def test_the_next_sprints_points_are_its_stories(self) -> None:
        story = NextSprintStory(id="US-2", title="Share a record", points=8, priority="should")

        with pytest.raises(ValidationError, match="points is 5 but the stories total 8"):
            NextSprint(number=2, stories=[story], points=5, velocity=20, velocity_basis="assumed")


class TestAFieldsBounds:
    """The bounds a criterion states were words in a comment, and the generated app
    took any value: the Movie Tracker took release years 1999 and 2027."""

    def test_a_number_carries_its_range_and_the_words_it_came_from(self) -> None:
        field = SchemaField(
            name="releaseYear",
            type="number",
            minimum=2000,
            maximum=2026,
            rules=["release years run from 2000 to 2026"],
        )
        dumped = field.model_dump(by_alias=True, exclude_none=True)
        assert (dumped["minimum"], dumped["maximum"]) == (2000, 2026)
        assert dumped["rules"] == ["release years run from 2000 to 2026"]

    def test_a_range_that_runs_backwards_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="minimum 2026 is above its maximum 2000"):
            SchemaField(name="releaseYear", type="number", minimum=2026, maximum=2000)
        with pytest.raises(ValidationError, match="minimum length 9 is above its maximum 3"):
            SchemaField(name="title", type="string", min_length=9, max_length=3)

    def test_a_bound_belongs_to_the_type_it_can_bound(self) -> None:
        with pytest.raises(ValidationError, match="releaseYear is a number"):
            SchemaField(name="releaseYear", type="number", max_length=4)
        with pytest.raises(ValidationError, match="title is a string"):
            SchemaField(name="title", type="string", maximum=4)
