"""What answered a stage, kept on the stage beside its status (0015).

A stage's model use reached the audit log as one line of words and nowhere a
page could read it. Each stage state carries this, so the stage itself can say
which model answered and what that took.
"""

from pydantic import Field

from .wire import WireModel


class StageModelUse(WireModel):
    """The model use behind one stage's current version.

    `answered_by` names the models the responses named, which is what the
    provider says answered rather than the string the component was configured
    with. `requests` counts the responses received, output retries included.
    A stage that asked no model carries none of this.
    """

    answered_by: list[str] = Field(min_length=1)
    #: What the requests asked about thinking, in the words a run records:
    #: "disabled" where the body turned it off, "default" where nothing was sent
    #: and the provider decided. Empty from a component that does not say.
    thinking: list[str] = Field(default_factory=list)
    requests: int = Field(ge=1)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    #: Part of `tokens_out`, where the provider reports it: DeepSeek's thinking.
    reasoning_tokens: int = Field(default=0, ge=0)
