"""A model that answers every stage as if the subject were a calculator.

This is what makes the golden half of the corpus case possible. The real
component runs, with its real rules, budget, validators, repair loops, promotion
and read model, and only the model's answers are fixed. So a failure means our
code is wrong rather than the model having a bad day, and the same assertions can
then be pointed at a live provider to check the prompts.

Routing is by the shape of the output the agent is asking for rather than by
matching the prompt text. Six agents, six output types, and each has a distinct
set of top level fields, so the script can tell which stage is calling without
depending on the wording of a prompt that is free to change.
"""

import json
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from .corpus import CALCULATOR_INPUT

REQUIREMENTS: dict[str, Any] = {
    "requirements": [
        {
            "text": "A user builds a simple calculator application.",
            "source_start": 0,
            "source_end": len(CALCULATOR_INPUT),
            "source_quote": CALCULATOR_INPUT,
            "rationale_kind": "read",
        },
        {
            "text": "A user enters two numbers and chooses an operation.",
            "source_start": 0,
            "source_end": 0,
            "source_quote": "",
            "rationale_kind": "inferred",
        },
        {
            "text": "The calculator adds, subtracts, multiplies and divides.",
            "source_start": 0,
            "source_end": 0,
            "source_quote": "",
            "rationale_kind": "inferred",
        },
        {
            "text": "The calculator shows the result of the calculation.",
            "source_start": 0,
            "source_end": 0,
            "source_quote": "",
            "rationale_kind": "inferred",
        },
    ]
}

GRAPH: dict[str, Any] = {
    "nodes": [
        {
            "id": "a1",
            "kind": "actor",
            "label": "User",
            "description": "The person doing the arithmetic.",
            "traces": ["R-1", "R-2"],
            "actor_kind": "primary",
        },
        {
            "id": "e1",
            "kind": "entity",
            "label": "Calculation",
            "description": "One expression and the result it produced.",
            "traces": ["R-2", "R-4"],
            "attributes": [
                {"name": "expression", "type": "string"},
                {"name": "operation", "type": "string"},
                {"name": "result", "type": "number"},
            ],
        },
        {
            "id": "m1",
            "kind": "service",
            "label": "Calculator",
            "description": "Evaluates an expression and returns the result.",
            "traces": ["R-1", "R-3"],
        },
    ],
    "edges": [
        {
            "id": "x1",
            "source": "a1",
            "target": "e1",
            "kind": "action",
            "verb": "enters",
            "traces": ["R-2"],
        },
        {
            "id": "x2",
            "source": "m1",
            "target": "e1",
            "kind": "data",
            "verb": "owns",
            "traces": ["R-4"],
        },
    ],
}

#: No digits anywhere. The explanation agent refuses any figure that is not in
#: the counted facts, so a stray number here would send the script into a repair
#: loop it cannot get out of.
EXPLANATION: dict[str, Any] = {
    "rationale": (
        "The design has one service and one thing it stores, so there is nothing to "
        "split apart and nothing outside it to isolate from."
    ),
    "pros": [
        "One thing to build and one thing to deploy",
        "The arithmetic and the display stay in one place",
    ],
    "cons": [
        "Everything scales together, whether it needs to or not",
        "A fault anywhere takes the whole calculator down",
    ],
}

INTERACTION: dict[str, Any] = {
    "name": "Working out a calculation",
    "steps": [
        {
            "from_id": "a1",
            "to_id": "m1",
            "message": "enter two numbers and an operation",
            "kind": "call",
        },
        {
            "from_id": "m1",
            "to_id": "m1",
            "message": "check the operation is one it supports",
            "kind": "note",
        },
        {"from_id": "m1", "to_id": "e1", "message": "record the {e1}", "kind": "call"},
        {"from_id": "e1", "to_id": "m1", "message": "the {e1} is stored", "kind": "return"},
        {"from_id": "m1", "to_id": "a1", "message": "show the result", "kind": "return"},
    ],
}

FLOW: dict[str, Any] = {
    "name": "Working out a calculation",
    "screens": [
        {
            "id": "s1",
            "name": "Calculator",
            "crumbs": ["Calculator"],
            "traces": ["R-2", "R-3"],
            "blocks": [
                {"id": "b1", "kind": "field", "label": "First number", "value": "12"},
                {"id": "b2", "kind": "field", "label": "Second number", "value": "4"},
                {"id": "b3", "kind": "row", "label": "Divide", "link_id": "l1"},
            ],
            "links": [
                {"id": "l1", "label": "Equals", "target_id": "s2", "variant": "primary"},
            ],
        },
        {
            "id": "s2",
            "name": "Result",
            "crumbs": ["Calculator", "Result"],
            "traces": ["R-4"],
            "blocks": [
                {"id": "b4", "kind": "summary", "label": "Result", "value": "3"},
                {"id": "b5", "kind": "text", "label": "Divided twelve by four"},
            ],
            "links": [
                {"id": "l2", "label": "Start again", "target_id": "s1", "variant": "secondary"},
            ],
        },
    ],
}

PLAN: dict[str, Any] = {
    "goal": "Someone can work out a calculation and see the result.",
    "stories": [
        {
            "title": "As a user, I can add, subtract, multiply and divide two numbers",
            "epic": "Arithmetic",
            "traces": ["R-2", "R-3"],
            "acceptance": [
                {
                    "given": "two numbers entered and an operation chosen",
                    "when": "the user asks for the answer",
                    "then": "the result of that operation is shown",
                },
                {
                    "given": "a division with zero as the second number",
                    "when": "the user asks for the answer",
                    "then": "the calculator says it cannot divide by zero and shows no result",
                },
            ],
        },
        {
            "title": "As a user, I can see the calculation I just did",
            "epic": "Arithmetic",
            "traces": ["R-4"],
            "acceptance": [
                {
                    "given": "a completed calculation",
                    "when": "the result is shown",
                    "then": "the expression it came from is shown beside it",
                }
            ],
        },
    ],
}

#: Which output shape belongs to which stage. Distinct by construction: no two of
#: the six output types share a top level field set.
BY_SHAPE: tuple[tuple[frozenset[str], dict[str, Any]], ...] = (
    (frozenset({"requirements"}), REQUIREMENTS),
    (frozenset({"nodes", "edges"}), GRAPH),
    (frozenset({"rationale", "pros", "cons"}), EXPLANATION),
    (frozenset({"name", "steps"}), INTERACTION),
    (frozenset({"name", "screens"}), FLOW),
    (frozenset({"goal", "stories"}), PLAN),
)


def answer_for(fields: frozenset[str]) -> dict[str, Any]:
    """The payload for whichever stage is asking."""
    for shape, payload in BY_SHAPE:
        if shape <= fields:
            return payload
    raise AssertionError(
        f"the calculator script does not know how to answer an output asking for {sorted(fields)}"
    )


def calculator_model() -> FunctionModel:
    """One model, six answers, routed by the shape being asked for."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        fields = frozenset(tool.parameters_json_schema.get("properties", {}))
        return ModelResponse(parts=[ToolCallPart(tool.name, json.dumps(answer_for(fields)))])

    return FunctionModel(respond)
