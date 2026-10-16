"""Wiring and compiling the testing phase's graph.

Six stages in the order a reader watches them, then the gate. Sequential for
C1's reason: a fan out would save wall clock and cost three connections per
run, an interleaved audit log and three writers on one checkpoint in one
superstep.

The order carries two arguments. Healing sits after execution because it reads
the failures execution produced, and before the security work because it is
about the run that just happened rather than about the code in general. And
quality sits between them rather than at the end, because the honesty guard
needs mutants in the region a test exercises, and the stage that knows how to
make mutants should have run before the stage that needs them.

Named `testing_graph` rather than `test_graph` for the reason `testing_nodes`
is not `test_nodes`: pytest would collect it.
"""

from itertools import pairwise

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from psycopg_pool import AsyncConnectionPool

from ..clients.c3 import C3Client
from .state import C3RunState
from .testing_nodes import (
    make_remediation,
    make_security_scan,
    make_self_healing,
    make_test_generation,
    make_test_quality,
    make_test_run,
    test_gate,
)

#: Node name to stage id. The two differ because a node name cannot hold a
#: hyphen in a LangGraph edge as readably as an identifier does, and because
#: the stage id is the contract's vocabulary and has to stay exactly that.
STAGE_NODES = {
    "test-generation": make_test_generation,
    "test-run": make_test_run,
    "test-quality": make_test_quality,
    "self-healing": make_self_healing,
    "security-scan": make_security_scan,
    "remediation": make_remediation,
}

#: The order stages run in, as node names.
NODE_ORDER = (
    "test_generation",
    "test_run",
    "test_quality",
    "self_healing",
    "security_scan",
    "remediation",
)

_NODE_NAME = {stage_id: stage_id.replace("-", "_") for stage_id in STAGE_NODES}


def build_testing_graph(pool: AsyncConnectionPool, checkpointer: BaseCheckpointSaver, c3: C3Client):
    """Six stages, then the test review gate."""
    graph = StateGraph(C3RunState)

    for stage_id, factory in STAGE_NODES.items():
        graph.add_node(_NODE_NAME[stage_id], factory(pool, c3))
    graph.add_node("test_gate", test_gate)

    graph.add_edge(START, NODE_ORDER[0])
    for earlier, later in pairwise(NODE_ORDER):
        graph.add_edge(earlier, later)
    graph.add_edge(NODE_ORDER[-1], "test_gate")
    # test_gate returns a Command, so it routes itself: to END on approval, or
    # back to the first stage when changes are requested.
    graph.add_edge("test_gate", END)

    return graph.compile(checkpointer=checkpointer)
