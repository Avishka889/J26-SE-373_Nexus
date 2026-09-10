"""Wiring and compiling the graph.

One graph, compiled once per process, with the checkpointer attached. Without a
checkpointer `interrupt()` does not work at all: it relies on persisted state to
have somewhere to pause.

The three leaf stages run one after another rather than in parallel, and that is
a change from the original sketch. A fan out would save wall clock, and it would
also mean three nodes writing to one checkpoint in the same superstep, three
concurrent connections from the pool per run, and an interleaved audit log. The
saving is real but it is not what makes this demo work: the stages already report
one at a time, so a reader sees progress either way. Sequential until there is a
measured reason, and the reason will be a number rather than a preference.
"""

from itertools import pairwise

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from psycopg_pool import AsyncConnectionPool

from ..clients.c1 import C1Client
from .nodes import (
    design_gate,
    make_build_graph,
    make_draw_wireframes,
    make_parse_requirements,
    make_plan_sprint,
    make_recommend,
    make_write_uml,
    questions_gate,
)
from .state import C1RunState

#: The order stages run in, and the order a reader watches them complete.
#: Requirements and the graph first because everything downstream reads them.
STAGE_ORDER = (
    "parse_requirements",
    "build_graph",
    "recommend",
    "write_uml",
    "draw_wireframes",
    "plan_sprint",
)


#: Which node regenerates which STAGE, keyed by stage id, for a retry that
#: should cost one stage rather than six. C1's artefact kinds and stage ids are
#: the same strings, so the keys read either way here; the registry and the
#: retry route treat them as stage ids, which is the vocabulary C2 needs where
#: one artefact (the repository) is written across three stages. The same
#: factories the graph is built from, so a retried stage is persisted by
#: exactly the code that persists a generated one rather than by a second path
#: that can drift.
STAGE_NODES = {
    "requirements": make_parse_requirements,
    "architecture-graph": make_build_graph,
    "architecture-recommendation": make_recommend,
    "uml-diagrams": make_write_uml,
    "wireframes": make_draw_wireframes,
    "sprint-plan": make_plan_sprint,
}


def build_graph(pool: AsyncConnectionPool, checkpointer: BaseCheckpointSaver, c1: C1Client):
    """Six stages, then the gate, with a pause for the design's questions after the first."""
    graph = StateGraph(C1RunState)

    graph.add_node("parse_requirements", make_parse_requirements(pool, c1))
    graph.add_node("questions_gate", questions_gate)
    graph.add_node("build_graph", make_build_graph(pool, c1))
    graph.add_node("recommend", make_recommend(pool, c1))
    graph.add_node("write_uml", make_write_uml(pool, c1))
    graph.add_node("draw_wireframes", make_draw_wireframes(pool, c1))
    graph.add_node("plan_sprint", make_plan_sprint(pool, c1))
    graph.add_node("design_gate", design_gate)

    graph.add_edge(START, STAGE_ORDER[0])
    # questions_gate returns a Command too: on to the graph, or back to the
    # requirements with the answers.
    graph.add_edge(STAGE_ORDER[0], "questions_gate")
    for earlier, later in pairwise(STAGE_ORDER[1:]):
        graph.add_edge(earlier, later)
    graph.add_edge(STAGE_ORDER[-1], "design_gate")
    # design_gate returns a Command, so it routes itself: to END on approval, or
    # back to the first stage when changes are requested.
    graph.add_edge("design_gate", END)

    return graph.compile(checkpointer=checkpointer)
