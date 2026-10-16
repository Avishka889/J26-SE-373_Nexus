"""What the rules can write before any model is asked, and what they refuse to.

Two claims are worth the file. The tests the rules derive from the contract
actually pass against the application the code generator produced, which is
settled at the bottom by running them. And the tiers the rules cannot honestly
assert are not asserted: an application with no authentication cannot be caught
refusing a caller, and a test that failed forever would say "this is broken"
where the truth is "this was never built".
"""

import json
import shutil
from dataclasses import dataclass
from typing import ClassVar

import pytest
from c3.generate import criteria as criteria_rules
from c3.generate import generate
from c3.generate.api_tests import build
from c3.generate.fill import bodies
from c3.generate.filling import fresh_bindings, merge_carried
from c3.harness.targets import TargetRepo
from sdlc_contracts import (
    AcceptanceCriterion,
    ApiContract,
    ApiEndpoint,
    EndpointSchema,
    EndpointTraces,
    EntityModel,
    SchemaField,
    SprintPlan,
    TestReport,
    UserStory,
    VelocityAssumption,
)
from sdlc_contracts.openapi import to_openapi

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")


@dataclass
class Ref:
    """The orchestrator's `TargetRef`, as the seam describes it."""

    kind: str
    code_version: int | None = None
    path: str = ""


def _document() -> dict:
    return to_openapi(_contract(), title="the generated app")


def _document_for(contract: ApiContract) -> dict:
    return to_openapi(contract, title="the generated app")


def _order_entity() -> EntityModel:
    return EntityModel(
        name="Order",
        fields=[
            SchemaField(name="id", type="id"),
            SchemaField(name="total", type="number"),
            SchemaField(name="note", type="string", required=False),
        ],
        traces=["R-1"],
    )


def _contract() -> ApiContract:
    entity = _order_entity()
    return ApiContract(
        version=1,
        entities=[entity],
        endpoints=[
            ApiEndpoint(
                id="get-orders",
                method="GET",
                path="/orders",
                response=EndpointSchema(entity="Order", fields=entity.fields),
                traces=EndpointTraces(story_ids=["US-1"], requirement_ids=["R-1"]),
            ),
            ApiEndpoint(
                id="post-orders",
                method="POST",
                path="/orders",
                request=EndpointSchema(
                    entity="Order", fields=[SchemaField(name="total", type="number")]
                ),
                response=EndpointSchema(entity="Order", fields=entity.fields),
                traces=EndpointTraces(story_ids=["US-1"], requirement_ids=["R-1"]),
            ),
            ApiEndpoint(
                id="delete-orders-id",
                method="DELETE",
                path="/orders/{id}",
                auth_actors=["Member"],
                traces=EndpointTraces(story_ids=["US-1"], requirement_ids=["R-1"]),
            ),
        ],
    )


def _story(story_id: str = "US-1", criteria: int = 1) -> UserStory:
    return UserStory(
        id=story_id,
        title="Place an order",
        epic="Orders",
        points=3,
        priority="must",
        traces=["R-1"],
        acceptance=[
            # `AC-<story number>-<n>`, which is the shape C1 issues. A fixture
            # using a different one would have let a test pass on an id nothing
            # produces.
            AcceptanceCriterion(
                id=f"AC-{story_id.split('-')[1]}-{index}",
                given="a basket with items",
                when="it is submitted",
                then="an order exists",
            )
            for index in range(1, criteria + 1)
        ],
    )


def _sprint(*stories: UserStory, backlog: tuple[UserStory, ...] = ()) -> SprintPlan:
    proposed = list(stories) or [_story()]
    return SprintPlan(
        sprint_name="Sprint 1",
        goal="Orders",
        estimated_points=sum(story.points for story in proposed),
        velocity_assumption=VelocityAssumption(points=10, basis="assumed"),
        proposed=proposed,
        backlog=list(backlog),
    )


class TestTheCriteriaSkeletons:
    def test_one_per_criterion_named_for_the_criterion(self) -> None:
        generation = generate(_sprint(_story(criteria=3)), _contract())
        path = "apps/api/src/__tests__/US-1.criteria.test.ts"

        body = generation.files[path]

        assert body.count("it.todo(") == 3
        assert "US-1 AC-1-1: given a basket with items" in body
        assert "US-1 AC-1-3:" in body

    def test_an_api_criterion_is_an_acceptance_test_and_not_an_integration_one(self) -> None:
        """They were labelled integration, and they run the app in process on
        its in-memory store: the generated test config pins MONGODB_URL empty,
        so they never touch the database a cloud release uses (review item
        C3-12)."""
        generation = generate(_sprint(_story(criteria=2)), _contract())

        kinds = {case.kind for case in generation.cases if case.criterion_id}

        assert kinds == {"acceptance"}

    def test_it_names_the_criterion_by_id_and_never_by_position(self) -> None:
        """A test outlives the design version it was written against.

        That is the healing loop's premise, and a position does not survive it.
        C1 carries a criterion id across design versions and never reissues one,
        so reordering the story's criteria must move neither the name a preserved
        test carries nor the trace the classifier reads. With the position in
        either of them, the second criterion's test would claim the first's
        identity as soon as a change note put them the other way round.
        """
        story = _story(criteria=2)
        reordered = story.model_copy(update={"acceptance": list(reversed(story.acceptance))})

        first = generate(_sprint(story), _contract())
        second = generate(_sprint(reordered), _contract())

        def named(generation) -> dict[str, str]:
            return {case.criterion_id: case.name for case in generation.cases if case.criterion_id}

        assert set(named(first)) == {"AC-1-1", "AC-1-2"}
        assert named(second) == named(first)
        body = second.files["apps/api/src/__tests__/US-1.criteria.test.ts"]
        assert "criterion 1" not in body, "a position is still in the test's name"

    def test_a_criterion_is_declared_and_never_vacuously_passed(self) -> None:
        """The rules know what a criterion says and nothing about how to
        observe it. A body here would be an invented assertion or a vacuous
        one, and `todo` reports as a skip rather than as a pass."""
        body = generate(_sprint(), _contract()).files[
            "apps/api/src/__tests__/US-1.criteria.test.ts"
        ]

        assert "expect(" not in body
        assert "it.todo(" in body

    def test_a_criterion_is_never_routed_to_an_app_the_target_lacks(self) -> None:
        """Found by a live run. The story is traced by an endpoint, so the
        rules wanted `apps/api`; the target had only `apps/web`, so the file
        landed where no runner is ever started. The tests were in the
        repository, absent from every report, and nobody was told.
        """
        generation = generate(_sprint(), _contract(), apps=("apps/web",))

        assert "apps/web/src/__tests__/US-1.criteria.test.ts" in generation.files
        assert not any(
            path.startswith("apps/api/") for path in generation.files if "criteria" in path
        )

    def test_a_criterion_goes_where_its_story_is_implemented(self) -> None:
        """Routing by the platform's own traceability, which a test generator
        pointed at the same repository does not have."""
        contract = _contract()
        untraced = _story("US-2")

        generation = generate(_sprint(_story(), untraced), contract)

        assert "apps/api/src/__tests__/US-1.criteria.test.ts" in generation.files
        assert "apps/web/src/__tests__/US-2.criteria.test.ts" in generation.files

    def test_the_backlog_is_not_generated_for(self) -> None:
        """Generating tests for work nobody committed to would put it in the
        report as though it were part of the increment."""
        generation = generate(_sprint(_story(), backlog=(_story("US-9"),)), _contract())

        assert not any("US-9" in path for path in generation.files)

    def test_a_story_id_cannot_leave_the_directory(self) -> None:
        """A story id reaches this from an artefact, and an artefact is written
        by a model. It names a file, so it may not name a path."""
        assert criteria_rules.slug("../../etc/passwd") == "etc-passwd"
        assert criteria_rules.slug("/absolute") == "absolute"
        assert criteria_rules.slug("") == "story"


class TestTheApiOracle:
    def test_it_asserts_the_status_the_document_declares(self) -> None:
        """Not a permissive set. The generated repository already ships a test
        per endpoint asserting the status is in one of those, and this is what
        it adds."""
        body = generate(_sprint(), _contract()).files[
            "apps/api/src/__tests__/orders.oracle.test.ts"
        ]

        assert "expect(answer.status).toBe(200);" in body
        assert "expect(answer.status).toBe(201);" in body
        assert "expect(answer.status).toBe(204);" in body

    def test_it_asserts_the_shape_the_document_declares(self) -> None:
        """A route answering 200 with the wrong body passes the first tier."""
        body = generate(_sprint(), _contract()).files[
            "apps/api/src/__tests__/orders.oracle.test.ts"
        ]

        assert 'expect(answer.body).toHaveProperty("total");' in body
        assert 'expect(typeof answer.body["total"]).toBe("number");' in body
        # The optional field is not asserted: the contract does not require it.
        assert '"note"' not in body

    def test_an_item_route_creates_what_it_addresses(self) -> None:
        """Through the API rather than through the application's internals, so
        the test exercises the public surface and this generator needs to know
        nothing about how the code generator names things."""
        body = generate(_sprint(), _contract()).files[
            "apps/api/src/__tests__/orders.oracle.test.ts"
        ]

        assert 'const seeded = await request(app).post("/orders")' in body
        assert "const answer = await request(app).delete(`/orders/${id}`)" in body

    def test_every_case_it_wrote_is_listed_with_its_traces(self) -> None:
        """The stage writes a report before anything runs, and it is built from
        these rather than from matching paths back afterwards."""
        generation = generate(_sprint(), _contract())
        api_cases = [case for case in generation.cases if case.kind == "api"]

        assert {one for case in api_cases for one in case.endpoint_ids} == {
            "get-orders",
            "post-orders",
            "delete-orders-id",
        }
        assert all(case.story_id == "US-1" for case in api_cases)
        assert all(case.requirement_ids == ["R-1"] for case in api_cases)
        # An oracle test is written for exactly one endpoint, so it names one.
        assert all(len(case.endpoint_ids) == 1 for case in api_cases)

    def test_a_criterion_case_names_every_endpoint_its_story_is_served_by(self) -> None:
        """Half the classifier's signal, which these carried none of.

        `diff_contracts` is one of its two inputs, and a criterion test with no
        endpoint gives it nothing to match. On generated code criteria tests are
        most of the tests, so most of the input could only ever be read through
        the requirement diff.
        """
        generation = generate(_sprint(), _contract())
        criteria_cases = [case for case in generation.cases if case.criterion_id]

        assert criteria_cases
        for case in criteria_cases:
            assert case.endpoint_ids == ["get-orders", "post-orders", "delete-orders-id"], (
                f"{case.criterion_id} names {case.endpoint_ids}"
            )


def _bounded_contract() -> ApiContract:
    """The order total bounded to 100 to 500, as C2 reads it from the criteria and
    enforces it in the handler; patched as well as created."""
    total = SchemaField(name="total", type="number", minimum=100, maximum=500)
    contract = _contract()
    [entity] = contract.entities
    entity = entity.model_copy(
        update={"fields": [total if f.name == "total" else f for f in entity.fields]}
    )
    post = contract.endpoints[1].model_copy(
        update={"request": EndpointSchema(entity="Order", fields=[total])}
    )
    patch = ApiEndpoint(
        id="patch-orders-id",
        method="PATCH",
        path="/orders/{id}",
        request=EndpointSchema(entity="Order"),
        traces=EndpointTraces(story_ids=["US-1"], requirement_ids=["R-1"]),
    )
    return contract.model_copy(
        update={
            "entities": [entity],
            "endpoints": [contract.endpoints[0], post, contract.endpoints[2], patch],
        }
    )


class TestAFieldsBounds:
    """C2 refuses a value outside the bounds a contract states, so the refusal is a
    feature that exists and is asserted, where a check nothing wrote stays a gap.
    The bounds were words in a comment, and the app took any value."""

    def test_a_value_outside_a_bound_is_asserted_refused_on_create_and_update(self) -> None:
        generation = generate(_sprint(), _bounded_contract())
        body = generation.files["apps/api/src/__tests__/orders.oracle.test.ts"]

        for endpoint_id in ("post-orders", "patch-orders-id"):
            assert f'it("{endpoint_id} refuses total 99, below its minimum 100"' in body
            assert f'it("{endpoint_id} refuses total 501, above its maximum 500"' in body
        assert '.send({"total": 99})' in body and '.send({"total": 501})' in body
        assert body.count("expect(answer.status).toBe(400);") == 4
        refusals = [case for case in generation.cases if "refuses total" in case.name]
        assert {case.endpoint_ids[0] for case in refusals} == {"post-orders", "patch-orders-id"}
        assert all(case.story_id == "US-1" for case in refusals)

    def test_the_happy_path_sends_a_value_inside_it(self) -> None:
        """The type's seed is 42, below 100: a create that sent it would be refused
        for a reason the test is not about, and every seeding POST with it."""
        body = generate(_sprint(), _bounded_contract()).files[
            "apps/api/src/__tests__/orders.oracle.test.ts"
        ]

        assert '.send({"total": 42})' not in body
        assert '.send({"total": 100})' in body
        assert 'const seeded = await request(app).post("/orders").send({"total": 100});' in body


class TestWhatIsAGapRatherThanATest:
    def test_declared_auth_with_no_authentication_is_reported_not_asserted(self) -> None:
        """A test asserting a refusal would fail forever and would say the
        wrong thing: the fault is an absent feature, not a broken one."""
        generation = generate(_sprint(), _contract())

        auth = [gap for gap in generation.gaps if gap.kind == "auth-not-implemented"]
        assert [gap.endpoint_id for gap in auth] == ["delete-orders-id"]
        body = generation.files["apps/api/src/__tests__/orders.oracle.test.ts"]
        assert "401" not in body

    def test_a_required_field_nothing_checks_is_reported_not_asserted(self) -> None:
        generation = generate(_sprint(), _contract())

        validation = [gap for gap in generation.gaps if gap.kind == "validation-not-enforced"]
        assert [gap.endpoint_id for gap in validation] == ["post-orders"]
        assert "total" in validation[0].detail
        assert "400" not in generation.files["apps/api/src/__tests__/orders.oracle.test.ts"]


class TestTheManifestAndTheRepeatability:
    def test_every_file_says_the_rules_wrote_it(self) -> None:
        generation = generate(_sprint(), _contract())

        assert {row.path for row in generation.manifest} == set(generation.files)
        assert all(row.arm == "rule" and row.generator == "rule" for row in generation.manifest)
        assert all(row.stage == "test-generation" for row in generation.manifest)

    def test_the_same_contract_generates_the_same_bytes(self) -> None:
        """A test that changed on every run could not be compared with the one
        before it, and comparing versions is what the healing loop does."""
        first = generate(_sprint(), _contract())
        second = generate(_sprint(), _contract())

        assert first.files == second.files


def _oracle_run(tmp_path, contract: ApiContract):
    """These tests, run against the app C2 generates from the same contract."""
    from c2.codegen.monorepo import generate_monorepo
    from c2_tests.design_fixture import scope, wireframes
    from c3.harness import Sandbox
    from c3.harness import node_lane as lane
    from c3.harness.targets import TargetRepo

    monorepo = generate_monorepo(
        "Oracle", contract, wireframes(), scope(), design_version=1, arm="rule"
    )
    checkout = tmp_path / "checkout"
    for generated in monorepo.files:
        target = checkout / generated.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated.content)

    story = scope().stories[0]
    sprint = _sprint(
        UserStory(
            id=story.id,
            title=story.title,
            epic="Fixture",
            points=story.points,
            priority="must",
            traces=list(story.traces.requirement_ids),
            acceptance=[
                AcceptanceCriterion(
                    id="AC-1",
                    given="the app is running",
                    when="a person uses it",
                    then="it does what the story says",
                )
            ],
        )
    )
    generation = generate(sprint, contract)
    repo = TargetRepo(root=checkout, kind="generated", stack="node", apps=("apps/api", "apps/web"))
    for path, content in generation.files.items():
        repo.write(path, content)

    lane.declare_measurement_tools(repo)
    box = Sandbox(checkout)
    assert lane.install(repo, box).passed
    authored = {path: "skeleton" for path in generation.files}
    return lane.run_tests(repo, box, authored=authored)


@pytest.mark.sandbox
@needs_npm
class TestAgainstWhatTheCodeGeneratorActuallyProduced:
    """The load bearing claim: these tests pass against the real application.

    Imports the code component's own design fixture, which is a test only
    dependency across the seam and is the point rather than an accident: the
    claim being settled is that one component's tests hold against another
    component's output, and nothing smaller settles it.
    """

    def test_the_rule_generated_tests_pass_against_the_generated_app(self, tmp_path) -> None:
        from c2.contract.rule_arm import generate_rule_contract
        from c2_tests.design_fixture import graph, scope, wireframes

        run = _oracle_run(tmp_path, generate_rule_contract(1, graph(), wireframes(), scope()))

        assert run.ran, run.steps[0].tail
        assert run.green, [
            (case.name, case.message)
            for suite in run.suites
            for case in suite.cases
            if case.outcome in ("failed", "errored")
        ]

        by_path = {suite.path: suite for suite in run.suites}
        oracles = [path for path in by_path if path.endswith(".oracle.test.ts")]
        assert oracles, "the rule generated contract tests should have run"
        assert all(by_path[path].passed > 0 for path in oracles)

        # And the provenance survives the round trip: what this component wrote
        # is a skeleton, what came with the repository is upstream.
        origins = {
            case.origin
            for suite in run.suites
            for case in suite.cases
            if suite.path.endswith(".oracle.test.ts")
        }
        assert origins == {"skeleton"}
        upstream = {
            case.origin
            for suite in run.suites
            for case in suite.cases
            if suite.path.endswith(".contract.test.ts")
        }
        assert upstream == {"upstream"}

    def test_a_bounded_field_is_refused_by_the_app_and_every_test_still_passes(
        self, tmp_path
    ) -> None:
        """The bounds a criterion states, read by C2 into the contract, enforced by its
        handler and asserted here. None of that happened, and the Movie Tracker took
        release years 1999 and 2027. Every test passing says the samples on both
        sides of the seam stay inside the bounds too."""
        from c2.contract.field_rules import with_field_rules
        from c2.contract.rule_arm import generate_rule_contract
        from c2_tests.design_fixture import graph, scope, wireframes

        contract = with_field_rules(
            generate_rule_contract(1, graph(), wireframes(), scope()),
            ["An order total is at least 2000 and at most 9000"],
        )

        run = _oracle_run(tmp_path, contract)

        assert run.ran, run.steps[0].tail
        assert run.green, [
            (case.name, case.message)
            for suite in run.suites
            for case in suite.cases
            if case.outcome in ("failed", "errored")
        ]
        # A case is named under its describe block, so it ends with the test's name.
        passed = [
            case.name for suite in run.suites for case in suite.cases if case.outcome == "passed"
        ]
        for refusal in (
            "post-orders refuses total 1999, below its minimum 2000",
            "post-orders refuses total 9001, above its maximum 9000",
        ):
            assert any(name.endswith(refusal) for name in passed), refusal

    def test_the_criteria_skeletons_report_as_skipped_and_never_as_passed(self, tmp_path) -> None:
        """Proved on the real runner rather than by reading the file: `todo` is
        the framework's word for declared and unwritten, and the whole argument
        depends on it not arriving as a pass."""
        from c2.codegen.monorepo import generate_monorepo
        from c2.contract.rule_arm import generate_rule_contract
        from c2_tests.design_fixture import graph, scope, wireframes
        from c3.harness import Sandbox
        from c3.harness import node_lane as lane
        from c3.harness.targets import TargetRepo

        contract = generate_rule_contract(1, graph(), wireframes(), scope())
        monorepo = generate_monorepo(
            "Skeletons", contract, wireframes(), scope(), design_version=1, arm="rule"
        )
        checkout = tmp_path / "checkout"
        for generated in monorepo.files:
            target = checkout / generated.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(generated.content)

        story = scope().stories[0]
        generation = generate(
            _sprint(
                UserStory(
                    id=story.id,
                    title=story.title,
                    epic="Fixture",
                    points=story.points,
                    priority="must",
                    traces=list(story.traces.requirement_ids),
                    acceptance=[
                        AcceptanceCriterion(
                            id="AC-1", given="a person", when="they act", then="something happens"
                        )
                    ],
                )
            ),
            contract,
        )
        repo = TargetRepo(
            root=checkout, kind="generated", stack="node", apps=("apps/api", "apps/web")
        )
        for path, content in generation.files.items():
            repo.write(path, content)

        lane.declare_measurement_tools(repo)
        box = Sandbox(checkout)
        assert lane.install(repo, box).passed
        run = lane.run_tests(repo, box)

        criteria_suites = [
            suite for suite in run.suites if suite.path.endswith(".criteria.test.ts")
        ]
        assert criteria_suites, "the criteria file should have been collected"
        outcomes = {case.outcome for suite in criteria_suites for case in suite.cases}
        assert outcomes == {"skipped"}


def test_the_generated_files_are_valid_json_free_typescript() -> None:
    """A sample body is embedded as JSON, so a contract with a quote in a field
    name cannot break the file it is written into."""
    entity = EntityModel(
        name="Order", fields=[SchemaField(name='we"ird', type="string")], traces=["R-1"]
    )
    contract = ApiContract(
        version=1,
        entities=[entity],
        endpoints=[
            ApiEndpoint(
                id="post-orders",
                method="POST",
                path="/orders",
                request=EndpointSchema(entity="Order", fields=entity.fields),
                response=EndpointSchema(entity="Order", fields=entity.fields),
                traces=EndpointTraces(story_ids=["US-1"], requirement_ids=["R-1"]),
            )
        ],
    )

    body = generate(_sprint(), contract).files["apps/api/src/__tests__/orders.oracle.test.ts"]

    sent = body.split(".send(")[1].split(");")[0]
    assert json.loads(sent) == {'we"ird': "a sample value"}


class TestTheStageTheOrchestratorCalls:
    """The report generation writes, before anything has run it."""

    @staticmethod
    def _workspace(tmp_path):
        root = tmp_path / "ws"
        (root / "apps" / "api").mkdir(parents=True)
        (root / "package.json").write_text('{"workspaces": ["apps/*"]}')
        (root / "apps" / "api" / "package.json").write_text(
            '{"devDependencies": {"vitest": "^2.1.0"}}'
        )
        return root

    async def test_every_case_is_reported_as_not_run(self, tmp_path) -> None:
        """Not empty, not absent, not passed. The tests exist and nothing has
        executed them, and that is a different fact from all three."""
        from c3.service import C3

        target = Ref(kind="generated", code_version=7, path=str(self._workspace(tmp_path)))

        outcome = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=3
        )

        report = TestReport.model_validate(outcome.notes["report"])
        assert report.total > 0
        assert report.not_run == report.total
        assert report.passed == 0 and report.failed == 0 and report.skipped == 0

    async def test_the_report_is_stamped_with_the_version_it_lives_at(self, tmp_path) -> None:
        """A report that said version 1 while living at version 3 would be a
        number nobody could attribute."""
        from c3.service import C3

        target = Ref(kind="generated", code_version=7, path=str(self._workspace(tmp_path)))

        outcome = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=3
        )

        report = TestReport.model_validate(outcome.notes["report"])
        assert report.version == 3
        assert "code version 7" in report.target
        assert report.mutation is None and report.mutation_skipped_reason

    async def test_the_gaps_travel_with_the_files(self, tmp_path) -> None:
        from c3.service import C3

        target = Ref(kind="generated", code_version=7, path=str(self._workspace(tmp_path)))

        outcome = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=1
        )

        kinds = {gap["kind"] for gap in outcome.notes["gaps"]}
        assert kinds == {"auth-not-implemented", "validation-not-enforced"}

    async def test_the_report_names_what_no_test_can_assert(self, tmp_path) -> None:
        """They were counted in the summary and listed only in the notes, which
        reach the audit log and nothing else, so the page that says what was
        generated could not say what was not (the live clinic project,
        2026-10-13: "Every criterion in scope has a test" over five of them)."""
        from c3.service import C3

        target = Ref(kind="generated", code_version=7, path=str(self._workspace(tmp_path)))

        outcome = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=1
        )

        report = TestReport.model_validate(outcome.notes["report"])
        assert report.gaps, "the canned contract has obligations nothing implements"
        assert [(gap.endpoint_id, gap.kind, gap.detail) for gap in report.gaps] == [
            (gap["endpointId"], gap["kind"], gap["detail"]) for gap in outcome.notes["gaps"]
        ]

    async def test_a_java_target_is_refused_rather_than_written_into(self, tmp_path) -> None:
        """These rules write TypeScript. Writing it into a Maven project would
        produce files nothing compiles and a report that counted them."""
        from c3.service import C3, NotBuilt

        root = tmp_path / "java"
        root.mkdir()
        (root / "pom.xml").write_text("<project/>")
        target = Ref(kind="benchmark", path=str(root))

        with pytest.raises(NotBuilt, match="java target"):
            await C3("canned").generate_tests(
                target, _sprint(), _contract(), _document(), version=1
            )

    async def test_a_written_criteria_test_survives_the_next_run(self, tmp_path) -> None:
        """The stage that may change a written test is the guarded one.

        The live walk found every criteria file rewritten on every run, so a
        test could never be stale, and the healing loop's whole input could not
        occur. This is the property that makes it possible.
        """
        from c3.generate.fill import declared_names, written_names
        from c3.service import C3

        root = self._workspace(tmp_path)
        target = Ref(kind="generated", code_version=7, path=str(root))
        first = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=3
        )
        criteria = next(path for path in first.files if path.endswith(".criteria.test.ts"))

        # Stand in for a model having filled it, and for the behaviour it saw.
        skeleton = (root / criteria).read_text()
        name = declared_names(skeleton)[0]
        filled = skeleton.replace(
            f'it.todo("{name}")',
            f'it("{name}", () => {{ expect(total([1])).toBe(998); }})',
        ).replace("import { describe, it }", "import { describe, expect, it }")
        (root / criteria).write_text(filled)

        await C3("canned").generate_tests(target, _sprint(), _contract(), _document(), version=4)

        after = (root / criteria).read_text()
        assert "toBe(998)" in after, "the written body is still there to go stale"
        assert written_names(after) == [name]

    async def test_a_quarantined_contract_test_stays_quarantined_on_the_next_run(
        self, tmp_path
    ) -> None:
        """The contract tests are written again on every run, and a person's
        quarantine of one is carried across with its note, or the test would
        fail the review again at the next run."""
        from c3.generate.decisions import QUARANTINED_BY, quarantine
        from c3.generate.fill import skipped_names, written_names
        from c3.service import C3

        root = self._workspace(tmp_path)
        target = Ref(kind="generated", code_version=7, path=str(root))
        first = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=3
        )
        oracle = next(path for path in first.files if path.endswith(".oracle.test.ts"))
        name = written_names(first.files[oracle])[0]
        (root / oracle).write_text(
            quarantine(first.files[oracle], name, by="Ana", reason="wrong status", on="2026-10-05")
        )

        again = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=4
        )

        assert skipped_names(again.files[oracle]) == [name]
        assert f"{QUARANTINED_BY} Ana on 2026-10-05: wrong status" in again.files[oracle]
        assert (root / oracle).read_text() == again.files[oracle]

    async def test_a_quarantined_criteria_test_is_still_a_case_the_report_declares(
        self, tmp_path
    ) -> None:
        """Skipped is an outcome the run reports, so the report declares it."""
        from c3.generate.decisions import quarantine
        from c3.generate.fill import declared_names, skipped_names
        from c3.service import C3

        root = self._workspace(tmp_path)
        target = Ref(kind="generated", code_version=7, path=str(root))
        first = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=3
        )
        criteria = next(path for path in first.files if path.endswith(".criteria.test.ts"))
        skeleton = (root / criteria).read_text()
        name = declared_names(skeleton)[0]
        filled = skeleton.replace(
            f'it.todo("{name}")',
            f'it("{name}", () => {{ expect(total([1])).toBe(998); }})',
        ).replace("import { describe, it }", "import { describe, expect, it }")
        (root / criteria).write_text(
            quarantine(filled, name, by="Ana", reason="wrong total", on="2026-10-05")
        )

        again = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=4
        )

        assert skipped_names(again.files[criteria]) == [name]
        report = TestReport.model_validate(again.notes["report"])
        assert name in {case.name for suite in report.suites for case in suite.cases}

    async def test_an_untouched_skeleton_is_regenerated(self, tmp_path) -> None:
        """Nothing is lost by rewriting a file that is still all todos, and a
        criterion may have appeared in it."""
        from c3.service import C3

        root = self._workspace(tmp_path)
        target = Ref(kind="generated", code_version=7, path=str(root))
        first = await C3("canned").generate_tests(
            target, _sprint(), _contract(), _document(), version=3
        )
        criteria = next(path for path in first.files if path.endswith(".criteria.test.ts"))
        (root / criteria).write_text("// scribbled over\n")

        await C3("canned").generate_tests(target, _sprint(), _contract(), _document(), version=4)

        assert "scribbled" not in (root / criteria).read_text()


@pytest.mark.sandbox
@needs_npm
class TestTheModelFillAgainstARealWorkspace:
    """The fill is checked by collecting the file, never by running it.

    A model is not called: the answers are scripted, so what is under test is
    the check rather than a provider. What makes this worth the install is that
    the collector is real, and it is the only thing that can tell a file that
    looks like tests from a file that is tests.
    """

    @staticmethod
    def _checkout(tmp_path, name: str):
        from c2.codegen.monorepo import generate_monorepo
        from c2.contract.rule_arm import generate_rule_contract
        from c2_tests.design_fixture import graph, scope, wireframes

        contract = generate_rule_contract(1, graph(), wireframes(), scope())
        monorepo = generate_monorepo(
            name, contract, wireframes(), scope(), design_version=1, arm="rule"
        )
        checkout = tmp_path / "checkout"
        for generated in monorepo.files:
            target = checkout / generated.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(generated.content)
        story = scope().stories[0]
        sprint = _sprint(
            UserStory(
                id=story.id,
                title=story.title,
                epic="Fixture",
                points=story.points,
                priority="must",
                traces=list(story.traces.requirement_ids),
                acceptance=[
                    AcceptanceCriterion(
                        id="AC-1",
                        given="the API is running",
                        when="the collection is requested",
                        then="it answers with a list",
                    )
                ],
            )
        )
        return checkout, contract, sprint, story

    @staticmethod
    def _scripted(answer: str):
        """A filler agent whose one answer is written out here."""
        from c3.generate.fill import build_filler
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        def respond(messages, info):
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, json.dumps({"content": answer}))]
            )

        return build_filler(FunctionModel(respond))

    @staticmethod
    def _skeleton(checkout, sprint, contract, path: str) -> str:
        """The skeleton the stage itself writes: its setup binds the app's exports."""
        repo = TargetRepo(
            root=checkout, kind="generated", stack="node", apps=("apps/api", "apps/web")
        )
        return generate(sprint, contract, bound=fresh_bindings(repo)).files[path]

    @staticmethod
    def _body(skeleton: str, statements: str) -> str:
        """The skeleton with its todo turned into a real test, on the app its setup
        binds and through the client the skeleton imports."""
        from c3.generate.fill import declared_names

        name = declared_names(skeleton)[0]
        return skeleton.replace(
            f"  it.todo({json.dumps(name)});",
            f"  it({json.dumps(name)}, async () => {{\n    {statements}\n  }});",
        )

    async def test_a_draft_the_compiler_refuses_is_put_back(self, tmp_path) -> None:
        """The check the discipline names and never ran.

        Vitest strips types, so this draft collects and runs: it calls a method
        the app does not have, fails at run time, and the report reads as though
        the application were at fault. `app.request(...)` on an Express app is
        the real one, and it cost six repairs and a whole healing run before
        anybody asked the compiler.
        """
        from c3.service import C3

        checkout, contract, sprint, story = self._checkout(tmp_path, "Uncompilable")
        path = f"apps/api/src/__tests__/{story.id}.criteria.test.ts"
        skeleton = self._skeleton(checkout, sprint, contract, path)
        answer = self._body(
            skeleton,
            'const found = await app.request("/orders");\n    expect(found.status).toBe(200);',
        )
        target = Ref(kind="generated", code_version=1, path=str(checkout))

        outcome = await C3("scripted", filler=self._scripted(answer)).generate_tests(
            target, sprint, contract, _document_for(contract), version=2
        )

        assert isinstance(outcome.notes["fill"], list), outcome.notes["fill"]
        [result] = [one for one in outcome.notes["fill"] if one["path"] == path]
        assert not result["accepted"]
        assert any("the compiler refused" in one for one in result["reasons"]), result["reasons"]
        # And the skeleton is what ships, so who authored the file stays a fact.
        assert "it.todo(" in outcome.files[path]

    async def test_a_fill_that_collects_is_kept_and_marked_as_the_model_s(self, tmp_path) -> None:
        from c3.service import C3

        checkout, contract, sprint, story = self._checkout(tmp_path, "Filled")
        skeleton = self._skeleton(
            checkout, sprint, contract, f"apps/api/src/__tests__/{story.id}.criteria.test.ts"
        )
        answer = self._body(
            skeleton,
            'const found = await request(app).get("/orders");\n'
            "    expect(Array.isArray(found.body)).toBe(true);",
        )
        target = Ref(kind="generated", code_version=1, path=str(checkout))

        outcome = await C3("scripted", filler=self._scripted(answer)).generate_tests(
            target, sprint, contract, _document_for(contract), version=2
        )

        # A skipped fill leaves a sentence here rather than a list of results,
        # and that sentence is the fastest explanation of everything below.
        assert isinstance(outcome.notes["fill"], list), outcome.notes["fill"]
        path = f"apps/api/src/__tests__/{story.id}.criteria.test.ts"
        assert "it.todo(" not in outcome.files[path], outcome.notes["fill"][0]["reasons"]
        assert "request(app)" in outcome.files[path]
        assert [row.generator for row in outcome.manifest if row.path == path] == ["llm"]
        # The file says what it holds now. It said "Each is declared and not yet
        # written" over written tests, in the project's own repository.
        assert "declared and not yet written" not in outcome.files[path]
        assert "each written from its criterion" in outcome.files[path]
        assert (checkout / path).read_text() == outcome.files[path]

        report = TestReport.model_validate(outcome.notes["report"])
        filled = [case for case in report.cases if case.origin == "filled"]
        assert filled, "the case the model wrote should say the model wrote it"
        # And it still has not run: collecting is not running.
        assert report.not_run == report.total

    async def test_a_test_sent_back_is_written_against_its_reason(self, tmp_path) -> None:
        """The reviewer's reason reaches the model, and goes once it is answered."""
        from c3.generate.decisions import WRITE_AGAIN_FOR, write_again
        from c3.generate.fill import build_filler, declared_names
        from c3.service import C3
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        checkout, contract, sprint, story = self._checkout(tmp_path, "SentBack")
        path = f"apps/api/src/__tests__/{story.id}.criteria.test.ts"
        skeleton = self._skeleton(checkout, sprint, contract, path)
        name = declared_names(skeleton)[0]
        written = self._body(
            skeleton,
            'const found = await request(app).get("/orders");\n    expect(found.status).toBe(404);',
        )
        sent_back = write_again(
            written, name, by="Ana", reason="it expects a 404 where the list answers", on="d"
        )
        (checkout / path).write_text(sent_back)
        # A model that keeps every comment it was given, as rule five asks.
        answer = sent_back.replace(
            f"  it.todo({json.dumps(name)});",
            f"  it({json.dumps(name)}, async () => {{\n"
            '    const found = await request(app).get("/orders");\n'
            "    expect(Array.isArray(found.body)).toBe(true);\n  });",
        )
        asked: list[str] = []

        def respond(messages, info):
            asked.append(str(messages))
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, json.dumps({"content": answer}))]
            )

        target = Ref(kind="generated", code_version=1, path=str(checkout))
        outcome = await C3("scripted", filler=build_filler(FunctionModel(respond))).generate_tests(
            target, sprint, contract, _document_for(contract), version=2
        )

        assert asked and "it expects a 404 where the list answers" in asked[0]
        assert "Array.isArray(found.body)" in outcome.files[path], outcome.notes["fill"]
        assert WRITE_AGAIN_FOR not in outcome.files[path], "answered, so no longer asked"
        assert (checkout / path).read_text() == outcome.files[path]

    async def test_a_fill_the_runner_cannot_collect_is_put_back(self, tmp_path) -> None:
        """The check that only a real collector can make.

        This answer passes every static rule and the compiler: the name is
        kept, the body asserts something real, nothing forbidden appears, and
        every type is sound. The `it` sits inside a function nobody calls, so
        the text of the file says the test is there and the runner finds no
        test at all. Nothing short of asking the runner can tell those apart.

        It used to import a module that does not exist, which the compiler now
        refuses first and with a better sentence, so the collector was no longer
        the thing under test.
        """
        from c3.service import C3

        checkout, contract, sprint, story = self._checkout(tmp_path, "Broken")
        path = f"apps/api/src/__tests__/{story.id}.criteria.test.ts"
        skeleton = self._skeleton(checkout, sprint, contract, path)
        answer = self._body(
            skeleton,
            'const found = await request(app).get("/orders");\n'
            "    expect(Array.isArray(found.body)).toBe(true);",
        )
        # The `it` moves inside a function nobody calls. Every type is sound and
        # the assertion is real, so only the runner can say the test is absent.
        # After the describe's own opening, not the setup's `beforeEach`.
        answer = answer.replace(
            "() => {\n  it(", "() => {\n  function registerLater(): void {\n  it(", 1
        )
        head, _, tail = answer.rpartition("  });\n")
        answer = head + "  });\n  }\n  void registerLater;\n" + tail
        target = Ref(kind="generated", code_version=1, path=str(checkout))

        outcome = await C3("scripted", filler=self._scripted(answer)).generate_tests(
            target, sprint, contract, _document_for(contract), version=2
        )

        assert "it.todo(" in outcome.files[path], "the skeleton should have come back"
        assert "registerLater" not in outcome.files[path]
        assert [row.generator for row in outcome.manifest if row.path == path] == ["rule"]
        refused = [row for row in outcome.notes["fill"] if not row["accepted"]]
        assert refused, outcome.notes["fill"]
        assert "did not collect" in refused[0]["reasons"][0], refused[0]["reasons"]


class TestAnItemRouteNothingCanCreate:
    """An id the test invented is an id the application is right to refuse.

    Found by the first live run: the oracle asserted 200 against
    `/calculation-inputs/does-not-exist`, got the 404 the handler correctly
    returns, and reported six failures that were all the test's fault. Those
    failures reach the healing loop next, which would try to classify a
    generator bug as brittleness, so a test that fails for the wrong reason is
    worse here than a test that is not written.
    """

    @staticmethod
    def _document() -> dict:
        return {
            "paths": {
                # No POST on the collection, so nothing can be created.
                "/widgets/{id}": {
                    "get": {
                        "operationId": "get-widgets-id",
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["id"],
                                            "properties": {"id": {"type": "string"}},
                                        }
                                    }
                                }
                            },
                            "404": {"description": "not found"},
                        },
                    }
                }
            }
        }

    def test_it_asserts_the_refusal_rather_than_the_success(self) -> None:
        suite = build(self._document(), entities={}, request_schemas={})
        written = suite.files["apps/api/src/__tests__/widgets.oracle.test.ts"]

        assert "toBe(404)" in written
        assert "toBe(200)" not in written, "nothing can create the widget this would address"

    def test_the_success_path_becomes_a_visible_gap(self) -> None:
        suite = build(self._document(), entities={}, request_schemas={})

        gap = next(one for one in suite.gaps if one.kind == "no-way-to-create")
        assert "no POST on /widgets" in gap.detail
        assert "200" in gap.detail, "the gap says which status nothing can reach"

    def test_the_shape_of_a_success_body_is_not_asserted_either(self) -> None:
        """Checking a success schema against a not found body asserts that
        `{ error: "not found" }` has an id, which is the same wrong failure."""
        suite = build(self._document(), entities={}, request_schemas={})
        written = suite.files["apps/api/src/__tests__/widgets.oracle.test.ts"]

        assert "declared shape" not in written

    def test_a_route_that_can_be_created_still_asserts_success(self) -> None:
        """The fix narrows nothing that worked: with a collection POST the
        test creates a widget and asks for the status the contract declares."""
        document = self._document()
        document["paths"]["/widgets"] = {
            "post": {
                "operationId": "post-widgets",
                "responses": {"201": {"description": "created"}},
            }
        }

        suite = build(document, entities={}, request_schemas={})
        written = suite.files["apps/api/src/__tests__/widgets.oracle.test.ts"]

        assert "toBe(200)" in written
        assert "${id}" in written, "it addresses the widget it just created"
        assert not [one for one in suite.gaps if one.kind == "no-way-to-create"]


class TestTestsAlreadyWrittenAreNotWrittenOver:
    """The generator is the one thing that may not change a test silently.

    A criteria test encodes the behaviour a model observed when it was written.
    When the behaviour moves underneath it the test goes stale, fails, and the
    healing loop rewrites it under the guard, where a mutant has to die and a
    refusal is recorded. Overwriting it here does that job with none of those
    checks, and the failure the component exists to classify never happens: the
    live walk found every criteria file rewritten on every run, so no test
    could ever be stale.
    """

    SKELETON = (
        "// story: US-1 A story\n// requirements: R-1\n"
        'import { describe, it } from "vitest";\n'
        'it.todo("US-1 criterion 1: a thing happens");\n'
    )

    WRITTEN = (
        "// story: US-1 A story\n// requirements: R-1\n"
        'import { describe, expect, it } from "vitest";\n'
        'it("US-1 criterion 1: a thing happens", () => { expect(total([1])).toBe(1); });\n'
    )

    PATH = "apps/api/src/__tests__/US-1.criteria.test.ts"

    def _repo(self, tmp_path, existing: dict[str, str]):
        repo = TargetRepo(root=tmp_path, kind="generated", stack="node", apps=("apps/api",))
        for path, content in existing.items():
            repo.write(path, content)
        return repo

    def test_a_written_criteria_file_keeps_its_tests(self, tmp_path) -> None:
        repo = self._repo(tmp_path, {self.PATH: self.WRITTEN})

        [one] = merge_carried(repo, {self.PATH: self.SKELETON}).values()

        assert one.carried == ("US-1 criterion 1: a thing happens",)
        assert "expect(total([1])).toBe(1)" in one.content

    def test_a_file_that_is_still_all_todos_is_left_to_be_regenerated(self, tmp_path) -> None:
        """Nothing is lost by regenerating a skeleton, and a new criterion may
        have appeared in it."""
        repo = self._repo(tmp_path, {self.PATH: self.SKELETON})

        assert merge_carried(repo, {self.PATH: self.SKELETON}) == {}

    def test_a_criterion_that_appeared_is_declared_beside_what_was_kept(self, tmp_path) -> None:
        """The whole point. A design regeneration rewrites every criterion, so
        the old test is stale and the new criterion has none, and both facts
        have to survive into the report."""
        repo = self._repo(tmp_path, {self.PATH: self.WRITTEN})
        grown = self.SKELETON + 'it.todo("US-1 criterion 2: another thing");\n'

        [one] = merge_carried(repo, {self.PATH: grown}).values()

        assert one.carried == ("US-1 criterion 1: a thing happens",)
        assert "US-1 criterion 2: another thing" in one.declared
        assert 'it.todo("US-1 criterion 2: another thing")' in one.content
        # And the test that was already there is untouched.
        assert "expect(total([1])).toBe(1)" in one.content

    def test_a_criterion_that_went_away_keeps_its_test_anyway(self, tmp_path) -> None:
        """That test is exactly the healing loop's input: it was written
        against behaviour the platform used to promise. Regenerating it away
        would be the generator changing a test with nothing proved."""
        repo = self._repo(
            tmp_path,
            {
                self.PATH: self.WRITTEN
                + 'it("US-1 criterion 2: gone", () => { expect(1).toBe(2); });\n'
            },
        )

        [one] = merge_carried(repo, {self.PATH: self.SKELETON}).values()

        assert "US-1 criterion 2: gone" in one.carried

    def test_an_oracle_test_is_never_carried(self, tmp_path) -> None:
        """It asserts what the contract declares, so it follows the contract."""
        oracle = "apps/api/src/__tests__/widgets.oracle.test.ts"
        repo = self._repo(tmp_path, {oracle: self.WRITTEN})

        assert merge_carried(repo, {oracle: self.SKELETON}) == {}

    def test_a_file_that_does_not_exist_yet_is_not_merged(self, tmp_path) -> None:
        repo = self._repo(tmp_path, {})

        assert merge_carried(repo, {self.PATH: self.SKELETON}) == {}

    def test_a_file_whose_shape_it_cannot_find_keeps_its_tests_and_gains_none(
        self, tmp_path
    ) -> None:
        """Appending after the end would be a syntax error, and a file that
        will not parse is worse than a criterion without a test."""
        odd = 'it("US-1 criterion 1: a thing happens", () => { expect(1).toBe(1); })'
        repo = self._repo(tmp_path, {self.PATH: odd})
        grown = self.SKELETON + 'it.todo("US-1 criterion 2: another thing");\n'

        [one] = merge_carried(repo, {self.PATH: grown}).values()

        assert one.content == odd
        assert one.carried == ("US-1 criterion 1: a thing happens",)


class TestEachTestLoadsItsOwnApplication:
    """Book Tracker's release was refused in staging over this.

    The generated app builds its store when `app.ts` loads, and a static import
    loads it once for a whole file. So "given a user with one book already in
    their list" found the book the test before it had added (three books, not
    two), the test review let the red test through, and staging refused the
    candidate. A skeleton on a side whose `app.ts` exports something now loads
    it afresh before every test.
    """

    BOUND: ClassVar[dict[str, list[str]]] = {"api": ["app", "widgetsRepository"]}
    PATH = "apps/api/src/__tests__/US-1.criteria.test.ts"

    def test_an_api_skeleton_loads_the_app_afresh_before_every_test(self) -> None:
        body = generate(_sprint(), _contract(), bound=self.BOUND).files[self.PATH]

        setup = criteria_rules.fresh_app_block(["app", "widgetsRepository"])
        assert setup.rstrip("\n") in body
        assert 'import { beforeEach, describe, expect, it, vi } from "vitest";' in body
        assert criteria_rules.fresh_app_of(body) == ("../app.ts", ["app", "widgetsRepository"])

    def test_a_side_with_nothing_bound_keeps_the_plain_skeleton(self) -> None:
        generation = generate(_sprint(_story(), _story("US-2")), _contract(), bound=self.BOUND)

        web = generation.files["apps/web/src/__tests__/US-2.criteria.test.ts"]
        assert criteria_rules.fresh_app_of(web) is None
        assert 'import { describe, it } from "vitest";' in web
        assert "supertest" not in web

    def test_an_api_skeleton_can_act_as_the_user_does(self) -> None:
        """On Movie Tracker's live run (2026-10-06) every criteria file stayed
        todos. The skeleton imported nothing to call the API with, and the model
        keeps a skeleton's imports and imports only what it is told exists, so
        its drafts called a `request` nobody imported or imported one inside a
        body. The contract tests reach the app through supertest, and so does
        this, before the setup."""
        body = generate(_sprint(), _contract(), bound=self.BOUND).files[self.PATH]

        assert criteria_rules.SUPERTEST_IMPORT in body
        assert body.index(criteria_rules.SUPERTEST_IMPORT) < body.index("beforeEach(async")

    def test_a_side_without_an_app_to_drive_imports_no_http_client(self) -> None:
        body = generate(_sprint(), _contract(), bound={"api": ["widgetsRepository"]}).files[
            self.PATH
        ]

        assert "supertest" not in body

    def test_the_bound_names_are_the_app_s_values_and_never_its_types(self, tmp_path) -> None:
        """`typeof import(...)` has no member for a type, so binding one would
        not compile."""
        repo = TargetRepo(
            root=tmp_path, kind="generated", stack="node", apps=("apps/api", "apps/web")
        )
        repo.write(
            "apps/api/src/app.ts",
            "export const app = express();\n"
            "export const booksRepository = new InMemoryBookRepository();\n"
            "export interface Book { id: string }\n",
        )

        assert fresh_bindings(repo) == {"api": ["app", "booksRepository"]}


class TestACarriedFileMovesOntoAFreshApplication:
    """A test written before the setup existed is carried, and carried tests
    are the healing loop's to change, not the generator's. So only the import
    moves: every body keeps every character, because the setup binds each
    export under the name the test already uses. Book Tracker's failing test was
    exactly such a file, so a rerun would have carried the failure forward."""

    NAMES: ClassVar[list[str]] = ["app", "booksRepository"]
    PATH = "apps/api/src/__tests__/US-1.criteria.test.ts"
    NAME = "US-1 AC-1-1: given no books, when one is added, then the list holds it"
    SKELETON = (
        "// story: US-1 Add a book\n// requirements: R-1\n"
        'import { beforeEach, describe, it, vi } from "vitest";\n\n'
        + criteria_rules.fresh_app_block(["app", "booksRepository"])
        + '\ndescribe("Add a book", () => {\n'
        f"  it.todo({json.dumps(NAME)});\n"
        "});\n"
    )
    WRITTEN = (
        "// story: US-1 Add a book\n// requirements: R-1\n"
        'import { describe, it, expect, beforeEach } from "vitest";\n'
        'import request from "supertest";\n'
        'import { app } from "../app.ts";\n\n'
        'describe("Add a book", () => {\n'
        f"  it({json.dumps(NAME)}, async () => {{\n"
        '    await request(app).post("/books").send({ title: "Dune" });\n'
        '    const listed = await request(app).get("/books");\n'
        "    expect(listed.body).toHaveLength(1);\n"
        "  });\n"
        "});\n"
    )

    def _merged(self, tmp_path, existing: str):
        repo = TargetRepo(root=tmp_path, kind="generated", stack="node", apps=("apps/api",))
        repo.write(self.PATH, existing)
        [one] = merge_carried(repo, {self.PATH: self.SKELETON}).values()
        return one

    def test_only_the_import_moves_and_every_body_keeps_every_character(self, tmp_path) -> None:
        one = self._merged(tmp_path, self.WRITTEN)

        assert (one.moved, one.left_shared) == (True, "")
        assert criteria_rules.fresh_app_of(one.content) == ("../app.ts", self.NAMES)
        assert 'import { app } from "../app.ts";' not in one.content
        assert 'import { describe, it, expect, beforeEach, vi } from "vitest";' in one.content
        assert bodies(one.content) == bodies(self.WRITTEN)

    def test_a_type_import_from_the_app_stays(self, tmp_path) -> None:
        typed = self.WRITTEN.replace(
            'import { app } from "../app.ts";', 'import { app, type Book } from "../app.ts";'
        )

        one = self._merged(tmp_path, typed)

        assert one.moved
        assert 'import type { Book } from "../app.ts";' in one.content

    def test_a_file_importing_the_app_as_a_whole_is_left_and_says_why(self, tmp_path) -> None:
        whole = self.WRITTEN.replace(
            'import { app } from "../app.ts";', 'import * as api from "../app.ts";'
        ).replace("request(app)", "request(api.app)")

        one = self._merged(tmp_path, whole)

        assert not one.moved
        assert "as a whole" in one.left_shared
        assert one.content == whole

    def test_a_renamed_import_is_left_and_says_why(self, tmp_path) -> None:
        renamed = self.WRITTEN.replace(
            'import { app } from "../app.ts";', 'import { app as server } from "../app.ts";'
        ).replace("request(app)", "request(server)")

        one = self._merged(tmp_path, renamed)

        assert not one.moved
        assert "renames app as server" in one.left_shared

    def test_a_file_that_never_imports_the_app_shares_nothing(self, tmp_path) -> None:
        plain = self.WRITTEN.replace(
            'import { app } from "../app.ts";', 'import { total } from "../total.ts";'
        )

        one = self._merged(tmp_path, plain)

        assert (one.moved, one.left_shared) == (False, "")
        assert one.content == plain

    # The skeleton as it is written now, with the client its tests act through.
    WITH_CLIENT = SKELETON.replace(
        'import { beforeEach, describe, it, vi } from "vitest";\n',
        'import { beforeEach, describe, it, vi } from "vitest";\n'
        + criteria_rules.SUPERTEST_IMPORT
        + "\n",
    )

    def test_a_carried_file_without_the_client_gains_it_and_keeps_its_bodies(
        self, tmp_path
    ) -> None:
        """A todo added to a carried file is written against that file's imports,
        and a file carried from before the skeleton imported supertest had nothing
        to call the API with: its new criteria would stay todos, as Movie
        Tracker's did."""
        through_the_repository = (
            "// story: US-1 Add a book\n// requirements: R-1\n"
            'import { describe, it, expect } from "vitest";\n'
            'import { booksRepository } from "../app.ts";\n\n'
            'describe("Add a book", () => {\n'
            f"  it({json.dumps(self.NAME)}, async () => {{\n"
            '    await booksRepository.create({ title: "Dune" });\n'
            "    expect(await booksRepository.list()).toHaveLength(1);\n"
            "  });\n"
            "});\n"
        )
        repo = TargetRepo(root=tmp_path, kind="generated", stack="node", apps=("apps/api",))
        repo.write(self.PATH, through_the_repository)

        [one] = merge_carried(repo, {self.PATH: self.WITH_CLIENT}).values()

        assert criteria_rules.SUPERTEST_IMPORT in one.content
        assert one.content.index(criteria_rules.SUPERTEST_IMPORT) < one.content.index(
            "beforeEach(async"
        )
        assert bodies(one.content) == bodies(through_the_repository)

    def test_a_carried_file_that_has_the_client_is_not_given_a_second(self, tmp_path) -> None:
        repo = TargetRepo(root=tmp_path, kind="generated", stack="node", apps=("apps/api",))
        repo.write(self.PATH, self.WRITTEN)

        [one] = merge_carried(repo, {self.PATH: self.WITH_CLIENT}).values()

        assert one.content.count('from "supertest"') == 1


@pytest.mark.sandbox
@needs_npm
class TestTheFreshApplicationOnTheRealRunner:
    """Proved where the failure happened, on the runner against the generated
    app: two tests in one file, the second of which needs an empty store."""

    TESTS = (
        'describe("One store per test", () => {\n'
        '  it("the first leaves an item behind", async () => {\n'
        "    await STORE.create({} as never);\n"
        "    expect((await STORE.list()).length).toBe(1);\n"
        "  });\n"
        '  it("the second starts with an empty store", async () => {\n'
        "    expect((await STORE.list()).length).toBe(0);\n"
        "  });\n"
        "});\n"
    )

    def _outcomes(self, tmp_path, *, fresh: bool) -> dict[str, str]:
        from c2.codegen.monorepo import generate_monorepo
        from c2.contract.rule_arm import generate_rule_contract
        from c2_tests.design_fixture import graph, scope, wireframes
        from c3.harness import Sandbox
        from c3.harness import node_lane as lane

        contract = generate_rule_contract(1, graph(), wireframes(), scope())
        monorepo = generate_monorepo(
            "Fresh", contract, wireframes(), scope(), design_version=1, arm="rule"
        )
        repo = TargetRepo(
            root=tmp_path, kind="generated", stack="node", apps=("apps/api", "apps/web")
        )
        for generated in monorepo.files:
            repo.write(generated.path, generated.content)
        names = fresh_bindings(repo)["api"]
        store = next(name for name in names if name.endswith("Repository"))
        if fresh:
            head = 'import { beforeEach, describe, expect, it, vi } from "vitest";\n\n'
            head += criteria_rules.fresh_app_block(names) + "\n"
        else:
            head = 'import { describe, expect, it } from "vitest";\n'
            head += f'import {{ {store} }} from "../app.ts";\n\n'
        repo.write(
            "apps/api/src/__tests__/US-1.criteria.test.ts",
            head + self.TESTS.replace("STORE", store),
        )

        lane.declare_measurement_tools(repo)
        box = Sandbox(tmp_path)
        assert lane.install(repo, box).passed
        run = lane.run_tests(repo, box)
        assert run.ran, run.steps[0].tail
        return {
            case.name: case.outcome
            for suite in run.suites
            if suite.path.endswith("US-1.criteria.test.ts")
            for case in suite.cases
        }

    def test_the_second_test_starts_from_an_empty_store(self, tmp_path) -> None:
        outcomes = self._outcomes(tmp_path, fresh=True)

        assert set(outcomes.values()) == {"passed"}, outcomes

    def test_a_static_import_shares_one_store_and_the_second_test_fails(self, tmp_path) -> None:
        """The same two tests without the setup: the failure this replaces."""
        outcomes = self._outcomes(tmp_path, fresh=False)

        assert sorted(outcomes.values()) == ["failed", "passed"], outcomes
