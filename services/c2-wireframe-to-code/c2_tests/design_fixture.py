"""A small coherent design slice the contract tests share.

One actor, two entities, one external system, a constraint, three action
edges, one flow of three screens (a list, a form, a confirmation), one story
in scope and one out. Small enough to reason about by hand, rich enough to
exercise every mapping the rule arm performs.
"""

from c2.rules.scope import derive_scope
from sdlc_contracts import (
    AcceptanceCriterion,
    ArchitectureGraph,
    EntityAttribute,
    FlowLink,
    FlowScreen,
    GraphEdge,
    GraphNode,
    ScreenBlock,
    SprintPlan,
    UserStory,
    VelocityAssumption,
    WireframeCoverageRow,
    WireframeFlow,
    WireframesArtefact,
)


def _node(id: str, kind: str, label: str, **extra) -> GraphNode:
    return GraphNode(
        id=id,
        kind=kind,
        label=label,
        traces=extra.pop("traces", ["R-1"]),
        position={"x": 0, "y": 0},
        **extra,
    )


def graph() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[
            _node("a1", "actor", "Shopper", actor_kind="primary"),
            _node("s1", "service", "Order Service"),
            _node(
                "e1",
                "entity",
                "Order",
                traces=["R-1", "R-2"],
                attributes=[
                    EntityAttribute(name="total", type="money"),
                    EntityAttribute(name="placedAt", type="datetime"),
                    EntityAttribute(name="status", type="enum"),
                ],
            ),
            _node(
                "e2",
                "entity",
                "Product",
                traces=["R-3"],
                attributes=[EntityAttribute(name="name", type="string")],
            ),
            _node(
                "c1",
                "constraint",
                "An order total never exceeds available stock",
                traces=["R-4"],
                applies_to=["e1"],
            ),
            _node("x1", "actor", "Inventory System", actor_kind="external_system"),
        ],
        edges=[
            GraphEdge(
                id="ed1", source="a1", target="e1", kind="action", verb="places", traces=["R-1"]
            ),
            GraphEdge(
                id="ed2", source="a1", target="e1", kind="action", verb="cancels", traces=["R-2"]
            ),
            GraphEdge(
                id="ed3", source="a1", target="e2", kind="action", verb="browses", traces=["R-3"]
            ),
            GraphEdge(
                id="ed4", source="s1", target="e1", kind="data", verb="stores", traces=["R-1"]
            ),
        ],
    )


def wireframes() -> WireframesArtefact:
    return WireframesArtefact(
        flows=[
            WireframeFlow(
                id="shop",
                name="Place an order",
                version="v1",
                coversStoryIds=["US-1"],
                screens=[
                    FlowScreen(
                        id="catalog",
                        name="Product Catalog",
                        blocks=[
                            ScreenBlock(id="b1", kind="list", label="Products"),
                        ],
                        links=[
                            FlowLink(
                                id="l1",
                                label="Add to order",
                                target_id="checkout",
                                variant="primary",
                            ),
                        ],
                    ),
                    FlowScreen(
                        id="checkout",
                        name="Order Checkout",
                        blocks=[
                            ScreenBlock(id="b2", kind="field", label="Delivery address"),
                            ScreenBlock(id="b3", kind="field", label="Payment method"),
                        ],
                        links=[
                            FlowLink(
                                id="l2", label="Place order", target_id="done", variant="primary"
                            ),
                        ],
                    ),
                    FlowScreen(
                        id="done",
                        name="Order Confirmed",
                        terminal=True,
                        blocks=[
                            ScreenBlock(id="b4", kind="summary", label="Order summary"),
                        ],
                        links=[],
                    ),
                ],
            )
        ],
        coverage=[
            WireframeCoverageRow(
                story_id="US-1",
                story_title="Place an order",
                screen_ids=["shop/catalog", "shop/checkout", "shop/done"],
                covered=True,
            ),
            WireframeCoverageRow(
                story_id="US-2",
                story_title="Monthly report",
                screen_ids=[],
                covered=False,
                needs_screen=False,
            ),
        ],
    )


def _story(id: str, title: str, points: int, traces: list[str]) -> UserStory:
    return UserStory(
        id=id,
        title=title,
        epic="Ordering",
        points=points,
        priority="must",
        traces=traces,
        acceptance=[
            AcceptanceCriterion(
                id=f"{id}-a1",
                given="a shopper with items chosen",
                when="they complete the action",
                then="the outcome is recorded",
            )
        ],
    )


def sprint() -> SprintPlan:
    return SprintPlan(
        sprint_name="Sprint 1 (proposed)",
        goal="An order can be placed end to end.",
        velocity_assumption=VelocityAssumption(points=20, basis="assumed for a first sprint"),
        estimated_points=5,
        proposed=[_story("US-1", "Place an order", 5, ["R-1", "R-2"])],
        backlog=[_story("US-2", "Monthly report", 3, ["R-9"])],
    )


def scope():
    return derive_scope(sprint(), wireframes())
