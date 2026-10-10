"""The checks that compare artefacts, and the coverage they are computed over.

Two groups carry the weight.

The staleness group builds a design where every artefact was correct when it was
made and the requirements have since moved on. That is not hypothetical: it is
what happens every time somebody requests a change, and each artefact's own rules
pass on it because each one only ever sees itself. It is also why these checks
live here rather than in the component: nothing that generates one artefact can
see the other five.

The rate group is about honesty. `test_an_empty_design_has_no_rate` is the one
that matters: a project with nothing in it has not achieved perfect consistency,
and a metric saying otherwise puts the emptiest run at the top of the table.
"""

import httpx
import pytest
from orchestrator.checks.consistency import RULE_IDS, Design, check_design
from orchestrator.checks.coverage import with_coverage
from sdlc_contracts import (
    AcceptanceCriterion,
    ArchitectureGraph,
    FlowLink,
    FlowScreen,
    GraphNode,
    ParsedRequirement,
    Position,
    ScreenBlock,
    SequenceStep,
    SprintPlan,
    UmlArtefact,
    UseCase,
    UserStory,
    VelocityAssumption,
    WireframeFlow,
    WireframesArtefact,
)


def requirement(id: str, priority: str = "must") -> ParsedRequirement:
    return ParsedRequirement(
        id=id, text=f"Requirement {id}.", type="functional", priority=priority, confidence=80
    )


REQUIREMENTS = [requirement("R-1"), requirement("R-2"), requirement("R-3", "should")]


def graph() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[
            GraphNode(
                id="a1",
                kind="actor",
                label="Customer",
                position=Position(x=0, y=0),
                traces=["R-1"],
                actorKind="primary",
            ),
            GraphNode(
                id="e1",
                kind="entity",
                label="Payment",
                position=Position(x=0, y=0),
                traces=["R-1", "R-2"],
                attributes=[{"name": "amount", "type": "number"}],
            ),
            GraphNode(
                id="m1",
                kind="service",
                label="Payment Service",
                position=Position(x=0, y=0),
                traces=["R-2"],
            ),
        ],
        edges=[],
    )


def story(id: str, traces: list[str], title: str = "As a customer, I can pay") -> UserStory:
    return UserStory(
        id=id,
        title=title,
        epic="Payments",
        points=5,
        priority="must",
        traces=traces,
        acceptance=[AcceptanceCriterion(id=f"AC-{id}-1", given="a", when="b", then="c")],
    )


def sprint(proposed: list[UserStory], backlog: list[UserStory] | None = None) -> SprintPlan:
    return SprintPlan(
        sprintName="Sprint 1 (proposed)",
        goal="Pay for things.",
        velocityAssumption=VelocityAssumption(points=20, basis="assumed"),
        estimatedPoints=sum(s.points for s in proposed),
        proposed=proposed,
        backlog=backlog or [],
    )


def flow(id: str, traces: list[str], screens: int = 2) -> WireframeFlow:
    return WireframeFlow(
        id=id,
        name="Paying",
        version="v1",
        traces=traces,
        screens=[
            FlowScreen(
                id=f"s{n}",
                name=f"Screen {n}",
                terminal=False,
                blocks=[ScreenBlock(id=f"b{n}", kind="text", label="Something")],
                links=[FlowLink(id=f"l{n}", label="Next", targetId="s1", variant="primary")],
            )
            for n in range(1, screens + 1)
        ],
    )


def uml(steps: list[SequenceStep] | None = None, story_id: str | None = "US-1") -> UmlArtefact:
    return UmlArtefact(
        useCases=[
            UseCase(
                id="uc1",
                name="Paying",
                traces=["R-1"],
                storyId=story_id,
                steps=steps
                or [
                    SequenceStep(fromId="a1", toId="m1", message="pay for {e1}", kind="call"),
                    SequenceStep(fromId="m1", toId="a1", message="done", kind="return"),
                ],
            )
        ],
        diagrams=[],
    )


def good_design() -> Design:
    plan = sprint([story("US-1", ["R-1", "R-2"]), story("US-2", ["R-3"], "As an admin, I refund")])
    wireframes = with_coverage(
        WireframesArtefact(flows=[flow("flow-a1", ["R-1", "R-2"]), flow("flow-a2", ["R-3"])]), plan
    )
    return Design(
        requirements=REQUIREMENTS, graph=graph(), uml=uml(), wireframes=wireframes, sprint=plan
    )


def replacing(design: Design, **changes) -> Design:
    return Design(**{**design.__dict__, **changes})


class TestADesignThatAgreesWithItself:
    def test_nothing_fires(self) -> None:
        report = check_design(good_design())
        assert report.findings == (), f"a coherent design tripped {report.rule_ids()}"

    def test_the_rate_is_one(self) -> None:
        assert check_design(good_design()).rate == 1.0

    def test_something_was_actually_checked(self) -> None:
        # Without this, the assertion above passes on a design where every rule
        # returned early and looked at nothing.
        assert check_design(good_design()).subjects > 0


# --- one mutation per rule ----------------------------------------------------


def _story_with_no_screen(design: Design) -> Design:
    plan = design.sprint
    return replacing(
        design, wireframes=with_coverage(WireframesArtefact(flows=[flow("flow-a1", ["R-1"])]), plan)
    )


def _must_only_in_the_backlog(design: Design) -> Design:
    # R-3 is a should, so promote it and push its story out of the sprint.
    plan = sprint([story("US-1", ["R-1", "R-2"])], backlog=[story("US-2", ["R-3"])])
    return replacing(
        design,
        requirements=[requirement("R-1"), requirement("R-2"), requirement("R-3", "must")],
        sprint=plan,
        wireframes=with_coverage(design.wireframes, plan),
    )


def _use_case_names_a_missing_story(design: Design) -> Design:
    return replacing(design, uml=uml(story_id="US-99"))


def _participant_the_graph_lost(design: Design) -> Design:
    return replacing(
        design, graph=ArchitectureGraph(nodes=[n for n in graph().nodes if n.id != "m1"], edges=[])
    )


def _token_naming_a_deleted_node(design: Design) -> Design:
    return replacing(
        design,
        graph=ArchitectureGraph(nodes=[n for n in graph().nodes if n.id != "e1"], edges=[]),
        uml=uml(
            [
                SequenceStep(fromId="a1", toId="m1", message="pay for {e1}", kind="call"),
                SequenceStep(fromId="m1", toId="a1", message="done", kind="return"),
            ]
        ),
    )


def _requirement_that_was_removed(design: Design) -> Design:
    return replacing(design, requirements=[requirement("R-1"), requirement("R-2")])


MUTATIONS = [
    ("story-has-a-screen", "warning", _story_with_no_screen),
    ("must-is-in-the-sprint", "warning", _must_only_in_the_backlog),
    ("use-case-names-a-real-story", "error", _use_case_names_a_missing_story),
    ("diagram-participants-exist", "error", _participant_the_graph_lost),
    ("diagram-tokens-resolve", "error", _token_naming_a_deleted_node),
    ("traces-name-current-requirements", "error", _requirement_that_was_removed),
]


class TestTheRuleCatalogue:
    @pytest.mark.parametrize("rule_id,severity,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
    def test_the_mutation_trips_its_rule(self, rule_id: str, severity: str, mutate) -> None:
        report = check_design(mutate(good_design()))
        assert rule_id in report.rule_ids(), (
            f"{rule_id} did not fire; what fired was {report.rule_ids()}"
        )
        assert all(f.severity == severity for f in report.findings if f.rule_id == rule_id)

    def test_every_rule_in_the_catalogue_has_a_mutation(self) -> None:
        assert {rule_id for rule_id, _, _ in MUTATIONS} == set(RULE_IDS)

    @pytest.mark.parametrize("rule_id,severity,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
    def test_every_finding_sends_the_reader_somewhere(self, rule_id, severity, mutate) -> None:
        # These are read at the gate, and the thing to fix is on another page.
        for finding in check_design(mutate(good_design())).findings:
            assert finding.stage_id, f"{finding.rule_id} does not say where to go"
            assert finding.reason.strip()


class TestStalenessAfterARegeneration:
    """The failures the pipeline creates rather than the model.

    Each artefact passed its own rules when it was generated. The requirements
    then moved on, some stages regenerated and some did not, and only something
    holding all of them at once can see it.
    """

    def test_a_diagram_pointing_at_a_deleted_node_is_caught(self) -> None:
        report = check_design(_participant_the_graph_lost(good_design()))
        finding = next(f for f in report.errors if f.rule_id == "diagram-participants-exist")
        assert "m1" in finding.reason
        assert finding.stage_id == "uml-diagrams"

    def test_a_token_naming_a_deleted_node_is_caught_separately(self) -> None:
        # A diagram can have every participant right and still mention a node
        # that is gone, which renders to the reader as literal braces.
        report = check_design(_token_naming_a_deleted_node(good_design()))
        assert "diagram-tokens-resolve" in report.rule_ids()
        assert "{e1}" in next(
            f.reason for f in report.errors if f.rule_id == "diagram-tokens-resolve"
        )

    def test_a_trace_to_a_removed_requirement_is_caught_in_every_artefact(self) -> None:
        report = check_design(_requirement_that_was_removed(good_design()))
        stale = [f for f in report.errors if f.rule_id == "traces-name-current-requirements"]
        # The graph never used R-3, so the findings should come from the story
        # and the journey that did, and name both places.
        assert {f.stage_id for f in stale} == {"sprint-plan", "wireframes"}
        assert all("R-3" in f.reason for f in stale)


class TestTheRate:
    def test_an_empty_design_has_no_rate(self) -> None:
        # Not 1.0. Nothing was checked, so nothing was found to be consistent,
        # and a hundred percent here would rank the emptiest run first.
        report = check_design(Design())
        assert report.subjects == 0
        assert report.rate is None

    def test_a_design_with_one_problem_scores_below_one(self) -> None:
        report = check_design(_story_with_no_screen(good_design()))
        assert report.rate is not None
        assert 0 < report.rate < 1

    def test_the_rate_counts_what_was_looked_at_not_just_what_failed(self) -> None:
        # A bigger design with the same single problem should score higher,
        # otherwise the number punishes a project for being large and the
        # ablation rewards whichever run generated least.
        small = check_design(_story_with_no_screen(good_design()))

        grown = _story_with_no_screen(good_design())
        plan = sprint([*grown.sprint.proposed, story("US-3", ["R-1"], "As a customer, I refund")])
        big = check_design(
            replacing(grown, sprint=plan, wireframes=with_coverage(grown.wireframes, plan))
        )

        assert big.subjects > small.subjects, "the design did not actually grow"
        assert len(big.findings) == len(small.findings), "it should have the same one problem"
        assert big.rate > small.rate


class TestCoverage:
    def test_a_flow_covers_the_stories_it_shares_requirements_with(self) -> None:
        plan = sprint([story("US-1", ["R-1"]), story("US-2", ["R-3"])])
        covered = with_coverage(WireframesArtefact(flows=[flow("f1", ["R-1", "R-2"])]), plan)
        assert covered.flows[0].covers_story_ids == ["US-1"]

    def test_nothing_writes_it_at_generation_so_it_has_to_be_derived(self) -> None:
        # The regression this replaces: the read model filtered on
        # `coversStoryIds` and nothing ever set it, so every story read as
        # uncovered no matter how many screens realised it.
        raw = WireframesArtefact(flows=[flow("f1", ["R-1"])])
        assert raw.flows[0].covers_story_ids == []

        plan = sprint([story("US-1", ["R-1"])])
        assert with_coverage(raw, plan).coverage[0].covered is True

    def test_a_flow_sharing_nothing_covers_nothing(self) -> None:
        plan = sprint([story("US-1", ["R-1"])])
        covered = with_coverage(WireframesArtefact(flows=[flow("f1", ["R-9"])]), plan)
        assert covered.flows[0].covers_story_ids == []
        assert covered.coverage[0].covered is False

    def test_every_story_gets_a_row_including_the_uncovered_ones(self) -> None:
        # A table listing only what was covered reads a hundred percent every time.
        plan = sprint([story("US-1", ["R-1"]), story("US-2", ["R-3"])])
        rows = with_coverage(WireframesArtefact(flows=[flow("f1", ["R-1"])]), plan).coverage

        assert [row.story_id for row in rows] == ["US-1", "US-2"]
        assert [row.covered for row in rows] == [True, False]

    def test_screen_ids_are_composite_so_they_are_unambiguous(self) -> None:
        plan = sprint([story("US-1", ["R-1"])])
        rows = with_coverage(
            WireframesArtefact(flows=[flow("f1", ["R-1"], screens=2)]), plan
        ).coverage
        assert rows[0].screen_ids == ["f1/s1", "f1/s2"]

    def test_backlog_stories_are_counted_too(self) -> None:
        # Planned work with no screen is exactly what the table is for showing.
        plan = sprint([story("US-1", ["R-1"])], backlog=[story("US-2", ["R-3"])])
        rows = with_coverage(WireframesArtefact(flows=[flow("f1", ["R-1"])]), plan).coverage
        assert [row.story_id for row in rows] == ["US-1", "US-2"]

    def test_no_sprint_plan_means_no_rows_rather_than_a_crash(self) -> None:
        covered = with_coverage(WireframesArtefact(flows=[flow("f1", ["R-1"])]), None)
        assert covered.coverage == []
        assert covered.flows[0].covers_story_ids == []

    def test_it_matches_what_the_frontend_derives(self) -> None:
        # buildSnapshot.ts filters flows by coversStoryIds and lists every screen
        # of the matching flow. Both sides have to agree, or the fixture demo and
        # the real backend show different numbers for the same design.
        plan = sprint([story("US-1", ["R-1"])])
        rows = with_coverage(
            WireframesArtefact(flows=[flow("f1", ["R-1"], screens=3), flow("f2", ["R-9"])]), plan
        ).coverage
        assert rows[0].screen_ids == ["f1/s1", "f1/s2", "f1/s3"]


async def _model_request_failing_with(error: Exception) -> BaseException:
    """What a stage is raised when its model request gets no response, from the real client.

    The OpenAI client the DeepSeek lane uses, with retries off so the test does
    not wait, and pydantic-ai around it, as a stage calls them.
    """
    from openai import AsyncOpenAI
    from pydantic_ai import Agent
    from pydantic_ai.models import override_allow_model_requests
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    def refuse(request: httpx.Request) -> httpx.Response:
        raise error

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as http:
        client = AsyncOpenAI(
            base_url="https://model.invalid/v1", api_key="test", max_retries=0, http_client=http
        )
        model = OpenAIChatModel("deepseek-flash", provider=OpenAIProvider(openai_client=client))
        try:
            # The suite refuses model requests; this one never leaves the process,
            # since the transport above answers it, so it is allowed for this call.
            with override_allow_model_requests(True):
                await Agent(model).run("hello")
        except Exception as raised:
            return raised
    raise AssertionError("the request was answered")


class TestWhatAFailedStageSays:
    """A stage error is stored and then returned in a snapshot, so it reaches the
    browser. That makes it two things at once: an explanation a reader can act on,
    and a payload that must not carry provider internals.

    The run that prompted this stored a Groq rate limit body containing the
    account's organisation id, its service tier, exact token counts and a billing
    link, all of which went into the database and out to the client.
    """

    def test_a_rate_limit_reads_as_a_rate_limit(self) -> None:
        from orchestrator.errors import readable_failure

        raw = RuntimeError(
            "status_code: 429, model_name: llama-3.3-70b-versatile, body: {'error': "
            "{'message': 'Rate limit reached for model `llama-3.3-70b-versatile` in "
            "organization `org_01kzjvpz82e7d9d7btbss5hcn4` service tier `on_demand` on "
            "tokens per day (TPD): Limit 100000, Used 100000. Upgrade at "
            "https://console.groq.com/settings/billing'}}"
        )
        said = readable_failure(raw)

        assert "rate limiting" in said
        assert "Retry" in said
        # None of the account's business belongs in a snapshot.
        for leak in ("org_01", "on_demand", "100000", "console.groq.com", "billing"):
            assert leak not in said, f"{leak} reached the client"

    def test_credentials_and_quota_get_their_own_words(self) -> None:
        from orchestrator.errors import readable_failure
        from pydantic_ai.exceptions import ModelHTTPError

        assert "credentials" in readable_failure(
            ModelHTTPError(status_code=401, model_name="deepseek-chat", body=None)
        )
        assert "out of quota" in readable_failure(
            ModelHTTPError(
                status_code=429,
                model_name="gpt-5",
                body={"error": {"code": "insufficient_quota"}},
            )
        )

    def test_a_cloud_provider_s_401_is_not_the_model_s_key(self) -> None:
        """The codes were matched anywhere in any message, so a Render or Vercel
        refusal sent the reader to the model's key."""
        from orchestrator.errors import readable_failure

        said = readable_failure(RuntimeError("Render answered 401 to GET services: unauthorized"))

        assert "credentials" not in said
        assert "Render answered 401" in said

    def test_a_hash_with_429_in_it_is_not_a_rate_limit(self) -> None:
        from orchestrator.errors import readable_failure

        raw = "the files hash to 4290ab12cd34, not to candidate 0f1e2d3c4b5a"

        assert readable_failure(RuntimeError(raw)) == raw

    def test_a_model_failure_a_stage_wrapped_is_still_the_model_s(self) -> None:
        from orchestrator.errors import readable_failure
        from pydantic_ai.exceptions import ModelHTTPError

        try:
            try:
                raise ModelHTTPError(status_code=429, model_name="deepseek-chat", body={})
            except ModelHTTPError as failure:
                raise RuntimeError("the domain model stage could not finish") from failure
        except RuntimeError as wrapped:
            said = readable_failure(wrapped)

        assert "rate limiting" in said

    async def test_a_model_request_that_timed_out_says_the_model_did_not_answer(self) -> None:
        """On the live run Test Generation stopped with "Request timed out.", which
        said neither what had timed out nor what to do about it."""
        from orchestrator.errors import readable_failure

        failure = await _model_request_failing_with(httpx.ReadTimeout("timed out"))
        said = readable_failure(failure)

        assert str(failure) == "Request timed out.", "the client's own words, as the run saw them"
        assert "model provider did not answer in time" in said
        assert "Retrying it usually works" in said

    async def test_a_model_request_that_never_connected_says_so(self) -> None:
        from orchestrator.errors import readable_failure

        said = readable_failure(await _model_request_failing_with(httpx.ConnectError("refused")))

        assert "could not reach the model provider" in said

    async def test_a_model_timeout_a_stage_wrapped_is_still_the_model_s(self) -> None:
        from orchestrator.errors import readable_failure

        failure = await _model_request_failing_with(httpx.ReadTimeout("timed out"))
        try:
            raise RuntimeError("test generation could not finish") from failure
        except RuntimeError as wrapped:
            said = readable_failure(wrapped)

        assert "model provider did not answer in time" in said

    def test_a_timeout_that_is_not_the_model_s_is_not_blamed_on_it(self) -> None:
        """A registry or a GitHub call can time out too, and the model is not at fault."""
        from orchestrator.errors import readable_failure

        try:
            try:
                raise httpx.ReadTimeout("timed out")
            except httpx.ReadTimeout as timeout:
                raise RuntimeError("the npm registry did not answer: timed out") from timeout
        except RuntimeError as wrapped:
            said = readable_failure(wrapped)

        assert "model" not in said

    def test_any_other_model_status_is_said_without_the_body(self) -> None:
        from orchestrator.errors import readable_failure
        from pydantic_ai.exceptions import ModelHTTPError

        said = readable_failure(
            ModelHTTPError(
                status_code=503,
                model_name="deepseek-chat",
                body={"error": {"message": "overloaded for organization org_01abc"}},
            )
        )

        assert "answered 503" in said
        assert "org_01abc" not in said

    def test_the_components_own_reasons_pass_through(self) -> None:
        # These are already sentences, built from the rule that refused, and they
        # are the most useful thing a reader can be told.
        from orchestrator.errors import readable_failure

        reason = (
            "the graph still broke 2 rule(s) after 2 attempts: Calculator Result is not "
            "connected to anything, so it plays no part in the design."
        )
        assert readable_failure(RuntimeError(reason)) == reason

    def test_nothing_arrives_whole(self) -> None:
        from orchestrator.errors import readable_failure

        said = readable_failure(RuntimeError("x" * 5000))
        assert len(said) < 320
        assert said.endswith("...")

    def test_a_silent_exception_still_says_what_it_was(self) -> None:
        # In words, not as a class name: "The stage failed with TimeoutError and
        # no message" told a reader the name of a class in a library.
        from orchestrator.errors import readable_failure

        said = readable_failure(TimeoutError())

        assert "ran out of time" in said
        assert "TimeoutError" not in said
