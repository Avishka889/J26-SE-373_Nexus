"""Wiring and compiling the code phase's graph.

Seven stages in the order a reader watches them, then the gate. Sequential
for C1's reason: a fan out would save wall clock and cost three connections
per run, an interleaved audit log and three writers on one checkpoint in one
superstep. The agreement stage is placed after both code stages deliberately,
so a failure in either yields an honest report about what is missing rather
than no report at all.
"""

from itertools import pairwise

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from psycopg_pool import AsyncConnectionPool

from ..clients.c2 import C2Client
from .code_nodes import (
    code_gate,
    make_api_contract,
    make_backend_code,
    make_build,
    make_contract_agreement,
    make_frontend_code,
    make_land,
    make_sprint_scope,
    make_tech_stack,
)
from .state import C2RunState

#: Node name to stage id. The two differ because a node name cannot hold a
#: hyphen in a LangGraph edge as readably as an identifier does, and because
#: the stage id is the contract's vocabulary and has to stay exactly that.
STAGE_NODES = {
    "sprint-scope": make_sprint_scope,
    "tech-stack": make_tech_stack,
    "api-contract": make_api_contract,
    "frontend-code": make_frontend_code,
    "backend-code": make_backend_code,
    "contract-agreement": make_contract_agreement,
    "build": make_build,
}

#: The order stages run in, as node names.
NODE_ORDER = (
    "sprint_scope",
    "tech_stack",
    "api_contract",
    "frontend_code",
    "backend_code",
    "contract_agreement",
    "build",
)

_NODE_NAME = {stage_id: stage_id.replace("-", "_") for stage_id in STAGE_NODES}


def build_code_graph(pool: AsyncConnectionPool, checkpointer: BaseCheckpointSaver, c2: C2Client):
    """Seven stages, then the code review gate."""
    graph = StateGraph(C2RunState)

    for stage_id, factory in STAGE_NODES.items():
        graph.add_node(_NODE_NAME[stage_id], factory(pool, c2))
    graph.add_node("code_gate", code_gate)
    graph.add_node("code_land", make_land(pool, c2))

    graph.add_edge(START, NODE_ORDER[0])
    for earlier, later in pairwise(NODE_ORDER):
        graph.add_edge(earlier, later)
    graph.add_edge(NODE_ORDER[-1], "code_gate")
    # code_gate returns a Command, so it routes itself: to the landing on
    # approval, or back to the first stage when changes are requested.
    graph.add_edge("code_gate", END)
    graph.add_edge("code_land", END)

    return graph.compile(checkpointer=checkpointer)
