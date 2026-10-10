"""Where each node sits on the canvas, decided the same way every time.

The graph is regenerated whenever the requirements change, and a reader comparing
two versions has to be able to see what moved. If the layout came out differently
each run, everything would appear to have moved and the impact highlight would be
worthless: "three nodes changed" means nothing on a canvas that rearranged itself.

So this is a pure function of the graph. No randomness, no clock, and above all
no dependence on the order the model happened to list its nodes in, which is the
one that looks deterministic in testing and is not. Two runs producing the same
nodes in different orders produce identical positions, and there is a test that
shuffles the input to prove it.

The geometry follows what the existing designs already use: four columns, left to
right, in the order a reader traverses them. Who acts, what runs, what is kept,
what constrains it all.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from sdlc_contracts import Position

from .schema import DraftNode

#: One column per kind, left to right, in reading order.
COLUMN_X: Final[dict[str, int]] = {
    "actor": 0,
    "service": 340,
    "entity": 720,
    "constraint": 1080,
}

#: Vertical space per node. Enough that a two line label does not collide with
#: the node beneath it.
ROW_HEIGHT: Final = 160

#: Anything with an unrecognised kind. It still gets a position, because a node
#: with no coordinates renders at the origin under everything else, and a rule
#: violation should be visible rather than hidden.
FALLBACK_X: Final = 1440

#: Sorts a node with no usable trace last. The rules will have refused it anyway,
#: but layout runs on drafts too and must not be the thing that raises.
UNTRACED = 10_000


def _trace_rank(node: DraftNode, order: Mapping[str, int]) -> int:
    """How early in the requirements list this node's earliest trace appears.

    Ordering by this makes the canvas read in requirement order, so the node for
    the first requirement sits above the node for the seventh and a reader
    following a trace chip moves down the column rather than hunting.

    By position in the list rather than by the number inside the id, which is
    what this did until requirement ids became identities. An id is now carried
    across design versions and never reissued, so a requirement added in version
    three has a high number and reads first in the brief. Ranking by the number
    would have put it at the bottom of the canvas while it sat at the top of the
    requirements list, and the two screens would disagree about the same design.
    """
    ranks = [order[trace] for trace in node.traces if trace in order]
    return min(ranks) if ranks else UNTRACED


def _actor_rank(node: DraftNode) -> int:
    """People before other systems, within the actor column.

    A reader looks for themselves first. External systems are context, and they
    belong below the humans rather than interleaved with them.
    """
    return 1 if node.actor_kind == "external_system" else 0


def _sort_key(node: DraftNode, order: Mapping[str, int]) -> tuple[int, int, str]:
    """Deterministic and independent of the order the model listed nodes in.

    The id is the final tiebreak rather than the label, because two nodes can
    share a label and ids are unique by rule 1. Falling back to the label would
    make the layout depend on input order for the duplicate pair, which is the
    exact failure this module exists to prevent.
    """
    return (_actor_rank(node), _trace_rank(node, order), node.id)


def layout(nodes: list[DraftNode], *, requirement_ids: Sequence[str] = ()) -> dict[str, Position]:
    """A position for every node, from the graph and the order the brief reads in.

    `requirement_ids` is the requirements as the artefact lists them, which is
    reading order. Passing them is what lets the canvas read the same way the
    requirements page does; without them every node ranks as untraced and the
    column falls back to sorting by id, which is deterministic and arbitrary.
    """
    order = {identifier: rank for rank, identifier in enumerate(requirement_ids)}
    columns: dict[str, list[DraftNode]] = {}
    for node in nodes:
        columns.setdefault(node.kind, []).append(node)

    for members in columns.values():
        members.sort(key=lambda member: _sort_key(member, order))

    tallest = max((len(members) for members in columns.values()), default=0)
    positions: dict[str, Position] = {}

    for kind, members in columns.items():
        x = COLUMN_X.get(kind, FALLBACK_X)
        # Centred against the tallest column, so a graph with two actors and six
        # entities does not hang off the top. Integer division keeps the numbers
        # round, which matters only because a reader comparing two versions
        # should not see 319.5 move to 320.
        offset = ((tallest - len(members)) * ROW_HEIGHT) // 2
        for row, node in enumerate(members):
            positions[node.id] = Position(x=x, y=offset + row * ROW_HEIGHT)

    return positions
