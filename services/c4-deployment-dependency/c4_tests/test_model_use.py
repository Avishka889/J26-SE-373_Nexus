"""What answered each of this component's stages, read from the responses.

The recorder itself is tested in C1, whose copy this module's is; these hold
C4 to it: every agent reports every response, and every stage that asks a
model says what answered in its notes. The changelog stage's own test reads
the notes end to end.
"""

import pytest
from c4.model_use import recording
from c4.risk.changelog import changelog_agent
from c4.risk.explain import explanation_agent
from c4.service import C4
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

BUILDERS = (
    ("changelog", changelog_agent),
    ("explanation", explanation_agent),
)

#: Every stage that asks a model.
MODEL_STAGES = ("analyse_changelogs", "assess_risk")


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
    assert getattr(getattr(C4, stage), "reports_model_use", False), f"{stage} does not report"
