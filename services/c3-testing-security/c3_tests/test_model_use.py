"""What answered each of this component's stages, read from the responses.

The recorder itself is tested in C1, whose copy this module's is; these hold
C3 to it: every agent reports every response, and every stage that asks a
model says what answered in its notes. The healing stage's sandbox test reads
the notes end to end.
"""

from functools import partial

import pytest
from c3.detect.llm import build_detector, build_triager
from c3.generate.fill import build_filler
from c3.heal.referee import build_referee
from c3.heal.repair import build_repairer
from c3.model_use import recording
from c3.remediate.patch import build_patcher
from c3.service import C3
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

BUILDERS = (
    ("test filler", build_filler),
    ("detector", build_detector),
    ("triager", build_triager),
    ("repairer, whole file", build_repairer),
    ("repairer, minimal", partial(build_repairer, shape="minimal")),
    ("referee", build_referee),
    ("patcher", build_patcher),
)

#: Every stage that asks a model.
MODEL_STAGES = ("generate_tests", "heal", "scan", "propose_remediation")


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
    assert getattr(getattr(C3, stage), "reports_model_use", False), f"{stage} does not report"
