"""One call to a model, as it is recorded wherever a model is asked (NFR13).

The changelog signal asks a model to extract claims, and the explanation asks one
to write prose about a decision already made. Both record the call the same way:
the model, the prompt and its hash, the settings, what came of it, and what it
cost, retries included, so a study's spend is read from its record and not
estimated after the fact.
"""

from typing import Literal

from pydantic import Field

from .remediation_proposal import RiskLevel
from .wire import WireModel

ModelOutcome = Literal["answered", "malformed", "cut-off", "rate-limited", "provider-error"]


class ModelCallSettings(WireModel):
    """The settings the call was made with, recorded because they change answers."""

    max_tokens: int | None = None
    thinking: str | None = None
    temperature: float | None = None


class ModelCall(WireModel):
    """One call to the model, whatever came of it (NFR13)."""

    model_id: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    settings: ModelCallSettings = Field(default_factory=ModelCallSettings)
    outcome: ModelOutcome
    #: The answers the provider sent back for this call, retries included: each
    #: one was billed, so this and the two counts below are what the call cost.
    requests: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=0.0, ge=0)
    error: str = ""
    #: What the model said the level was. Recorded for the study, used by nothing.
    stated_level: RiskLevel | None = None
