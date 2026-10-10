"""Which stories a wireframe is expected to cover, and which it is not.

Coverage is trace overlap between a flow and a story, and every story used to be
scored against it. That counts work no screen could ever satisfy: ingesting
telemetry, syncing an ERP, staying available during delivery hours. One real plan
reported fourteen of twenty four stories uncovered when six of them were of that
kind, which reads as a hole in the design and is not one.
"""

import pytest
from orchestrator.checks.coverage import needs_a_screen, with_coverage
from orchestrator.readmodel.assemble import derive_project_view_from_stages
from sdlc_contracts import (
    ARTEFACT_STAGE_IDS,
    CODE_STAGE_IDS,
    DEPLOY_RUNNER_STAGE_IDS,
    DEPLOY_STAGE_IDS,
    DESIGN_STAGE_IDS,
    GENERATING_STAGE_IDS,
    TEST_STAGE_IDS,
    AcceptanceCriterion,
    ArchitectureGraph,
    FlowLink,
    FlowScreen,
    GraphEdge,
    GraphNode,
    Position,
    ScreenBlock,
    SprintPlan,
    UserStory,
    VelocityAssumption,
    WireframeFlow,
    WireframesArtefact,
)


def actor(node_id: str, label: str, kind: str = "primary") -> GraphNode:
    return GraphNode(
        id=node_id,
        kind="actor",
        label=label,
        actorKind=kind,
        traces=["R-1"],
        position=Position(x=0, y=0),
    )


def graph_with(*labels: str) -> ArchitectureGraph:
    nodes = [actor(f"a{n}", label) for n, label in enumerate(labels, start=1)]
    nodes.append(
        GraphNode(
            id="e1",
            kind="entity",
            label="Consignment",
            traces=["R-1"],
            position=Position(x=0, y=0),
        )
    )
    return ArchitectureGraph(
        nodes=nodes,
        edges=[
            GraphEdge(
                id="x1", source="a1", target="e1", kind="action", verb="packs", traces=["R-1"]
            )
        ],
    )


def story(story_id: str, title: str, traces: list[str]) -> UserStory:
    return UserStory(
        id=story_id,
        title=title,
        epic="Delivery",
        points=3,
        priority="must",
        traces=traces,
        acceptance=[AcceptanceCriterion(id=f"AC-{story_id}-1", given="a", when="b", then="c")],
    )


class TestWhoAStoryBelongsTo:
    """Conservative on purpose: only obvious non-people are excused."""

    GRAPH = graph_with("Delivery Driver", "Compliance Officer")

    @pytest.mark.parametrize(
        "title",
        [
            "As a Delivery Driver, I can capture a signature at each stop.",
            "As a delivery driver, I can follow my assigned route.",
            "As a Compliance Officer, I can export a batch's history.",
        ],
    )
    def test_a_story_an_actor_performs_needs_a_screen(self, title: str) -> None:
        assert needs_a_screen(story("US-1", title, ["R-1"]), self.GRAPH)

    @pytest.mark.parametrize(
        "title",
        [
            "As a doctor, I can issue a prescription.",
            "As a compliance officer, I can see who read a record.",
            "As an operator, I can reassign a stop on the Dispatch Board.",
            "As a stakeholder, I can rely on the platform being available.",
        ],
    )
    def test_a_role_the_graph_does_not_name_still_needs_one(self, title: str) -> None:
        # The reason this rule is not "the role must be a primary actor". A
        # design whose actors are Clinician and Administrator has stories about a
        # doctor and a compliance officer, and matching on the label excused
        # every one of them from coverage. A near miss in wording is not evidence
        # that nobody performs the story.
        assert needs_a_screen(
            story("US-1", title, ["R-1"]), graph_with("Clinician", "Administrator")
        )

    @pytest.mark.parametrize(
        "title",
        [
            "As the system, I continuously ingest temperature readings.",
            "As a calling system, I can request a notification.",
            "As the platform, I retry a failed delivery.",
        ],
    )
    def test_software_describing_itself_does_not(self, title: str) -> None:
        assert not needs_a_screen(story("US-9", title, ["R-1"]), self.GRAPH)

    def test_a_story_with_no_role_at_all_does_not(self) -> None:
        assert not needs_a_screen(
            story("US-9", "Ingest telemetry from sensors.", ["R-1"]), self.GRAPH
        )

    def test_an_external_system_the_design_names_does_not(self) -> None:
        # `external_system` actors are other software. Nobody looks at a screen
        # on their behalf, and the graph is consulted for exactly this.
        graph = ArchitectureGraph(
            nodes=[actor("a1", "Delivery Driver"), actor("a2", "ERP", "external_system")],
            edges=[],
        )
        assert not needs_a_screen(
            story("US-1", "As an ERP, I receive stock levels.", ["R-1"]), graph
        )

    def test_the_systemic_test_does_not_need_a_graph(self) -> None:
        # It reads the role, not the design, so a snapshot without a graph
        # classifies exactly the same way.
        assert not needs_a_screen(story("US-9", "As the system, I ingest readings.", ["R-1"]), None)
        assert needs_a_screen(story("US-1", "As a driver, I collect a load.", ["R-1"]), None)


def flow(flow_id: str, traces: list[str]) -> WireframeFlow:
    return WireframeFlow(
        id=flow_id,
        name="Collection",
        version="v1",
        traces=traces,
        screens=[
            FlowScreen(
                id="s1",
                name="Screen 1",
                terminal=False,
                blocks=[ScreenBlock(id="b1", kind="text", label="Something")],
                links=[FlowLink(id="l1", label="Next", targetId="s1", variant="primary")],
            )
        ],
    )


class TestTheTableKeepsEveryStory:
    """A row is never dropped, because a machine decided this one."""

    def test_a_story_that_needs_no_screen_still_gets_a_row(self) -> None:
        graph = graph_with("Delivery Driver")
        plan = SprintPlan(
            sprintName="Sprint 1 (proposed)",
            goal="Ship it",
            estimatedPoints=3,
            velocityAssumption=VelocityAssumption(points=20, basis="assumed"),
            proposed=[story("US-1", "As a Delivery Driver, I collect a consignment.", ["R-1"])],
            backlog=[story("US-2", "As the system, I ingest readings.", ["R-9"])],
        )
        wireframes = WireframesArtefact(flows=[flow("f1", ["R-1"])])

        rows = with_coverage(wireframes, plan, graph).coverage
        assert [r.story_id for r in rows] == ["US-1", "US-2"], "no row may be dropped"

        by_id = {r.story_id: r for r in rows}
        assert by_id["US-1"].needs_screen is True
        assert by_id["US-2"].needs_screen is False
        assert by_id["US-2"].covered is False, "unchanged: it has no screen, it just wants none"

    def test_the_score_is_taken_over_the_stories_that_need_one(self) -> None:
        graph = graph_with("Delivery Driver")
        plan = SprintPlan(
            sprintName="Sprint 1 (proposed)",
            goal="Ship it",
            estimatedPoints=3,
            velocityAssumption=VelocityAssumption(points=20, basis="assumed"),
            proposed=[story("US-1", "As a Delivery Driver, I collect a consignment.", ["R-1"])],
            backlog=[
                story("US-2", "As the system, I ingest readings.", ["R-9"]),
                story("US-3", "As the system, I raise an alert.", ["R-9"]),
            ],
        )
        wireframes = WireframesArtefact(flows=[flow("f1", ["R-1"])])
        rows = with_coverage(wireframes, plan, graph).coverage
        scored = [r for r in rows if r.needs_screen]
        assert len(scored) == 1, "the two system stories are not scored"
        assert len(rows) == 3, "but all three are still listed"


class TestTheCheapProjectDerivation:
    """The three fields `GET /projects` shows, from stage statuses alone.

    Composing a snapshot per project to reach them read every artefact of every
    project and took twenty one seconds on a development branch. The browser
    blocks its first paint on that call, so it was twenty one seconds of blank
    page on every refresh.

    `derive_project_view` still exists for the single project routes, which
    already hold a composed snapshot. The two must agree; these cases are the
    ones where they could differ.
    """

    ALL = dict.fromkeys(DESIGN_STAGE_IDS, "complete")

    def test_a_project_with_nothing_done_is_a_draft(self) -> None:
        assert derive_project_view_from_stages({}, approved=False) == {
            "reqPhase": "input",
            "progress": 0,
            "phaseProgress": {"design": 0, "code": 0, "testing": 0, "deployment": 0},
            "status": "draft",
            "runStopped": False,
        }

    def test_progress_counts_only_complete_stages(self) -> None:
        view = derive_project_view_from_stages(
            {
                "requirements": "complete",
                "domain-model": "failed",
                "architecture-graph": "generating",
            },
            approved=False,
        )
        # One of eight design stages is a tenth of the design's 80, and the design is
        # a quarter of the whole: 2.5, shown as 3.
        assert view["phaseProgress"]["design"] == 10 and view["progress"] == 3
        # A stage is generating: the list said "design" here while the project
        # page said "analyzing", because the two derivations disagreed.
        assert view["status"] == "analyzing"

    def test_req_phase_is_the_furthest_complete_stage(self) -> None:
        view = derive_project_view_from_stages(
            {"requirements": "complete", "domain-model": "complete"},
            approved=False,
        )
        assert view["reqPhase"] == "domain-model"

    def test_a_design_waiting_on_a_decision_is_not_finished(self) -> None:
        # The distinction the frontend already draws. Note the asymmetry that is
        # deliberate: progress counts stages, so it reads 100 once every stage is
        # complete, but `status` stays "design" until somebody approves. Only
        # approval moves a project on to code.
        waiting = derive_project_view_from_stages(self.ALL, approved=False)
        assert waiting["status"] == "design"
        assert waiting["status"] != "code"

    def test_an_approved_design_is_a_quarter_of_the_whole(self) -> None:
        """Approving the design finishes the first of four phases. It read 0 here,
        the code phase's own progress, under a header that says "Overall"."""
        done = derive_project_view_from_stages(self.ALL, approved=True)
        assert (done["reqPhase"], done["progress"], done["status"]) == ("design-review", 25, "code")

    def test_progress_after_approval_counts_the_code_stages(self) -> None:
        half_generated = {
            **self.ALL,
            "sprint-scope": "complete",
            "tech-stack": "complete",
            "api-contract": "complete",
            "frontend-code": "generating",
        }
        view = derive_project_view_from_stages(half_generated, approved=True)
        # The design's 100 and three eighths of the code's 80, over four phases.
        assert view["phaseProgress"]["code"] == 30 and view["progress"] == 33
        assert view["status"] == "code"

    def test_an_approved_code_review_moves_the_project_to_testing(self) -> None:
        # The next rung of the same ladder, read from its own gate kind. A kind
        # blind bool made a code approval indistinguishable from the design one.
        done = derive_project_view_from_stages(self.ALL, approved=True, code_approved=True)
        assert done["status"] == "testing"
        # Two phases of four finished: it read 100, from Testing onwards, as if the
        # project were done.
        assert done["progress"] == 50

    def test_an_approved_test_review_moves_the_project_to_deploy(self) -> None:
        # The frontend has named this rung and the next since it had a status
        # ladder, and the server stopped at testing: a released project read
        # "Testing".
        view = derive_project_view_from_stages(
            self.ALL, approved=True, code_approved=True, test_approved=True
        )
        assert view["status"] == "deploy" and view["progress"] == 75

    def test_a_verified_release_makes_the_project_complete(self) -> None:
        view = derive_project_view_from_stages(
            self.ALL,
            approved=True,
            code_approved=True,
            test_approved=True,
            released=True,
        )
        assert view["status"] == "complete" and view["progress"] == 100

    def test_a_code_approval_without_a_design_one_is_impossible_but_honest(self) -> None:
        # Data planted by hand or a bug: the ladder still reads newest phase
        # first rather than crashing or inventing a rung.
        view = derive_project_view_from_stages(self.ALL, approved=False, code_approved=True)
        assert view["status"] == "testing"

    def test_a_project_whose_first_run_stopped_is_not_a_draft(self) -> None:
        """Thirty two projects read "Draft" because their first run failed: a draft
        is a project nobody has started, and these had been started and stopped."""
        view = derive_project_view_from_stages(
            {"requirements": "failed"}, approved=False, started=True, stopped={"c1"}
        )
        assert view["status"] == "design"
        assert view["runStopped"] is True

    def test_a_project_never_started_is_a_draft_and_has_not_stopped(self) -> None:
        view = derive_project_view_from_stages({}, approved=False, started=False)
        assert (view["status"], view["runStopped"]) == ("draft", False)

    def test_a_stopped_run_in_another_phase_is_not_this_ones(self) -> None:
        """The design run that stopped long ago is not what a project in testing
        is waiting on: only the current phase's newest run counts."""
        view = derive_project_view_from_stages(
            self.ALL, approved=True, code_approved=True, started=True, stopped={"c1"}
        )
        assert (view["status"], view["runStopped"]) == ("testing", False)

    def test_a_stopped_run_that_is_running_again_has_not_stopped(self) -> None:
        view = derive_project_view_from_stages(
            {"requirements": "complete", "domain-model": "generating"},
            approved=False,
            started=True,
            stopped={"c1"},
        )
        assert (view["status"], view["runStopped"]) == ("analyzing", False)

    def test_overall_progress_across_the_four_phases(self) -> None:
        """Each phase is a quarter: its stages carry 80 of its 100, its approval (for
        deployment, a verified release) the last 20, so a phase waiting on its
        decision reads 80. It was the current phase's own figure, so a project
        waiting on its design review read 100, and so did Book Tracker, its tests
        approved and nothing released."""
        design = dict.fromkeys(DESIGN_STAGE_IDS, "complete")
        code = dict.fromkeys(CODE_STAGE_IDS, "complete")
        tests = dict.fromkeys(TEST_STAGE_IDS, "complete")
        analysed = dict.fromkeys(
            [s for s in DEPLOY_STAGE_IDS if s not in DEPLOY_RUNNER_STAGE_IDS], "complete"
        )

        def progress(stages: dict[str, str], **gates: bool) -> int:
            return derive_project_view_from_stages(
                stages, approved=gates.pop("approved", False), **gates
            )["progress"]

        assert progress({}) == 0
        assert progress(design) == 20
        assert progress({**design, **code}, approved=True) == 45
        assert progress({**design, **code, **tests}, approved=True, code_approved=True) == 70
        assert (
            progress(
                {**design, **code, **tests, **analysed},
                approved=True,
                code_approved=True,
                test_approved=True,
            )
            == 95
        )
        assert (
            progress(
                {**design, **code, **tests, **analysed},
                approved=True,
                code_approved=True,
                test_approved=True,
                released=True,
            )
            == 100
        )

    def test_a_skipped_stage_is_behind_the_project(self) -> None:
        """Staging Verification is skipped when no Docker daemon answers, and the run
        goes on to its review all the same. A phase waiting there reads 80 whether
        a stage ran or was decided not to apply."""
        analysed = {
            **dict.fromkeys(
                [s for s in DEPLOY_STAGE_IDS if s not in DEPLOY_RUNNER_STAGE_IDS], "complete"
            ),
            "staging-verification": "skipped",
        }
        view = derive_project_view_from_stages(
            analysed, approved=True, code_approved=True, test_approved=True
        )
        assert view["phaseProgress"]["deployment"] == 80 and view["progress"] == 95

    def test_a_missing_stage_reads_as_pending_not_as_a_crash(self) -> None:
        # A project created before a stage existed has no row for it.
        assert (
            derive_project_view_from_stages({"requirements": "complete"}, approved=False)[
                "reqPhase"
            ]
            == "requirements"
        )


class TestWhichStagesARunSaysItIsWorkingOn:
    """Domain Model spins with the graph; Design Review never spins.

    Domain Model produces no artefact, so it was left out of the set marked
    generating and sat grey and finished-looking beside seven spinners. It is a
    projection of the architecture graph, so it is being built exactly when the
    graph is, and grey read as skipped.

    Design Review stays out for the opposite reason: it is the gate, it has
    nothing to do until every other stage is finished, and showing it as
    generating would misdescribe the run.
    """

    def test_domain_model_spins_with_the_rest(self) -> None:
        assert "domain-model" in GENERATING_STAGE_IDS

    def test_the_gate_never_claims_to_be_working(self) -> None:
        assert "design-review" not in GENERATING_STAGE_IDS

    def test_it_is_the_artefacts_plus_exactly_one(self) -> None:
        assert set(GENERATING_STAGE_IDS) - set(ARTEFACT_STAGE_IDS) == {"domain-model"}

    def test_every_stage_is_accounted_for(self) -> None:
        # Anything neither generated nor the gate would sit pending forever, and
        # the client decides the gate is reachable by asking whether every stage
        # is complete.
        unexplained = set(DESIGN_STAGE_IDS) - set(GENERATING_STAGE_IDS) - {"design-review"}
        assert unexplained == set(), f"{unexplained} would never leave pending"


class TestOwnershipIsNotOptional:
    """Every project read goes through an owner, or through one named exception.

    The scoping was added by threading an owner through the store, and an
    internal call inside `patch_project` was missed because the search looked for
    the qualified `store.get_project` and that one is unqualified. It failed
    loudly, which is the good case; a reader that had silently fallen back to
    unscoped would not have.
    """

    def test_the_project_reads_demand_an_owner(self) -> None:
        import inspect

        from orchestrator.db import store

        for name in ("get_project", "list_projects", "delete_project", "project_progress"):
            parameters = inspect.signature(getattr(store, name)).parameters
            assert "owner_id" in parameters, f"{name} can read across owners"
            assert parameters["owner_id"].default is inspect.Parameter.empty, (
                f"{name} defaults its owner, which is how everything ends up "
                "owned by whoever the default names"
            )

    def test_creating_a_project_demands_an_owner(self) -> None:
        import inspect

        from orchestrator.db import store

        owner = inspect.signature(store.create_project).parameters["owner_id"]
        assert owner.default is inspect.Parameter.empty

    def test_only_the_two_documented_functions_skip_the_owner(self) -> None:
        """Read the code, not the comments.

        Two earlier versions of this got it wrong in the same way. A line based
        check called `project_progress` unscoped because its WHERE sits on a
        different line from its FROM. Then a source text check called
        `patch_project` scoped because its docstring happens to contain the word
        `owner_id`. Both are the mistake of matching near the thing instead of
        the thing, so this parses the body and drops the docstring.
        """
        import ast
        import inspect
        import textwrap

        from orchestrator.db import store

        def body_without_docstring(function) -> str:
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
            definition = tree.body[0]
            if ast.get_docstring(definition):
                definition.body = definition.body[1:]
            return ast.unparse(definition)

        unscoped = []
        for name, function in vars(store).items():
            if not inspect.isfunction(function) or name.startswith("_"):
                continue
            code = body_without_docstring(function)
            if "app.projects" in code and "owner_id" not in code:
                unscoped.append(name)

        # Both are documented as authorised by their caller. Written out rather
        # than counted, so a third has to be argued for here before it exists.
        assert sorted(unscoped) == ["patch_project", "project_without_owner_check"], (
            f"these touch app.projects without an owner: {sorted(unscoped)}"
        )
