"""What answered each of this component's stages, read from the responses.

The recorder itself is tested in C1, whose copy this module's is; these hold
C2 to it: every agent reports every response, and every stage that asks a
model says what answered in its notes.
"""

import pytest
from c2.codegen.fill import build_handler_filler, build_page_filler
from c2.contract.llm_arm import build_contract_agent
from c2.model_use import recording
from c2.service import C2
from c2.stack.explain import build_stack_explainer
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from .design_fixture import graph
from .test_service import c2_answering

BUILDERS = (
    ("contract", build_contract_agent),
    ("stack explainer", build_stack_explainer),
    ("page filler", build_page_filler),
    ("handler filler", build_handler_filler),
)

#: Every stage that asks a model.
MODEL_STAGES = ("propose_stack", "infer_contract", "generate_frontend", "generate_backend")


def prose(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("An answer in words, not in the shape asked.")])


@pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[n for n, _ in BUILDERS])
async def test_every_response_an_agent_gets_is_recorded(name: str, build) -> None:
    # A model that only answers in prose is refused until the agent gives up,
    # and each refused answer still counts.
    agent = build(FunctionModel(prose))
    with recording() as answers, pytest.raises(UnexpectedModelBehavior):
        await agent.run("anything")

    assert answers, f"the {name} agent's responses are not recorded"


@pytest.mark.parametrize("stage", MODEL_STAGES)
def test_every_stage_that_asks_a_model_reports_what_answered(stage: str) -> None:
    assert getattr(getattr(C2, stage), "reports_model_use", False), f"{stage} does not report"


async def test_a_stage_says_what_answered_in_its_notes() -> None:
    component = c2_answering({"rationale": "One team, one deploy, one language."})

    result = await component.propose_stack(graph())

    use = result.notes["model_use"]
    assert use["answered_by"] == ["function:respond:"]
    assert use["requests"] == 1
    assert use["tokens_in"] > 0
