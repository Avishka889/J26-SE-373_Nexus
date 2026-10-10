"""The canvas does not rearrange itself between two runs over the same design.

The property that matters is not "the layout looks reasonable", it is that the
same graph always lands in the same place. A reader comparing version 2 with
version 1 has to be able to see what actually moved, and on a canvas that
reshuffles, the impact highlight saying "three nodes changed" is noise.

The strongest test here is the shuffled one. A layout can be perfectly
deterministic in testing and still depend on the order the model happened to list
its nodes in, which is the one thing that varies between two runs over identical
requirements.
"""

import random

from c1.sag.layout import COLUMN_X, ROW_HEIGHT, layout
from c1.sag.schema import DraftNode
from sdlc_contracts import Position


def node(id: str, kind: str, traces: list[str], actor_kind: str = "") -> DraftNode:
    return DraftNode(id=id, kind=kind, label=id.upper(), traces=traces, actor_kind=actor_kind)


#: The requirements as the artefact lists them, which is reading order. Layout
#: takes this rather than reading the number out of an id, because an id is an
#: identity carried across design versions: a requirement added in version three
#: has a high number and still reads first in the brief.
READING_ORDER = ["R-1", "R-2", "R-3", "R-4", "R-5", "R-6"]


def place(nodes: list[DraftNode], order: list[str] | None = None) -> dict[str, Position]:
    return layout(nodes, requirement_ids=READING_ORDER if order is None else order)


def graph() -> list[DraftNode]:
    return [
        node("a1", "actor", ["R-1"], "primary"),
        node("a2", "actor", ["R-4"], "primary"),
        node("a3", "actor", ["R-2"], "external_system"),
        node("m1", "service", ["R-1"]),
        node("m2", "service", ["R-3"]),
        node("e1", "entity", ["R-1"]),
        node("e2", "entity", ["R-2"]),
        node("e3", "entity", ["R-5"]),
        node("c1", "constraint", ["R-6"]),
    ]


class TestDeterminism:
    def test_the_same_graph_lands_in_the_same_place(self) -> None:
        assert place(graph()) == place(graph())

    def test_the_order_the_model_listed_nodes_in_does_not_matter(self) -> None:
        # The failure this module exists to prevent: a layout that is stable in a
        # test and moves in production because the model emitted its nodes in a
        # different order over identical requirements.
        expected = place(graph())
        rng = random.Random(0)
        for _ in range(20):
            shuffled = graph()
            rng.shuffle(shuffled)
            assert place(shuffled) == expected

    def test_two_nodes_sharing_a_label_still_land_deterministically(self) -> None:
        # Ids break the tie, not labels, because labels are not unique.
        left = [node("e1", "entity", ["R-1"]), node("e2", "entity", ["R-1"])]
        right = list(reversed(left))
        for member in left + right:
            member.label = "Record"
        assert place(left) == place(right)

    def test_nothing_depends_on_a_clock_or_a_random_source(self) -> None:
        first = place(graph())
        random.seed(999)
        assert place(graph()) == first


class TestTheGeometry:
    def test_each_kind_gets_its_own_column(self) -> None:
        placed = place(graph())
        for member in graph():
            assert placed[member.id].x == COLUMN_X[member.kind]

    def test_columns_read_left_to_right_in_the_order_a_reader_traverses_them(self) -> None:
        assert COLUMN_X["actor"] < COLUMN_X["service"] < COLUMN_X["entity"] < COLUMN_X["constraint"]

    def test_no_two_nodes_sit_on_top_of_each_other(self) -> None:
        placed = place(graph())
        seen = {(position.x, position.y) for position in placed.values()}
        assert len(seen) == len(placed)

    def test_a_column_reads_in_requirement_order(self) -> None:
        placed = place(graph())
        # e1 came from R-1, e2 from R-2, e3 from R-5, so they descend in that order
        # and a reader following a trace chip moves down rather than hunting.
        assert placed["e1"].y < placed["e2"].y < placed["e3"].y

    def test_a_column_reads_in_reading_order_and_not_in_id_order(self) -> None:
        """The canvas and the requirements page agree about what comes first.

        A requirement added in a later design version carries a high id and
        still reads wherever the brief puts it, because ids are identities
        carried across versions and are never reissued. Ranking by the number
        inside the id, which is what this did before, would have put the newest
        requirement's node at the bottom of the canvas while the requirement sat
        at the top of the list.
        """
        order = ["R-9", "R-2", "R-1"]
        placed = place(
            [
                node("e1", "entity", ["R-1"]),
                node("e2", "entity", ["R-2"]),
                node("e3", "entity", ["R-9"]),
            ],
            order,
        )

        assert placed["e3"].y < placed["e2"].y < placed["e1"].y

    def test_people_come_before_other_systems(self) -> None:
        placed = place(graph())
        # a3 is an external system tracing to R-2, so requirement order alone
        # would put it above a2 at R-4. A reader looks for themselves first.
        assert placed["a1"].y < placed["a2"].y < placed["a3"].y

    def test_shorter_columns_are_centred_rather_than_hanging_off_the_top(self) -> None:
        placed = place(graph())
        entities = [placed[i].y for i in ("e1", "e2", "e3")]
        constraints = [placed["c1"].y]
        # One constraint against three entities: it sits in the middle of them,
        # not level with the first.
        assert min(entities) < constraints[0] < max(entities)

    def test_positions_are_round_numbers(self) -> None:
        # Only because a reader comparing two versions should not see 319.5
        # become 320 and wonder what moved.
        for position in place(graph()).values():
            assert position.x == int(position.x)
            assert position.y == int(position.y)

    def test_rows_are_far_enough_apart_for_a_two_line_label(self) -> None:
        placed = place(graph())
        column = sorted(placed[i].y for i in ("e1", "e2", "e3"))
        assert column[1] - column[0] == ROW_HEIGHT


class TestEdgeCases:
    def test_an_empty_graph_places_nothing(self) -> None:
        assert place([]) == {}

    def test_one_node_is_placed_at_the_top_of_its_column(self) -> None:
        placed = place([node("a1", "actor", ["R-1"], "primary")])
        assert placed["a1"].x == COLUMN_X["actor"]
        assert placed["a1"].y == 0

    def test_a_node_with_no_trace_sorts_last_rather_than_crashing(self) -> None:
        # The rules refuse an untraced node, but layout runs on drafts too and
        # must not be the thing that raises.
        placed = place([node("e1", "entity", []), node("e2", "entity", ["R-1"])])
        assert placed["e2"].y < placed["e1"].y

    def test_an_unrecognised_kind_still_gets_a_position(self) -> None:
        # A node with no coordinates renders at the origin under everything else,
        # which hides a rule violation instead of showing it.
        placed = place([node("z1", "widget", ["R-1"])])
        assert placed["z1"].x > COLUMN_X["constraint"]

    def test_a_trace_to_a_requirement_the_artefact_does_not_list_sorts_last(self) -> None:
        # There is no position to order it by, and guessing one from the digits in
        # the id is what this stopped doing. The rules refuse a trace that
        # resolves to nothing; layout puts it at the bottom and does not raise.
        placed = place([node("e1", "entity", ["R-99"]), node("e2", "entity", ["R-2"])])
        assert placed["e2"].y < placed["e1"].y

    def test_no_reading_order_at_all_still_places_everything(self) -> None:
        placed = place([node("e1", "entity", ["R-1"]), node("e2", "entity", ["R-2"])])
        assert len({(one.x, one.y) for one in placed.values()}) == 2


class TestStabilityUnderChange:
    def test_adding_a_node_leaves_the_other_columns_alone(self) -> None:
        before = place(graph())
        after = place([*graph(), node("m3", "service", ["R-9"])])
        # A new service must not move the entities. Its own column reflows,
        # which is inherent to a column layout and visible as such.
        for entity in ("e1", "e2", "e3"):
            assert after[entity].x == before[entity].x

    def test_renaming_a_node_does_not_move_it(self) -> None:
        before = place(graph())
        renamed = graph()
        for member in renamed:
            if member.id == "e2":
                member.label = "Something Else Entirely"
        assert place(renamed) == before
