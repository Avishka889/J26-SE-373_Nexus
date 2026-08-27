"""The component registry: what exists, and how a run of it is driven.

`runs.component` was a free string the supervisor read for one audit line, and
everything else was hardwired to C1: one graph, one client, one stage table,
one gate kind. A `component="c2"` run would have executed the C1 pipeline.
This module is the fix: one entry per component, and the supervisor, the
lifespan and the retry route all dispatch through it.

Nothing in `graph/nodes.py` may import this module (the registry names node
factories, so the dependency points this way), and the specs hold callables
rather than imports where a cycle threatens.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sdlc_contracts import (
    CODE_ARTEFACT_KINDS,
    CODE_GENERATING_STAGE_IDS,
    CODE_STAGE_IDS,
    DEPLOY_ARTEFACT_KINDS,
    DEPLOY_GENERATING_STAGE_IDS,
    DEPLOY_RUNNER_STAGE_IDS,
    DEPLOY_STAGE_IDS,
    DESIGN_STAGE_IDS,
    GENERATING_STAGE_IDS,
    TEST_ARTEFACT_KINDS,
    TEST_GENERATING_STAGE_IDS,
    TEST_STAGE_IDS,
)

from .config import Settings
from .errors import DomainError

#: A stage node factory: (pool, client) -> the async node the graph runs.
NodeFactory = Callable[..., Any]


@dataclass(frozen=True)
class ComponentSpec:
    #: `runs.component`, and the registry key.
    key: str
    #: Prose for audit lines and errors: "requirements and design".
    label: str
    #: The audit category this component's automated writes carry.
    audit_category: str
    #: Every stage_states row this component owns, gate included.
    stage_ids: tuple[str, ...]
    #: Flipped to generating when a run starts.
    generating_stage_ids: tuple[str, ...]
    #: The artefact kinds this component writes.
    artefact_kinds: tuple[str, ...]
    #: The gate kind its interrupt payload carries and its gate rows store.
    gate_kind: str
    #: The stage that renders the gate.
    gate_stage_id: str
    #: Whether a first run may retitle the project. C1 only: it is the run
    #: that reads the raw brief.
    renames_project: bool
    #: How long a running row may go silent before the poller reclaims it.
    #: Per component, because a code generation stage is legitimately slower
    #: than a design stage.
    stale_after_seconds: int
    #: (pool, checkpointer, client) -> compiled graph.
    build_graph: Callable[..., Any]
    #: Settings -> the component client. May mutate os.environ to place the
    #: provider key where the model client looks, exactly as the lifespan did.
    make_client: Callable[[Settings], Any]
    #: () -> {stage_id: node factory}, for single stage retries. A callable so
    #: the import happens at dispatch time rather than at registry import.
    stage_nodes: Callable[[], Mapping[str, NodeFactory]]
    #: (run row, project row, notes) -> the graph's initial state.
    initial_state: Callable[[Mapping[str, Any], Mapping[str, Any], list[str]], dict[str, Any]]
    #: (pool, initial state) -> the state one stage needs when it is retried
    #: alone: what a full run's earlier stages would have put there. None where
    #: the initial state is already enough.
    retry_state: Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None


# ------------------------------------------------------------------------- c1


def _c1_build_graph(pool: Any, checkpointer: Any, client: Any) -> Any:
    from .graph.build import build_graph

    return build_graph(pool, checkpointer, client)


def _c1_make_client(settings: Settings) -> Any:
    from .clients.c1 import make_c1_client
    from .main import place_provider_key

    if settings.c1_mode == "inprocess":
        place_provider_key(settings, settings.c1_model)
    return make_c1_client(
        settings.c1_mode,
        model=settings.c1_model,
        base_url=settings.c1_base_url,
        thinking=settings.c1_thinking,
    )


def _c1_stage_nodes() -> Mapping[str, NodeFactory]:
    from .graph.build import STAGE_NODES

    return STAGE_NODES


def _c1_initial_state(
    run: Mapping[str, Any], project: Mapping[str, Any], notes: list[str]
) -> dict[str, Any]:
    return {
        "project_id": run["project_id"],
        "run_id": str(run["id"]),
        "requirements_version": run["requirements_version"],
        "input_text": project["requirement_text"],
        # Read from the version table, not passed in by whoever started the
        # run, so a note cannot be lost by starting a run the long way round.
        "revision_notes": notes,
        "attempt": 0,
    }


#: The design run's second pause, after Requirements Analysis, while the design
#: waits on the questions it asked. Not a review: "approved" continues with the
#: assumptions it stated, and "changes" analyses the requirements again with the
#: answers. Its own kind, so nothing that reads the review's gate reads this one.
QUESTIONS_GATE_KIND = "c1-questions"

C1_SPEC = ComponentSpec(
    key="c1",
    label="requirements and design",
    audit_category="design",
    stage_ids=tuple(DESIGN_STAGE_IDS),
    generating_stage_ids=tuple(GENERATING_STAGE_IDS),
    artefact_kinds=(
        "requirements",
        "architecture-graph",
        "architecture-recommendation",
        "uml-diagrams",
        "wireframes",
        "sprint-plan",
    ),
    gate_kind="c1-design-review",
    gate_stage_id="design-review",
    renames_project=True,
    stale_after_seconds=90,
    build_graph=_c1_build_graph,
    make_client=_c1_make_client,
    stage_nodes=_c1_stage_nodes,
    initial_state=_c1_initial_state,
)


# ------------------------------------------------------------------------- c2


class UnconfiguredComponent:
    """A component this orchestrator cannot call, that says so when called.

    Every registered graph has to compile, even when its provider key is
    missing, because a gate opened before the key went missing still has to be
    resumable: settling it runs the gate node and nothing else, so a client
    that only fails on a stage call is enough to approve code that already
    exists. Refusing to start instead would strand the decision.
    """

    def __init__(self, key: str, reason: str) -> None:
        self._key = key
        self.model = f"not configured: {reason}"
        self._reason = reason

    def __getattr__(self, name: str):
        async def refuse(*_args: Any, **_kwargs: Any):
            raise RuntimeError(
                f"this orchestrator cannot run {self._key}: {self._reason}. "
                f"The stage {name} needs it; a pending gate can still be decided."
            )

        return refuse


def _c2_build_graph(pool: Any, checkpointer: Any, client: Any) -> Any:
    from .graph.code_graph import build_code_graph

    return build_code_graph(pool, checkpointer, client)


def _c2_make_client(settings: Settings) -> Any:
    from .clients.c2 import make_c2_client
    from .main import place_provider_key

    try:
        if settings.c2_mode == "inprocess":
            place_provider_key(settings, settings.c2_model)
        return make_c2_client(
            settings.c2_mode,
            model=settings.c2_model,
            base_url=settings.c2_base_url,
            thinking=settings.c2_thinking,
        )
    except Exception as error:
        # C1 refuses to start without its key, because an orchestrator that
        # cannot analyse requirements has nothing to do. This one carries on:
        # every design project still works, and a code gate stays decidable.
        return UnconfiguredComponent("c2", str(error))


def _c2_stage_nodes() -> Mapping[str, NodeFactory]:
    from .graph.code_graph import STAGE_NODES

    return STAGE_NODES


def _c2_initial_state(
    run: Mapping[str, Any], project: Mapping[str, Any], notes: list[str]
) -> dict[str, Any]:
    """Two versions and nothing else.

    `requirements_version` is the code version this run produces, because that
    column is "the version on this component's own axis". `source_version` is
    the design version it reads, pinned when the run was created.
    """
    return {
        "project_id": run["project_id"],
        "run_id": str(run["id"]),
        "code_version": run["requirements_version"],
        "design_version": run.get("source_version") or 0,
        "attempt": 0,
    }


C2_SPEC = ComponentSpec(
    key="c2",
    label="wireframe to code",
    audit_category="code",
    stage_ids=tuple(CODE_STAGE_IDS),
    generating_stage_ids=tuple(CODE_GENERATING_STAGE_IDS),
    artefact_kinds=tuple(CODE_ARTEFACT_KINDS),
    gate_kind="c2-code-review",
    gate_stage_id="code-review",
    #: The design run reads the brief and may retitle; a code run never does.
    renames_project=False,
    #: Ten minutes, not C1's ninety seconds: one build step alone is capped at
    #: seven, and a poller that reclaimed a run mid install would run it twice.
    stale_after_seconds=600,
    build_graph=_c2_build_graph,
    make_client=_c2_make_client,
    stage_nodes=_c2_stage_nodes,
    initial_state=_c2_initial_state,
)


# ------------------------------------------------------------------------- c3


def _c3_build_graph(pool: Any, checkpointer: Any, client: Any) -> Any:
    from .graph.testing_graph import build_testing_graph

    return build_testing_graph(pool, checkpointer, client)


def _c3_make_client(settings: Settings) -> Any:
    from .clients.c3 import make_c3_client
    from .main import place_provider_key

    try:
        if settings.c3_mode == "inprocess":
            place_provider_key(settings, settings.c3_model)
        return make_c3_client(
            settings.c3_mode,
            model=settings.c3_model,
            base_url=settings.c3_base_url,
            arms=settings.c3_detection_arms,
            trained_model_dir=settings.c3_trained_model_dir,
            thinking=settings.c3_thinking,
        )
    except Exception as error:
        # C2's stance, for C2's reason: every design and code project still
        # works without a testing lane configured, and a testing gate that is
        # already open stays decidable.
        return UnconfiguredComponent("c3", str(error))


def _c3_stage_nodes() -> Mapping[str, NodeFactory]:
    from .graph.testing_graph import STAGE_NODES

    return STAGE_NODES


def _c3_initial_state(
    run: Mapping[str, Any], project: Mapping[str, Any], notes: list[str]
) -> dict[str, Any]:
    """Two versions and nothing else, as C2 has.

    `requirements_version` is the test version this run produces, because that
    column is "the version on this component's own axis". `source_version` is
    the code version it tests, pinned when the run was created.
    """
    return {
        "project_id": run["project_id"],
        "run_id": str(run["id"]),
        "test_version": run["requirements_version"],
        "code_version": run.get("source_version") or 0,
        "attempt": 0,
    }


C3_SPEC = ComponentSpec(
    key="c3",
    label="testing and security",
    audit_category="testing",
    stage_ids=tuple(TEST_STAGE_IDS),
    generating_stage_ids=tuple(TEST_GENERATING_STAGE_IDS),
    artefact_kinds=tuple(TEST_ARTEFACT_KINDS),
    gate_kind="c3-test-review",
    gate_stage_id="test-review",
    renames_project=False,
    #: Twenty minutes. Longer than C2's ten, and for a sharper reason: a cold
    #: Maven wrapper downloads a toolchain before the first test runs, and a
    #: mutation pass runs the suite once per mutant. A poller that reclaimed a
    #: run mid mutation would start the whole phase again.
    stale_after_seconds=1200,
    build_graph=_c3_build_graph,
    make_client=_c3_make_client,
    stage_nodes=_c3_stage_nodes,
    initial_state=_c3_initial_state,
)


# ------------------------------------------------------------------------- c4


def _c4_build_graph(pool: Any, checkpointer: Any, client: Any) -> Any:
    from .graph.deployment_graph import build_deployment_graph

    return build_deployment_graph(pool, checkpointer, client)


def _c4_make_client(settings: Settings) -> Any:
    from .clients.c4 import make_c4_client
    from .main import place_provider_key

    try:
        if settings.c4_mode == "inprocess":
            place_provider_key(settings, settings.c4_model)
        return make_c4_client(
            settings.c4_mode,
            model=settings.c4_model,
            base_url=settings.c4_base_url,
            cache_dir=settings.c4_cache_dir,
            thinking=settings.c4_thinking,
        )
    except Exception as error:
        # C2's and C3's stance: every earlier phase still works without a
        # deployment lane, and a deployment gate that is already open stays
        # decidable.
        return UnconfiguredComponent("c4", str(error))


def _c4_stage_nodes() -> Mapping[str, NodeFactory]:
    from .graph.deployment_graph import STAGE_NODES

    return STAGE_NODES


def _c4_initial_state(
    run: Mapping[str, Any], project: Mapping[str, Any], notes: list[str]
) -> dict[str, Any]:
    """The deploy version and the approved test version, and nothing else.

    `requirements_version` is the deploy version this run produces, as the column
    is "the version on this component's own axis". `source_version` is the test
    version whose approval the run starts from. The code version is looked up by
    the first stage, from the testing run that produced that test version.
    """
    return {
        "project_id": run["project_id"],
        "run_id": str(run["id"]),
        "deploy_version": run["requirements_version"],
        "test_version": run.get("source_version") or 0,
        "attempt": 0,
    }


async def _c4_retry_state(pool: Any, state: dict[str, Any]) -> dict[str, Any]:
    """The code version, which a full run's first stage looks up and pins.

    A stage retried alone never ran that stage, so every one that reads the
    code crashed with a missing key: Staging Verification, the way past a
    candidate that did not verify, could be asked for and never ran. The same
    lookup, from the testing run that produced the approved test version.
    """
    from .db import store

    async with pool.connection() as conn:
        tested = await store.run_for_version(
            conn, state["project_id"], component="c3", version=state["test_version"]
        )
    code_version = int((tested or {}).get("source_version") or 0)
    if not code_version:
        raise RuntimeError(
            f"no testing run produced test version {state['test_version']}, "
            "so the code it tested is unknown"
        )
    return {**state, "code_version": code_version}


C4_SPEC = ComponentSpec(
    key="c4",
    label="deployment and dependency evolution",
    audit_category="deployment",
    #: Not the runner stages. A release and its monitoring outlive a run, and a
    #: failed run resets its generating stages: a release in flight must not be
    #: one of them.
    stage_ids=tuple(stage for stage in DEPLOY_STAGE_IDS if stage not in DEPLOY_RUNNER_STAGE_IDS),
    generating_stage_ids=tuple(DEPLOY_GENERATING_STAGE_IDS),
    artefact_kinds=tuple(DEPLOY_ARTEFACT_KINDS),
    gate_kind="c4-deploy-review",
    gate_stage_id="deployment-review",
    renames_project=False,
    #: Thirty minutes: a cold install, an image build and the suite, on this
    #: machine, before a poller may decide the run was abandoned.
    stale_after_seconds=1800,
    build_graph=_c4_build_graph,
    make_client=_c4_make_client,
    stage_nodes=_c4_stage_nodes,
    initial_state=_c4_initial_state,
    retry_state=_c4_retry_state,
)


COMPONENTS: dict[str, ComponentSpec] = {
    "c1": C1_SPEC,
    "c2": C2_SPEC,
    "c3": C3_SPEC,
    "c4": C4_SPEC,
}


def where_it_stopped(
    spec: ComponentSpec, statuses: Mapping[str, str], not_reached: list[str]
) -> str:
    """The stage a stopped run's message belongs to, so its phase shows it.

    The last stage that failed: a full run's start resets every stage it
    generates, so a failure here is this run's, and the stage that stopped it
    fails after any leaf before it. Stage order is not running order (the domain
    model is a view over the graph that comes after it), which is why the
    unreached stages are only the fallback, for a run that stopped between
    stages; with neither, the review it never reached.
    """
    order = list(spec.stage_ids)
    failed = [stage for stage in order if statuses.get(stage) == "failed"]
    if failed:
        return failed[-1]
    unreached = [stage for stage in order if stage in not_reached]
    return unreached[0] if unreached else spec.gate_stage_id


def spec_for(key: str) -> ComponentSpec:
    spec = COMPONENTS.get(key)
    if spec is None:
        known = ", ".join(sorted(COMPONENTS))
        raise DomainError(
            f"'{key}' is not a component this orchestrator runs. Components: {known}.",
            status_code=409,
        )
    return spec


def spec_for_gate_kind(kind: str) -> ComponentSpec:
    for spec in COMPONENTS.values():
        if spec.gate_kind == kind:
            return spec
    known = ", ".join(sorted(spec.gate_kind for spec in COMPONENTS.values()))
    raise DomainError(
        f"'{kind}' is not a gate kind this orchestrator opens. Gate kinds: {known}.",
        status_code=409,
    )


def stale_windows() -> dict[str, int]:
    """Per component stale windows, for the poller's reclaim query."""
    return {spec.key: spec.stale_after_seconds for spec in COMPONENTS.values()}
