"""What the release notes say, according to a model, and what survived checking.

Signal two (FR5). The model reads the release notes between two versions and
returns claims: what kind of change, which symbols, and the sentence it rests on,
quoted. Code then checks every quote against the stored copy of the notes the
model was shown. A claim whose quote is not there, sits outside the version
window, or names a symbol its own quote does not contain is refused, and counted.

**The model extracts; a rule rates.** The vote is `changelog_level` over the
verified claims, re-derived by the validator here, so an invented claim can
neither raise nor lower the level, and the level can be reproduced from the
report alone (NFR13). What the model itself thought the level was is recorded as
`stated_level` for the study and used by nothing.

**A model that did not answer did not vote.** A rate limit, a provider error, a
malformed answer or one cut off at the output ceiling leaves the signal
abstaining, never reporting a quiet release.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator

from .deploy_rules import CHANGELOG_RULE, ClaimKind, changelog_level
from .ids import UpdateId
from .model_call import ModelCall
from .risk_report import SignalVote
from .wire import WireDatetime, WireModel

ClaimRefusal = Literal[
    "quote-not-found",
    "outside-version-window",
    "empty-quote",
    "symbol-not-in-quote",
    "no-such-source",
]


class ChangelogClaim(WireModel):
    """A claim that was checked and holds: the quote is in the notes, in the window."""

    id: str = Field(min_length=1)
    kind: ClaimKind
    symbols: list[str] = Field(default_factory=list)
    quote: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    #: The release whose notes hold the quote.
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def every_symbol_is_in_the_quote(self) -> "ChangelogClaim":
        missing = [symbol for symbol in self.symbols if symbol not in self.quote]
        if missing:
            raise ValueError(f"the claim names symbols its quote does not contain: {missing}")
        return self


class RefusedClaim(WireModel):
    """A claim the check refused, kept so the refusal rate is a result."""

    #: As the model wrote it, which may not be a kind the contract knows.
    kind: str = ""
    quote: str = ""
    version: str = ""
    symbols: list[str] = Field(default_factory=list)
    reason: ClaimRefusal
    detail: str = ""


class ChangelogAnalysis(WireModel):
    """The changelog signal for one update."""

    update_id: UpdateId
    #: The releases whose notes were read, oldest first.
    windows: list[str] = Field(default_factory=list)
    notes_found: bool
    claims: list[ChangelogClaim] = Field(default_factory=list)
    refused: list[RefusedClaim] = Field(default_factory=list)
    vote: SignalVote
    #: None when there was nothing to send, because no notes were found.
    model: ModelCall | None = None

    @model_validator(mode="after")
    def the_vote_is_the_rules(self) -> "ChangelogAnalysis":
        if self.vote.signal != "changelog":
            raise ValueError("a changelog analysis carries the changelog vote")
        answered = self.model is not None and self.model.outcome == "answered"
        if answered:
            expected = changelog_level(
                [claim.kind for claim in self.claims],
                notes_found=self.notes_found,
                refused=len(self.refused),
            )
        else:
            expected = None
        if self.vote.level != expected:
            raise ValueError(
                f"the changelog vote says {self.vote.level}; over these verified claims "
                f"the rule says {expected}"
            )
        if not answered and (self.claims or self.refused):
            raise ValueError("claims were recorded from a model that did not answer")
        return self


class ChangelogReport(WireModel):
    """The `changelog-report` artefact."""

    version: int = Field(ge=1)
    generated_at: WireDatetime
    #: The configured model string, recorded on every run.
    model_id: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_id: Literal["changelog-rule/1"] = CHANGELOG_RULE
    per_update: list[ChangelogAnalysis] = Field(default_factory=list)
    #: True when a rate limit ended the stage; the updates after it abstain.
    stopped_on_rate_limit: bool = False
    stop_reason: str = ""

    @computed_field
    @property
    def claims_verified(self) -> int:
        return sum(len(item.claims) for item in self.per_update)

    @computed_field
    @property
    def claims_refused(self) -> int:
        return sum(len(item.refused) for item in self.per_update)

    @computed_field
    @property
    def refusal_rate(self) -> float:
        total = self.claims_verified + self.claims_refused
        return self.claims_refused / total if total else 0.0
