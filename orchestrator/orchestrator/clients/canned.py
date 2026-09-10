"""A Component 1 that answers instantly and never calls a provider.

What the spine tests need. They are about runs, gates, versions and resume, and
none of that is any more true for having waited three minutes and spent money to
find out. This returns a small, valid design for any input, so every stage
persists a real artefact the read model composes and the contract accepts.

It is not a stub standing in for unwritten work: the real component exists and is
tested against a real model. This is the test double for the layer above it, and
the seam it plugs into is the same one the HTTP client uses.

`calls` records what was asked, which is how a test asserts the graph ran the
stages it claims to and in the order it claims to.
"""

import difflib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sdlc_contracts import (
    AcceptanceCriterion,
    AgreementCounts,
    ApiContract,
    ApiContractArtefact,
    ApiEndpoint,
    ArchitectureGraph,
    ArchitectureRecommendation,
    ArchitectureStyleNote,
    ArmComparison,
    ArmCounts,
    BuildReport,
    BuildStepReport,
    ClarifyingQuestion,
    ContractAgreement,
    CountedFact,
    CoverageEntry,
    DiffSpan,
    EarlierPage,
    EndpointSchema,
    EndpointTraces,
    EntityModel,
    FlowLink,
    FlowScreen,
    GraphEdge,
    GraphNode,
    GuardCheck,
    HealAttempt,
    HealReport,
    ManifestRow,
    MutationResult,
    ParsedRequirement,
    Position,
    RepositoryPointer,
    RequirementsArtefact,
    Reverification,
    SchemaField,
    ScopeStory,
    ScopeStoryTraces,
    ScorePart,
    ScreenBlock,
    SequenceStep,
    SprintPlan,
    SprintScope,
    StackCandidate,
    StackLayer,
    TechStackArtefact,
    TestCase,
    TestReport,
    TestSuite,
    TestSummary,
    TestTrace,
    ToolStep,
    TopologyCandidate,
    UmlArtefact,
    UmlDiagram,
    UseCase,
    UserStory,
    ValidationReport,
    VelocityAssumption,
    VerificationSnapshot,
    WireframeFlow,
    WireframesArtefact,
)

from ..db.store import now as store_now
from .c1 import StageOutcome
from .c2 import Arm, FilesOutcome, LandOutcome, PushOutcome
from .c3 import TestFilesOutcome
from .thinking import RUN_THINKING

#: Enough to exercise the read model without making a fixture unreadable.
MAX_CANNED_REQUIREMENTS = 8

#: What naming answers with, whatever text it is given: the spine tests this
#: double serves are about runs, gates and resume, never about whether a title
#: is a good one.
CANNED_TITLE = "Pharmacy Dispensing"


def canned_thinking(thinking: str | None, level: str) -> str | None:
    """What a canned component's record says at a level.

    Silent where the double says nothing about thinking, as most do; one given
    DeepSeek's off ("disabled") answers as a DeepSeek client would, with the
    level itself when a run asks for one.
    """
    if thinking is None:
        return None
    return thinking if level == "off" else level


@dataclass
class CannedC1:
    """Every call, answered from constants."""

    #: What produced these artefacts, since a run records it. Named for what it
    #: is: a design built from constants is not a design any model produced, and
    #: an audit log claiming otherwise would be worse than one saying nothing.
    model: str = "canned (no model)"
    #: What the requests say about thinking, as a run records it. None, since no
    #: request is made; a test that needs a value gives one.
    thinking: str | None = None
    #: The configured level, which a run uses where its account chose none.
    level: str = "off"
    #: The level each call came at, in order (None outside a run).
    levels: list[str | None] = field(default_factory=list)
    #: The stage names asked for, in order.
    calls: list[str] = field(default_factory=list)
    #: Stage names that should raise instead, for testing failure handling.
    fails: set[str] = field(default_factory=set)
    #: Clarifying questions to ask, until the input carries their answers: the
    #: real extractor does not ask what the brief already says.
    questions: list[str] = field(default_factory=list)
    #: What it asks instead once the input carries answers, for a test of the
    #: follow-up a design may ask after reading them. Empty by default.
    follow_ups: list[str] = field(default_factory=list)
    #: What the last wireframe stage was told the requirements say.
    wireframes_read: list[str] = field(default_factory=list)
    #: Stories the sprint plan leaves in the backlog (US-2 onward, 8 points
    #: each), for tests about moving stories into the build. None by default.
    backlog: int = 0

    def _called(self, name: str) -> None:
        self.calls.append(name)
        # The level the run asked this call at, so a test can see it arrive.
        self.levels.append(RUN_THINKING.get())
        if name in self.fails:
            raise RuntimeError(f"the {name} stage was told to fail")

    def thinking_for(self, level: str) -> str | None:
        """What a real component's record would say at a level; silent if this one is."""
        return canned_thinking(self.thinking, level)

    async def parse_requirements(self, text: str) -> StageOutcome[RequirementsArtefact]:
        """One requirement per line of input.

        Crude on purpose, and input dependent on purpose. A double that answered
        the same thing whatever it was given could not be used to prove that a
        change note reached the regeneration, which is one of the things the
        spine tests exist to check.
        """
        self._called("requirements")
        lines = [line.strip() for line in text.splitlines() if line.strip()] or [
            "Something was asked for."
        ]
        asking = self.follow_ups if "Answers to the design's questions" in text else self.questions
        return StageOutcome(
            artefact=RequirementsArtefact(
                requirements=[
                    ParsedRequirement(
                        id=f"R-{number}",
                        text=line[:200],
                        type="functional",
                        priority="must",
                        confidence=70,
                        sourceQuote=line[:200],
                    )
                    for number, line in enumerate(lines[:MAX_CANNED_REQUIREMENTS], start=1)
                ],
                questions=[
                    ClarifyingQuestion(id=f"Q-{number}", question=question, traces=["R-1"])
                    for number, question in enumerate(asking, start=1)
                ],
            ),
            summary=f"Requirements analysed: {len(lines)} requirement(s), 0 assumptions",
            notes={"returned": len(lines)},
        )

    async def build_graph(
        self, requirements: list[ParsedRequirement], *, text: str
    ) -> StageOutcome[ArchitectureGraph]:
        self._called("architecture-graph")
        traces = [r.id for r in requirements] or ["R-1"]
        return StageOutcome(
            artefact=ArchitectureGraph(
                nodes=[
                    GraphNode(
                        id="a1",
                        kind="actor",
                        label="Someone",
                        position=Position(x=0, y=0),
                        traces=traces,
                        actorKind="primary",
                    ),
                    GraphNode(
                        id="e1",
                        kind="entity",
                        label="Record",
                        position=Position(x=240, y=0),
                        traces=traces,
                        attributes=[{"name": "id", "type": "string"}],
                    ),
                    GraphNode(
                        id="m1",
                        kind="service",
                        label="Record Service",
                        position=Position(x=480, y=0),
                        traces=traces,
                    ),
                ],
                edges=[
                    GraphEdge(
                        id="x1",
                        source="a1",
                        target="e1",
                        kind="action",
                        verb="creates",
                        traces=traces,
                    ),
                    GraphEdge(
                        id="x2", source="m1", target="e1", kind="data", verb="owns", traces=traces
                    ),
                ],
            ),
            summary="Architecture graph ready: 3 nodes, 2 edges",
            notes={"attempts": 1},
        )

    async def recommend(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageOutcome[ArchitectureRecommendation]:
        self._called("architecture-recommendation")
        return StageOutcome(
            artefact=ArchitectureRecommendation(
                candidates=[
                    TopologyCandidate(
                        id="monolith",
                        name="Modular Monolith",
                        score=82,
                        rationale="Few services and no external systems.",
                        pros=["One thing to deploy"],
                        cons=["Scales as one piece", "One failure takes everything"],
                    ),
                    TopologyCandidate(
                        id="microservices",
                        name="Microservices",
                        score=41,
                        rationale="More boundaries than this design has reason for.",
                        pros=["Parts scale apart"],
                        cons=["More to operate", "Transactions cross boundaries"],
                    ),
                ],
                recommendedCandidateId="monolith",
                # Nobody has chosen yet: the gate is where a human answers.
                selectedCandidateId=None,
                style=ArchitectureStyleNote(
                    id="layered", name="Layered", note="Chosen because the design is small."
                ),
            ),
            summary="2 deployment shapes scored, Modular Monolith recommended at 82",
            notes={"margin": 41},
        )

    async def write_uml(self, graph: ArchitectureGraph) -> StageOutcome[UmlArtefact]:
        self._called("uml-diagrams")
        traces = list(graph.nodes[0].traces) if graph.nodes else ["R-1"]
        return StageOutcome(
            artefact=UmlArtefact(
                useCases=[
                    UseCase(
                        id="uc1",
                        name="Creating a record",
                        traces=traces,
                        steps=[
                            SequenceStep(
                                fromId="a1", toId="m1", message="create a {e1}", kind="call"
                            ),
                            SequenceStep(fromId="m1", toId="a1", message="done", kind="return"),
                        ],
                    )
                ],
                diagrams=[
                    UmlDiagram(id="class", kind="class", title="Class Diagram", traces=traces),
                    UmlDiagram(
                        id="sequence-uc1",
                        kind="sequence",
                        title="Sequence Diagram",
                        useCaseId="uc1",
                        traces=traces,
                    ),
                ],
            ),
            summary="2 diagrams generated, 1 interaction written",
            notes={},
        )

    async def draw_wireframes(
        self,
        graph: ArchitectureGraph,
        *,
        requirement_ids: list[str],
        version: str,
        requirements: list[ParsedRequirement] | None = None,
    ) -> StageOutcome[WireframesArtefact]:
        self._called("wireframes")
        self.wireframes_read = [one.text for one in requirements or []]
        traces = requirement_ids or ["R-1"]
        return StageOutcome(
            artefact=WireframesArtefact(
                flows=[
                    WireframeFlow(
                        id="flow-a1",
                        name="Creating a record",
                        version=version,
                        traces=traces,
                        screens=[
                            FlowScreen(
                                id="s1",
                                name="New record",
                                terminal=False,
                                blocks=[ScreenBlock(id="b1", kind="field", label="Name")],
                                links=[
                                    FlowLink(
                                        id="l1", label="Save", targetId="s2", variant="primary"
                                    )
                                ],
                            ),
                            FlowScreen(
                                id="s2",
                                name="Record Saved",
                                terminal=True,
                                blocks=[ScreenBlock(id="b2", kind="banner", label="Saved")],
                                links=[],
                            ),
                        ],
                    )
                ],
                # Derived by the read model against the sprint plan, which does
                # not exist at this point in the run.
                coverage=[],
            ),
            summary="1 flow generated, 2 screens",
            notes={"attempts": 1},
        )

    async def plan_sprint(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageOutcome[SprintPlan]:
        self._called("sprint-plan")
        traces = [r.id for r in requirements] or ["R-1"]
        story = UserStory(
            id="US-1",
            title="As someone, I can create a record",
            epic="Records",
            points=3,
            priority="must",
            traces=traces,
            acceptance=[
                AcceptanceCriterion(
                    id="AC-1-1",
                    given="someone on the new record screen",
                    when="they save",
                    then="the record is stored and confirmed",
                )
            ],
        )
        later = [
            UserStory(
                id=f"US-{number}",
                title=f"As someone, I can do thing {number}",
                epic="Records",
                points=8,
                priority="should",
                traces=traces,
                acceptance=[
                    AcceptanceCriterion(
                        id=f"AC-{number}-1",
                        given="someone on the records screen",
                        when=f"they do thing {number}",
                        then="it is done and confirmed",
                    )
                ],
            )
            for number in range(2, 2 + self.backlog)
        ]
        return StageOutcome(
            artefact=SprintPlan(
                sprintName="Sprint 1 (proposed)",
                goal="Someone can create a record.",
                velocityAssumption=VelocityAssumption(
                    points=20, basis="assumed, not measured: no delivered sprint yet"
                ),
                estimatedPoints=story.points,
                proposed=[story],
                backlog=later,
            ),
            summary="Sprint 1 (proposed) proposed: 1 story, 3 points estimated",
            notes={"attempts": 1},
        )

    async def name_project(self, text: str) -> str:
        self._called("naming")
        return CANNED_TITLE


# --------------------------------------------------------------------- c2


#: A one endpoint contract, and a monorepo that agrees with it. Coherent on
#: purpose: the read model composes these rows and the code snapshot's
#: validators are real, so a double that answered with an incoherent contract
#: would fail at the boundary rather than at the thing under test.
CANNED_CONTRACT = ApiContract(
    version=1,
    entities=[
        EntityModel(
            name="Thing",
            fields=[SchemaField(name="id", type="id"), SchemaField(name="label")],
            traces=["R-1"],
        )
    ],
    endpoints=[
        ApiEndpoint(
            id="get-things",
            method="GET",
            path="/things",
            summary="List things",
            auth_actors=["User"],
            response=EndpointSchema(entity="Thing"),
            traces=EndpointTraces(
                screen_ids=["flow/list"],
                action_ids=["b1"],
                story_ids=["US-1"],
                requirement_ids=["R-1"],
            ),
            origin="rule",
            confidence=80,
        )
    ],
)

CANNED_WEB_FILES = {
    "README.md": "# Canned\n",
    "packages/contract/src/client.ts": (
        "export const client = {\n"
        "  // implements get-things GET /things\n"
        "  getThings() { return fetchJson('/things'); },\n"
        "};\n"
    ),
    "apps/web/src/pages/FlowListPage.tsx": (
        "// screen: flow/list\nexport function FlowListPage() { return null; }\n"
    ),
}

CANNED_API_FILES = {
    "apps/api/src/app.ts": 'app.use("/things", thingsRouter(thingsRepository));\n',
    "apps/api/src/routes/things.ts": (
        "export function thingsRouter(repository: ThingRepository): Router {\n"
        "  // implements get-things GET /things\n"
        '  router.get("/", async (req, res) => { res.json(await repository.list()); });\n'
        "}\n"
    ),
}


def _canned_manifest(files: dict[str, str], stage: str, arm: str) -> list[ManifestRow]:
    return [
        ManifestRow(
            path=path,
            stage=stage,
            generator="rule",
            arm=arm,  # type: ignore[arg-type]
            implements=["get-things"],
            summary="Canned.",
            # A page records what its rewrite depended on, as C2's do, so the
            # next generation is handed it.
            written_from="canned-page" if path.startswith("apps/web/src/pages/") else "",
        )
        for path in files
    ]


@dataclass
class CannedC2:
    """Every call, answered from constants.

    CannedC1's counterpart, for the same reason: the C2 spine tests are about
    the code version axis, the stage table, the gate and the file store, and
    none of that is more true for having spent a minute generating a real
    monorepo through a real model.
    """

    model: str = "canned (no model)"
    thinking: str | None = None
    #: The configured level, which a run uses where its account chose none.
    level: str = "off"
    #: The level each call came at, in order (None outside a run).
    levels: list[str | None] = field(default_factory=list)
    #: The stage names asked for, in order.
    calls: list[str] = field(default_factory=list)
    #: Stage names that should raise instead, for testing failure handling.
    fails: set[str] = field(default_factory=set)
    #: What the push should answer. None means "no connection", which is the
    #: honest default for a test database with no credentials in it.
    pushes_to: RepositoryPointer | None = None
    #: The architecture the last stack proposal was asked from, for tests.
    stack_recommendation: ArchitectureRecommendation | None = None
    #: How the typecheck step ends, so a test can have a build that ran and failed.
    typecheck_outcome: str = "passed"
    #: The branch each push was asked for, in order.
    pushed_branches: list[str | None] = field(default_factory=list)
    #: The paths each push was handed, in order.
    pushed_paths: list[set[str]] = field(default_factory=list)
    #: The commits a landing moved the default branch to, in order.
    landed: list[str] = field(default_factory=list)
    #: Why landing is refused, when a test wants it refused.
    land_refused: str | None = None
    #: What a push raises, when a test wants GitHub to refuse it outright.
    push_raises: Exception | None = None
    #: Files the backend stage writes besides its own, so a test can have the
    #: generator write again a file an applied fix changed.
    extra_api_files: dict[str, str] = field(default_factory=dict)

    def _called(self, name: str) -> None:
        self.calls.append(name)
        # The level the run asked this call at, so a test can see it arrive.
        self.levels.append(RUN_THINKING.get())
        if name in self.fails:
            raise RuntimeError(f"the {name} stage was told to fail")

    def thinking_for(self, level: str) -> str | None:
        """What a real component's record would say at a level; silent if this one is."""
        return canned_thinking(self.thinking, level)

    async def derive_scope(
        self, sprint: SprintPlan, wireframes: WireframesArtefact
    ) -> StageOutcome[SprintScope]:
        """Every proposed story in scope, traced to whatever covers it.

        Input dependent, like CannedC1's parse: a scope that ignored the sprint
        plan could not prove the plan reached the stage.
        """
        self._called("sprint-scope")
        covered = {row.story_id: row.screen_ids for row in wireframes.coverage}
        stories = [
            ScopeStory(
                id=story.id,
                title=story.title,
                points=story.points,
                in_scope=in_scope,
                traces=ScopeStoryTraces(
                    requirement_ids=list(story.traces),
                    screen_ids=covered.get(story.id, []),
                ),
            )
            for in_scope, group in ((True, sprint.proposed), (False, sprint.backlog))
            for story in group
        ]
        scope = SprintScope(sprint_name=sprint.sprint_name, stories=stories)
        return StageOutcome(
            artefact=scope,
            summary=f"Sprint scope proposed: {len(scope.in_scope_ids)} in scope",
            notes={"stories_in_scope": len(scope.in_scope_ids)},
        )

    async def propose_stack(
        self, graph: ArchitectureGraph, recommendation: ArchitectureRecommendation | None = None
    ) -> StageOutcome[TechStackArtefact]:
        self._called("tech-stack")
        self.stack_recommendation = recommendation
        entities = sum(1 for node in graph.nodes if node.kind == "entity")
        artefact = TechStackArtefact(
            facts=[CountedFact(label="entities", value=entities)],
            candidates=[
                StackCandidate(
                    id="mern",
                    name="MERN",
                    layers=[
                        StackLayer(name="frontend", choice="React"),
                        StackLayer(name="backend", choice="Express"),
                        StackLayer(name="database", choice="MongoDB"),
                    ],
                    score=70,
                    score_breakdown=[ScorePart(label="baseline", points=70)],
                ),
                StackCandidate(
                    id="react-spring-postgres",
                    name="React and Spring Boot",
                    layers=[StackLayer(name="backend", choice="Spring Boot")],
                    score=60,
                    available=False,
                    unavailable_reason="generators not built yet",
                ),
            ],
            recommended_id="mern",
            selected_id="mern",
            selected_by="system default",
        )
        return StageOutcome(
            artefact=artefact, summary="Tech stack proposed: MERN (score 70)", notes={}
        )

    async def infer_contract(
        self,
        version: int,
        graph: ArchitectureGraph,
        wireframes: WireframesArtefact,
        scope: SprintScope,
        *,
        arm: Arm = "rule",
    ) -> StageOutcome[ApiContractArtefact]:
        self._called("api-contract")
        #: The graph's node names the last contract was inferred from, for the tests.
        self.contract_graph_labels = [node.label for node in graph.nodes] if graph else []
        contract = CANNED_CONTRACT.model_copy(update={"version": version})
        artefact = ApiContractArtefact(
            version=version,
            rule_arm=contract,
            llm_arm=contract,
            chosen=arm,
            contract=contract,
            comparison=ArmComparison(
                rule=ArmCounts(endpoints=1, attempts=1),
                llm=ArmCounts(endpoints=1, attempts=1),
                agreed=["GET /things"],
                agreement_rate=1.0,
            ),
        )
        return StageOutcome(
            artefact=artefact,
            summary=f"API contract inferred: 1 endpoint from the {arm} arm",
            notes={"chosen": arm},
        )

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
        earlier: list[EarlierPage] | None = None,
    ) -> FilesOutcome:
        self._called("frontend-code")
        #: What the last frontend stage asked of the page writer, for the tests.
        self.frontend_asked = {
            "fill": fill,
            "requirements": [one.text for one in requirements or []],
            "earlier": list(earlier or []),
        }
        return FilesOutcome(
            files=dict(CANNED_WEB_FILES),
            manifest=_canned_manifest(CANNED_WEB_FILES, "frontend-code", arm),
            summary="Frontend generated: 1 page, typed client included",
            notes={"files": len(CANNED_WEB_FILES)},
        )

    async def generate_backend(
        self, contract: ApiContract, *, arm: str = "rule", fill: bool = False
    ) -> FilesOutcome:
        self._called("backend-code")
        files = {**CANNED_API_FILES, **self.extra_api_files}
        return FilesOutcome(
            files=files,
            manifest=_canned_manifest(files, "backend-code", arm),
            summary="Backend generated: 1 route file with contract tests",
            notes={"files": len(files)},
        )

    async def check_agreement(
        self, contract: ApiContract, sources: dict[str, str]
    ) -> StageOutcome[ContractAgreement]:
        """Counted from what it was handed, never from a constant.

        The one call where a constant would be a lie a test could not see: an
        agreement report that says 100% whatever it is given would pass every
        assertion about a broken generation.
        """
        self._called("contract-agreement")
        served = sum(1 for content in sources.values() if "router.get" in content)
        total = len(contract.endpoints)
        implemented = min(served, total)
        agreement = ContractAgreement(
            contract_version=contract.version,
            counts=AgreementCounts(
                endpoints_total=total,
                endpoints_implemented=implemented,
                endpoints_missing=[e.id for e in contract.endpoints[implemented:]],
                endpoints_called=implemented,
                agreement_rate=(implemented / total) if total else 1.0,
            ),
        )
        return StageOutcome(
            artefact=agreement,
            summary=f"Contract agreement checked: {agreement.counts.agreement_rate:.0%} implemented",
            notes={"errors": 0},
        )

    async def build(
        self, sources: dict[str, str], *, on_step: Callable[[str], None] | None = None
    ) -> StageOutcome[BuildReport]:
        self._called("build")
        if on_step is not None:
            on_step("install")
        report = BuildReport(
            toolchain="canned (no toolchain)",
            isolation="none: nothing was run, these outcomes are constants",
            steps=[
                BuildStepReport(
                    name="install", command="npm install", outcome="passed", duration_seconds=0.0
                ),
                BuildStepReport(
                    name="typecheck",
                    command="npm run typecheck",
                    outcome=self.typecheck_outcome,  # type: ignore[arg-type]
                    duration_seconds=0.0,
                ),
                BuildStepReport(
                    name="unit tests", command="npm test", outcome="passed", duration_seconds=0.0
                ),
            ],
        )
        return StageOutcome(
            artefact=report,
            summary="Build passed" if report.passed else "Build failed",
            notes={"passed": report.passed},
        )

    async def push(
        self,
        files: dict[str, str],
        *,
        name: str,
        token: str | None,
        message: str,
        branch: str | None = None,
    ) -> PushOutcome:
        self._called("push")
        self.pushed_branches.append(branch)
        self.pushed_paths.append(set(files))
        if self.push_raises is not None:
            raise self.push_raises
        if token is None or self.pushes_to is None:
            return PushOutcome(reason="not pushed: the project owner has no GitHub connection")
        return PushOutcome(pointer=self.pushes_to.model_copy(update={"branch": branch or ""}))

    async def land(
        self, pointer: RepositoryPointer, *, token: str | None, message: str
    ) -> LandOutcome:
        self._called("land")
        if token is None:
            return LandOutcome(reason="not pushed: the project owner has no GitHub connection")
        if self.land_refused:
            return LandOutcome(reason=self.land_refused)
        self.landed.append(pointer.commit_sha)
        return LandOutcome(commit_sha=pointer.commit_sha, how="fast-forward")


def _named(target: Any) -> str:
    """What a report calls the thing it measured, as C3's `_target_name` does,
    so a canned run of a sample is not reported as the generated app."""
    kind = getattr(target, "kind", "generated")
    if kind == "generated":
        return "the generated app"
    if kind == "sample":
        return f"the {getattr(target, 'path', '') or 'java'} sample"
    return f"a benchmark checkout at {getattr(target, 'path', '')}"


#: The canned suite's one test file, as test generation writes it.
CANNED_TEST_PATH = "apps/web/src/__tests__/generated.test.ts"
CANNED_TEST = """import { describe, expect, it } from "vitest";
import { history, total } from "../calc";

describe("US-1", () => {
  it("a person sees the result", () => {
    expect(total()).toBe(5);
  });

  it("a person sees the history", () => {
    expect(history()).toHaveLength(3);
  });
});
"""


def canned_repair(before: str, after: str) -> DiffSpan:
    """A repair to the canned test file, as C3 records one: a unified diff over it."""
    repaired = CANNED_TEST.replace(before, after)
    return DiffSpan(
        path=CANNED_TEST_PATH,
        diff="".join(
            difflib.unified_diff(
                CANNED_TEST.splitlines(keepends=True),
                repaired.splitlines(keepends=True),
                fromfile=f"a/{CANNED_TEST_PATH}",
                tofile=f"b/{CANNED_TEST_PATH}",
                n=3,
            )
        ),
    )


#: The accepted repair: the expected total moved on purpose.
HONEST_REPAIR = canned_repair("toBe(5)", "toBe(6)")
#: The refused one: it asserts nothing that could fail.
WEAKENED_REPAIR = canned_repair("toHaveLength(3)", "toBeTruthy()")


@dataclass
class CannedC3:
    """Every call, answered from constants.

    CannedC2's counterpart, for the same reason: the C3 spine tests are about
    the test version axis, the stage table, the gate and the report artefacts,
    and none of that is more true for having spent ten minutes running a real
    mutation pass.

    Two answers here are deliberately not empty. The generated report has its
    cases at `not-run`, because that is what a generated and unexecuted suite
    is; and the heal report carries one accepted repair and one refused one, so
    a test that reads it is reading the shape the guard actually produces
    rather than a happy path.
    """

    model: str = "canned (no model)"
    thinking: str | None = None
    #: The configured level, which a run uses where its account chose none.
    level: str = "off"
    #: The level each call came at, in order (None outside a run).
    levels: list[str | None] = field(default_factory=list)
    #: The stage names asked for, in order.
    calls: list[str] = field(default_factory=list)
    #: Stage names that should raise instead, for testing failure handling.
    fails: set[str] = field(default_factory=set)
    #: What the canned suite does when it runs. Green by default, because the
    #: test review refuses a generated app's red tests and most of these tests
    #: are about what comes after that review; a test about a red suite asks.
    outcome: str = "passed"
    #: What the canned test exercises. `api` makes it one of the tests every run
    #: writes again from the contract, which a kept repair may not change.
    case_kind: str = "unit"
    #: The canned test's id. A real one is its file's path and its name, slashes
    #: and all, which a route has to carry whole.
    case_id: str = "c1"
    #: The steps a run records, as the harness names them, and how each ended.
    run_steps: list[tuple[str, str]] = field(default_factory=list)
    #: The sprint plan each test generation was given, in order.
    sprints: list[SprintPlan] = field(default_factory=list)

    def _called(self, name: str) -> None:
        self.calls.append(name)
        # The level the run asked this call at, so a test can see it arrive.
        self.levels.append(RUN_THINKING.get())
        if name in self.fails:
            raise RuntimeError(f"the {name} stage was told to fail")

    def thinking_for(self, level: str) -> str | None:
        """What a real component's record would say at a level; silent if this one is."""
        return canned_thinking(self.thinking, level)

    @staticmethod
    def _suite(outcome: str, kind: str = "unit", case_id: str = "c1") -> TestSuite:
        return TestSuite(
            path=CANNED_TEST_PATH,
            framework="vitest",
            cases=[
                TestCase(
                    id=case_id,
                    name="a person sees the result",
                    outcome=outcome,
                    kind=kind,  # type: ignore[arg-type]
                    message="expected 5, received 6" if outcome == "failed" else "",
                    traces=TestTrace(story_id="US-1", criterion_id="AC-1-1"),
                )
            ],
        )

    @staticmethod
    def _stored(target: Any) -> str | None:
        """The canned test file as the run's workspace holds it, when it holds one."""
        try:
            return (Path(getattr(target, "path", "") or "") / CANNED_TEST_PATH).read_text()
        except OSError:
            return None

    def _as_run(self, target: Any) -> str:
        """What a runner reports for the canned test: skipped while its file sets it aside."""
        stored = self._stored(target) or ""
        set_aside = ('it.skip("a person sees the result"', 'it.todo("a person sees the result"')
        return "skipped" if any(one in stored for one in set_aside) else self.outcome

    def _report(
        self, outcome: str, *, mutation: bool = False, version: int = 1, target: Any = None
    ) -> TestReport:
        return TestReport(
            version=version,
            generated_at=store_now(),
            target=_named(target),
            isolation="a subprocess in a temporary directory",
            steps=[
                ToolStep(name=name, command=name, outcome=ended)  # type: ignore[arg-type]
                for name, ended in self.run_steps
            ],
            suites=[]
            if outcome == "none"
            else [self._suite(outcome, self.case_kind, self.case_id)],
            coverage=[CoverageEntry(module="apps/web", lines_covered=8, lines_total=10)],
            mutation=(
                MutationResult(
                    tool="canned",
                    scope=["apps/web/src/calc.ts"],
                    killed=["m1"],
                    survived=["m2"],
                )
                if mutation
                else None
            ),
            mutation_skipped_reason="" if mutation else "the canned client does not mutate",
        )

    async def generate_tests(
        self, target, sprint, contract, openapi, *, version: int
    ) -> TestFilesOutcome:
        """Files, plus a report whose cases have not run, because they have not."""
        self._called("test-generation")
        self.sprints.append(sprint)
        report = self._report("not-run", version=version)
        return TestFilesOutcome(
            # Carried when the workspace has it, as C3 carries a written file,
            # so a decision made in it outlives the run.
            files={CANNED_TEST_PATH: self._stored(target) or CANNED_TEST},
            manifest=[
                ManifestRow(
                    path=CANNED_TEST_PATH,
                    stage="test-generation",
                    arm="rule",
                    generator="rule",
                    implements=["US-1"],
                    summary="One case per acceptance criterion.",
                )
            ],
            summary="1 test generated from 1 acceptance criterion",
            notes={"report": report.model_dump(by_alias=True, mode="json"), "generated": 1},
        )

    async def run_tests(
        self, target, *, version: int, declared: TestReport | None = None
    ) -> StageOutcome[TestReport]:
        self._called("test-run")
        report = self._report(self._as_run(target), version=version, target=target)
        return StageOutcome(
            artefact=report,
            summary=f"{report.passed} passed, {report.failed} failed",
            notes={"failed": report.failed},
        )

    async def measure_quality(
        self, target, report, scope, *, version: int
    ) -> StageOutcome[TestReport]:
        self._called("test-quality")
        measured = self._report(self._as_run(target), mutation=True, version=version, target=target)
        return StageOutcome(
            artefact=measured,
            summary=f"mutation score {measured.mutation.score}%",
            notes={"mutants": measured.mutation.total},
        )

    async def heal(
        self,
        target,
        report,
        *,
        from_code_version,
        to_code_version,
        contract_diff=None,
        requirement_diff=None,
        changed_code=(),
        version,
    ) -> StageOutcome[HealReport]:
        """One accepted repair and one refusal, which is the real shape."""
        self._called("self-healing")
        #: The production code that changed, as the healing stage was handed it.
        self.healed_with_changes = list(changed_code)
        passing = [
            GuardCheck(name="test-code-only", passed=True, detail="only the test file changed"),
            GuardCheck(
                name="passes-unchanged-code", passed=True, detail="green against the old code"
            ),
            GuardCheck(name="kills-a-mutant", passed=True, detail="killed m1"),
        ]
        weakened = [
            GuardCheck(name="test-code-only", passed=True, detail="only the test file changed"),
            GuardCheck(name="passes-unchanged-code", passed=True, detail="green"),
            GuardCheck(name="kills-a-mutant", passed=False, detail="0 of 4 mutants died"),
        ]
        healed = HealReport(
            version=version,
            generated_at=store_now(),
            target="the generated app",
            from_code_version=from_code_version,
            to_code_version=to_code_version,
            attempts=[
                HealAttempt(
                    test_id=self.case_id,
                    test_name="a person sees the result",
                    suite_path=CANNED_TEST_PATH,
                    failure_message="expected 5, received 6",
                    classification="brittle",
                    classified_by="trace-changed",
                    diff=HONEST_REPAIR,
                    checks=passing,
                ),
                HealAttempt(
                    test_id="c2",
                    test_name="a person sees the history",
                    suite_path=CANNED_TEST_PATH,
                    failure_message="expected 3 rows, received 2",
                    classification="brittle",
                    classified_by="trace-changed",
                    diff=WEAKENED_REPAIR,
                    checks=weakened,
                    refusal_reason="kills-no-mutant",
                ),
            ],
        )
        return StageOutcome(
            artefact=healed,
            summary=f"{healed.healed} healed, {healed.refused} refused",
            notes={"healed": healed.healed, "refused": healed.refused},
        )

    async def decide_test(
        self, source: str, name: str, *, decision: str, by: str, reason: str, on: str
    ) -> str | None:
        """The edit C3 makes, because a canned one would be a second to keep in step."""
        from c3.generate.decisions import decide

        self._called("test-decision")
        return decide(source, name, decision, by=by, reason=reason, on=on)

    async def scan(self, target, *, version: int) -> StageOutcome[ValidationReport]:
        self._called("security-scan")
        report = ValidationReport(
            version=version,
            generated_at=store_now(),
            target="the generated app",
            tests=TestSummary(run=1, passed=0, failed=1, skipped=0, line_coverage=80.0),
        )
        return StageOutcome(artefact=report, summary="no findings", notes={"findings": 0})

    async def propose_remediation(self, target, report) -> StageOutcome[list]:
        self._called("remediation")
        return StageOutcome(artefact=[], summary="nothing to propose", notes={"proposals": 0})

    def targets(self) -> list[dict[str, str]]:
        self._called("targets")
        return [
            {
                "id": "generated",
                "label": "The generated application",
                "stack": "node",
                "detail": "The repository this project's code phase produced.",
            },
            # A sample as well, as the real component offers, so a test can choose
            # something other than the generated application.
            {
                "id": "sample:java",
                "label": "The Java sample",
                "stack": "java",
                "detail": "The seeded Spring sample the detection arms are measured on.",
            },
        ]

    async def reverify(
        self,
        before_validation,
        before_tests,
        after_validation,
        after_tests,
        *,
        before_run_id: str = "",
        after_run_id: str = "",
    ) -> StageOutcome[Reverification | None]:
        """The subtraction, over the two reports it was handed.

        Nothing is invented here: unlike every other method on this double, the
        inputs are real artefacts the caller read out of the database, so the
        honest canned answer is the arithmetic rather than a constant.

        What is missing is the refusal. The real component will not subtract
        two passes measured with different arms, over a different file count,
        or with a suite that did not run, and that judgement is tested where it
        lives. A test that needs the refusal path here substitutes a client
        that returns one; a test that needs the numbers gets the numbers.
        """
        self._called("reverify")
        result = Reverification(
            before=VerificationSnapshot(
                open_findings=before_validation.open_findings,
                tests_passed=before_tests.passed,
                tests_failed=before_tests.failed,
                mutation_score=before_tests.mutation.score if before_tests.mutation else None,
            ),
            after=VerificationSnapshot(
                open_findings=after_validation.open_findings,
                tests_passed=after_tests.passed,
                tests_failed=after_tests.failed,
                mutation_score=after_tests.mutation.score if after_tests.mutation else None,
            ),
            before_run_id=before_run_id,
            after_run_id=after_run_id,
        )
        return StageOutcome(
            artefact=result,
            summary=(
                f"{result.findings_closed} closed, {result.tests_broken} broken"
                if not result.worsened
                else f"worse after the patch: {result.tests_broken} tests broke"
            ),
            notes={"comparable": True, "worsened": result.worsened},
        )
