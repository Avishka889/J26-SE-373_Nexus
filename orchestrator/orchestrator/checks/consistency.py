"""The six checks that compare artefacts against each other.

These live in the orchestrator, and where they live is the design decision worth
explaining. Every rule catalogue inside Component 1 reads one artefact and asks
whether it holds together on its own, because that is all a component ever has:
the graph is built without a sprint plan, the wireframes are drawn before one
exists. The orchestrator is the only thing that ever holds all six at once, so it
is the only place these questions can be asked.

That also makes them read-time derivations rather than a generation step. A
statement about how six artefacts relate stops being true the moment one of them
is regenerated, and a stored copy would go stale exactly when it mattered.

Half of what they catch is created by the pipeline rather than by a model. A
change note makes a new requirements version, some stages regenerate and others
do not, and an artefact that was correct against version 2 ends up beside a graph
built from version 3. Every artefact passed its own rules when it was made. Only
a comparison finds it.

Severity is advice, not a veto. An error means a defect worth fixing before
approving and a warning means worth knowing, and neither blocks the gate:
approving is a human decision, and a check that refused would be the tool
overruling the person it exists to inform.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from sdlc_contracts import (
    NODE_TOKEN,
    ArchitectureGraph,
    ConsistencyFinding,
    ParsedRequirement,
    SprintPlan,
    UmlArtefact,
    WireframesArtefact,
)

from .coverage import stories_of


@dataclass(frozen=True)
class Design:
    """Everything generated, as one thing to compare against itself."""

    requirements: list[ParsedRequirement] = field(default_factory=list)
    graph: ArchitectureGraph = field(default_factory=ArchitectureGraph)
    uml: UmlArtefact = field(default_factory=UmlArtefact)
    wireframes: WireframesArtefact = field(default_factory=WireframesArtefact)
    sprint: SprintPlan | None = None


@dataclass(frozen=True)
class Check:
    """What one rule found, and how much it looked at.

    The count is what makes the rate meaningful. Findings alone say how many
    things are wrong; findings over subjects says how much was checked to find
    them, which is the only version comparable between two runs over projects of
    different sizes.
    """

    findings: tuple[ConsistencyFinding, ...] = field(default=())
    subjects: int = 0


@dataclass(frozen=True)
class ConsistencyReport:
    findings: tuple[ConsistencyFinding, ...] = field(default=())
    subjects: int = 0

    @property
    def errors(self) -> tuple[ConsistencyFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> tuple[ConsistencyFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "warning")

    @property
    def rate(self) -> float | None:
        """The share of checked things that agreed with the rest of the design.

        None when nothing was checked, which is the honest answer and not 1.0. A
        project with no sprint plan and no diagrams has not achieved perfect
        consistency: there was nothing to be consistent about, and a hundred
        percent would put the emptiest run at the top of the table.
        """
        if self.subjects == 0:
            return None
        return round(1 - len(self.findings) / self.subjects, 4)

    def rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted({finding.rule_id for finding in self.findings}))


Rule = Callable[[Design], Check]


def check_design(design: Design) -> ConsistencyReport:
    """Run every cross artefact rule, in catalogue order."""
    findings: list[ConsistencyFinding] = []
    subjects = 0
    for rule in ALL_RULES:
        result = rule(design)
        findings.extend(result.findings)
        subjects += result.subjects
    return ConsistencyReport(findings=tuple(findings), subjects=subjects)


def story_has_a_screen(design: Design) -> Check:
    """1. Every story has somewhere a user would see it happen.

    A warning. Some stories are genuinely invisible, like a nightly
    reconciliation, and refusing a design over one would be wrong. A reader
    decides whether this one matters.
    """
    stories = stories_of(design.sprint)
    return Check(
        findings=tuple(
            ConsistencyFinding(
                ruleId="story-has-a-screen",
                severity="warning",
                reason=(
                    f'{story.id} "{story.title}" has no screen in any journey, so there is '
                    f"nothing showing how a user would do it."
                ),
                traces=list(story.traces),
                stageId="wireframes",
            )
            for story in stories
            if not any(story.id in flow.covers_story_ids for flow in design.wireframes.flows)
        ),
        subjects=len(stories),
    )


def must_is_in_the_sprint(design: Design) -> Check:
    """2. Every must-have is planned for this sprint, not the next one.

    Different from asking whether a requirement has a story anywhere, which the
    sprint plan checks itself. This asks whether it has one that is actually
    being done, and a must-have sitting in the backlog is the quieter version of
    the same problem: the plan looks complete because the story exists.
    """
    if design.sprint is None:
        return Check()
    musts = [r for r in design.requirements if r.priority == "must"]
    planned = {trace for story in design.sprint.proposed for trace in story.traces}
    backlogged = {trace for story in design.sprint.backlog for trace in story.traces}

    findings: list[ConsistencyFinding] = []
    for requirement in musts:
        if requirement.id in planned:
            continue
        where = "is only in the backlog" if requirement.id in backlogged else "has no story at all"
        findings.append(
            ConsistencyFinding(
                ruleId="must-is-in-the-sprint",
                severity="warning",
                reason=(
                    f"{requirement.id} is a must-have and {where}, so this sprint does not "
                    f"deliver it: {requirement.text}"
                ),
                traces=[requirement.id],
                stageId="sprint-plan",
            )
        )
    return Check(findings=tuple(findings), subjects=len(musts))


def use_case_names_a_real_story(design: Design) -> Check:
    """3. A use case claiming to realise a story names one that exists.

    An error: it is a reference to nothing, and a reader following it lands
    nowhere.
    """
    known = {story.id for story in stories_of(design.sprint)}
    claiming = [use_case for use_case in design.uml.use_cases if use_case.story_id]
    return Check(
        findings=tuple(
            ConsistencyFinding(
                ruleId="use-case-names-a-real-story",
                severity="error",
                reason=(
                    f"The interaction '{use_case.name}' says it realises {use_case.story_id}, "
                    f"which is not a story in this plan."
                ),
                traces=list(use_case.traces),
                stageId="uml-diagrams",
            )
            for use_case in claiming
            if use_case.story_id not in known
        ),
        subjects=len(claiming),
    )


def diagram_participants_exist(design: Design) -> Check:
    """4. Every lifeline in a sequence diagram is still a node in the graph.

    An error, and the one most likely to come from regeneration rather than from
    a model. Participants were checked against the graph when the diagram was
    written; rebuild the graph without rebuilding the diagram and a step points
    at a node that is gone.
    """
    known = {node.id for node in design.graph.nodes}
    findings: list[ConsistencyFinding] = []
    for use_case in design.uml.use_cases:
        missing = sorted(
            {
                participant
                for step in use_case.steps
                for participant in (step.from_id, step.to_id)
                if participant not in known
            }
        )
        if missing:
            findings.append(
                ConsistencyFinding(
                    ruleId="diagram-participants-exist",
                    severity="error",
                    reason=(
                        f"The interaction '{use_case.name}' involves {', '.join(missing)}, "
                        f"which the architecture graph no longer has."
                    ),
                    traces=list(use_case.traces),
                    stageId="uml-diagrams",
                )
            )
    return Check(
        findings=tuple(findings),
        subjects=sum(len(use_case.steps) for use_case in design.uml.use_cases),
    )


def diagram_tokens_resolve(design: Design) -> Check:
    """5. Every `{nodeId}` in a diagram message still names a node.

    An error, and a visible one: an unresolved token renders as the literal
    braces, so the reader sees `{e9}` in the middle of a sentence. Separate from
    the rule above because a diagram can have every participant right and still
    mention a node that has been deleted.
    """
    known = {node.id for node in design.graph.nodes}
    findings: list[ConsistencyFinding] = []
    for use_case in design.uml.use_cases:
        dangling = sorted(
            {
                match.group(1)
                for step in use_case.steps
                for match in NODE_TOKEN.finditer(step.message)
                if match.group(1) not in known
            }
        )
        if dangling:
            findings.append(
                ConsistencyFinding(
                    ruleId="diagram-tokens-resolve",
                    severity="error",
                    reason=(
                        f"The interaction '{use_case.name}' mentions "
                        f"{', '.join('{' + t + '}' for t in dangling)}, which names nothing in "
                        f"the graph, so the reader would see the braces."
                    ),
                    traces=list(use_case.traces),
                    stageId="uml-diagrams",
                )
            )
    return Check(
        findings=tuple(findings),
        subjects=sum(len(use_case.steps) for use_case in design.uml.use_cases),
    )


def _traced_things(design: Design) -> list[tuple[str, tuple[str, ...], str]]:
    """(what it is, what it traces to, where to fix it) for everything that claims."""
    things: list[tuple[str, tuple[str, ...], str]] = [
        (f"The node '{node.label}'", tuple(node.traces), "architecture-graph")
        for node in design.graph.nodes
    ]
    things += [
        (f"The journey '{flow.name}'", tuple(flow.traces), "wireframes")
        for flow in design.wireframes.flows
    ]
    things += [
        (f"The interaction '{use_case.name}'", tuple(use_case.traces), "uml-diagrams")
        for use_case in design.uml.use_cases
    ]
    things += [
        (f"The story '{story.title}'", tuple(story.traces), "sprint-plan")
        for story in stories_of(design.sprint)
    ]
    return things


def traces_name_current_requirements(design: Design) -> Check:
    """6. Nothing traces to a requirement that has since been removed.

    An error, and the staleness check for traceability itself. Every artefact
    verified its traces against the requirements it was generated from. A later
    version can drop one, and an artefact that did not regenerate keeps pointing
    at it: the trace chip still renders and links to a requirement that is not on
    the page.
    """
    known = {requirement.id for requirement in design.requirements}
    things = _traced_things(design)

    findings: list[ConsistencyFinding] = []
    for what, traces, stage in things:
        gone = sorted(trace for trace in traces if trace not in known)
        if gone:
            findings.append(
                ConsistencyFinding(
                    ruleId="traces-name-current-requirements",
                    severity="error",
                    reason=(
                        f"{what} traces to {', '.join(gone)}, which "
                        f"{'is' if len(gone) == 1 else 'are'} no longer a requirement of this "
                        f"project."
                    ),
                    traces=gone,
                    stageId=stage,  # type: ignore[arg-type]
                )
            )
    return Check(findings=tuple(findings), subjects=len(things))


#: All six, in the order they are reported. Coverage first, because it is the one
#: a reader at the gate is most likely to act on.
ALL_RULES: tuple[Rule, ...] = (
    story_has_a_screen,
    must_is_in_the_sprint,
    use_case_names_a_real_story,
    diagram_participants_exist,
    diagram_tokens_resolve,
    traces_name_current_requirements,
)

#: The names, for the evaluation and for the test that pins the catalogue.
RULE_IDS = (
    "story-has-a-screen",
    "must-is-in-the-sprint",
    "use-case-names-a-real-story",
    "diagram-participants-exist",
    "diagram-tokens-resolve",
    "traces-name-current-requirements",
)
