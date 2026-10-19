"""Wiring and compiling the deployment phase's graph.

Seven stages in the order their inputs exist, then the gate. Sequential for
C1's reason. The release notes are read before the code is searched, because the
claims they yield name the symbols the search looks for; both come before the
risk assessment, which combines their votes; and the pipeline and the staging
build come after the risk is fixed, so nothing seen while building a candidate
can leak back into the level it was built on.

The phase's last two stages, the release and its monitoring, are not nodes.
They outlive any run, so the orchestrator's saga runner and monitor carry them
out after the gate.

Named `deployment_graph` rather than `deploy_graph` for no pytest reason this
time, but to match the phase's own name everywhere else.
"""

from itertools import pairwise

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from psycopg_pool import AsyncConnectionPool

from ..clients.c4 import C4Client
from .deployment_nodes import (
    deployment_review,
    make_changelog_analysis,
    make_dependency_updates,
    make_impact_analysis,
    make_pipeline_generation,
    make_release_handover,
    make_release_route,
    make_risk_assessment,
    make_rollback_planning,
    make_staging_verification,
)
from .state import C4RunState

STAGE_NODES = {
    "dependency-updates": make_dependency_updates,
    "changelog-analysis": make_changelog_analysis,
    "impact-analysis": make_impact_analysis,
    "risk-assessment": make_risk_assessment,
    "pipeline-generation": make_pipeline_generation,
    "staging-verification": make_staging_verification,
    "rollback-planning": make_rollback_planning,
}

NODE_ORDER = tuple(stage_id.replace("-", "_") for stage_id in STAGE_NODES)

_NODE_NAME = {stage_id: stage_id.replace("-", "_") for stage_id in STAGE_NODES}


def build_deployment_graph(
    pool: AsyncConnectionPool, checkpointer: BaseCheckpointSaver, c4: C4Client
):
    """Seven stages, then the deployment review gate."""
    graph = StateGraph(C4RunState)

    for stage_id, factory in STAGE_NODES.items():
        graph.add_node(_NODE_NAME[stage_id], factory(pool, c4))
    graph.add_node("deployment_review", deployment_review)

    graph.add_edge(START, NODE_ORDER[0])
    for earlier, later in pairwise(NODE_ORDER):
        graph.add_edge(earlier, later)
    graph.add_node("release_route", make_release_route(pool))
    graph.add_node("release_handover", make_release_handover(pool))
    # After the stages the route decides: the review, a release the policy
    # allows, or no further when there is no candidate to release.
    graph.add_edge(NODE_ORDER[-1], "release_route")
    # The gate returns a Command, so it routes itself: to the handover on
    # approval, or back to the first stage when changes are requested.
    graph.add_edge("release_handover", END)

    return graph.compile(checkpointer=checkpointer)
