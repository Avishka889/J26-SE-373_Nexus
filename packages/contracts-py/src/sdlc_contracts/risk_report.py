"""The C4 risk report: three votes per update, the rule that combined them, the strategy.

This is the artefact the dissertation's first contribution stands on, and three
things are enforced here by shape because each is a way a hybrid assessment can
quietly stop being one.

**The final level is recomputed, never accepted.** `arbitration.final` and
`decided_by` must equal `safety_first` over the votes, and `strategy` must equal
`strategy_for` over the final level. A producer, model or code, that writes any
other level is refused at the boundary. That is FR6 and FR7 as a property of the
type rather than a promise in prose.

**Disagreement is said out loud.** When the votes cast differ, or when nothing
voted at all, an advisory is required (NFR10): the most cautious level was taken,
and a developer should confirm it.

**Level, evidence and files travel together.** Each assessment carries the
evidence its votes rest on and the files and components the update touches
(NFR11), and every evidence id a vote cites must resolve in the same assessment.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator

from .deploy_rules import (
    ARBITRATION_RULE,
    CHANGELOG_RULE,
    SEMVER_RULE,
    SIGNALS,
    STRATEGY_RULE,
    USAGE_RULE,
    DeployStrategy,
    Signal,
    VersionChange,
    safety_first,
    semver_level,
    strategy_for,
)
from .ids import UpdateId
from .model_call import ModelCall
from .remediation_proposal import RiskLevel
from .wire import Prose, WireDatetime, WireModel

#: Which rule each signal's vote is produced by.
RULE_FOR_SIGNAL: dict[Signal, str] = {
    "semver": SEMVER_RULE,
    "changelog": CHANGELOG_RULE,
    "usage": USAGE_RULE,
}

EvidenceKind = Literal["version", "claim", "reference", "api-diff", "component"]


class SignalVote(WireModel):
    """One signal's answer for one update, or its reason for having none."""

    signal: Signal
    level: RiskLevel | None = None
    #: Required exactly when there is no level: an abstention says why.
    abstained_reason: str = ""
    rule_id: str = Field(min_length=1)
    #: Written by code from the evidence, never by a model.
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def a_vote_or_a_reason(self) -> "SignalVote":
        if self.level is None and not self.abstained_reason.strip():
            raise ValueError(f"the {self.signal} signal abstained without saying why")
        if self.level is not None and self.abstained_reason.strip():
            raise ValueError(f"the {self.signal} signal voted and also gave an abstention")
        if self.rule_id != RULE_FOR_SIGNAL[self.signal]:
            raise ValueError(
                f"the {self.signal} vote names rule {self.rule_id!r}, "
                f"not {RULE_FOR_SIGNAL[self.signal]!r}"
            )
        return self


class EvidenceRef(WireModel):
    """One piece of evidence a vote rests on, summarised for a reader."""

    id: str = Field(min_length=1)
    kind: EvidenceKind
    summary: str = Field(min_length=1)


class Arbitration(WireModel):
    """How the votes became one level (FR6, FR7)."""

    rule_id: Literal["safety-first-max/1"] = ARBITRATION_RULE
    final: RiskLevel
    decided_by: list[Signal] = Field(default_factory=list)
    #: NFR10: required when the votes disagree or when nothing voted.
    advisory: str = ""


class Strategy(WireModel):
    """How an update at this level may ship (FR17, FR18, FR19)."""

    rule_id: Literal["risk-strategy/1"] = STRATEGY_RULE
    deploy: DeployStrategy
    manual_review_required: bool
    rollback_required: bool


class Latency(WireModel):
    """Seconds spent per step for one update (NFR1).

    The assessment is the changelog step, the usage step and the arbitration.
    Retrieval is reported beside it rather than inside it, because NFR1 bounds
    the assessment and a slow registry is not the engine being slow.
    """

    changelog_seconds: float = Field(ge=0)
    usage_seconds: float = Field(ge=0)
    arbitration_seconds: float = Field(ge=0)
    retrieval_seconds: float = Field(default=0.0, ge=0)

    @computed_field
    @property
    def assessment_seconds(self) -> float:
        return self.changelog_seconds + self.usage_seconds + self.arbitration_seconds


class UpdateAssessment(WireModel):
    """One update, assessed."""

    update_id: UpdateId
    key: str = Field(min_length=1)
    package: str = Field(min_length=1)
    ecosystem: Literal["npm", "maven"]
    from_version: str = Field(min_length=1)
    to_version: str = Field(min_length=1)
    #: The version change the SemVer vote is re-derived from.
    change: VersionChange
    #: Exactly one per signal, in the order `SIGNALS` names them.
    votes: list[SignalVote]
    arbitration: Arbitration
    strategy: Strategy
    affected_files: list[str] = Field(default_factory=list)
    #: Semantic Architecture Graph node ids.
    affected_components: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    #: Prose for a developer. Never the source of a level: the check that it
    #: does not contradict the final level lives where it is written.
    explanation: Prose = ""
    explanation_source: Literal["model", "rule", "none"] = "none"
    #: Why the model's answer was refused by the check: a level other than the
    #: final one, a quote or a file the evidence does not hold. Empty otherwise.
    explanation_refusal: str = ""
    #: Why no model answer was there to check: no model could be built, it did
    #: not answer, or a rate limit stopped the explanations. Empty otherwise.
    explanation_unavailable: str = ""
    #: The call the explanation was asked with, whatever came of it, so what the
    #: prose cost is on the record (NFR13). None when no call was made.
    explanation_call: ModelCall | None = None
    #: Em and en dashes taken out of the model's prose before it was shown, so
    #: how often the prompt's own rule was not kept is a result. A quote keeps its.
    explanation_dashes_replaced: int = Field(default=0, ge=0)
    latency: Latency

    @model_validator(mode="after")
    def the_level_is_the_rules_not_the_writers(self) -> "UpdateAssessment":
        signals = [vote.signal for vote in self.votes]
        if signals != list(SIGNALS):
            raise ValueError(
                f"expected one vote per signal in order {list(SIGNALS)}, got {signals}"
            )

        by_signal = {vote.signal: vote.level for vote in self.votes}
        if by_signal["semver"] != semver_level(self.change):
            raise ValueError(
                f"the SemVer vote says {by_signal['semver']} for a {self.change} change, "
                f"and the rule says {semver_level(self.change)}"
            )

        final, decided_by = safety_first(by_signal)
        if (self.arbitration.final, tuple(self.arbitration.decided_by)) != (final, decided_by):
            raise ValueError(
                f"the report says {self.arbitration.final} decided by "
                f"{self.arbitration.decided_by}; the rule over these votes says "
                f"{final} decided by {list(decided_by)}"
            )

        cast = {level for level in by_signal.values() if level is not None}
        if (len(cast) > 1 or not cast) and not self.arbitration.advisory.strip():
            raise ValueError(
                "the signals disagree or none voted, so the assessment must advise a "
                "developer to confirm it (NFR10)"
            )

        expected = strategy_for(final)
        high = final == "high"
        if (
            self.strategy.deploy != expected
            or self.strategy.manual_review_required != high
            or self.strategy.rollback_required != high
        ):
            raise ValueError(
                f"a {final} update ships as {expected}, with manual review and a prepared "
                f"rollback exactly when it is high"
            )

        known = {item.id for item in self.evidence}
        for vote in self.votes:
            missing = [ref for ref in vote.evidence_ids if ref not in known]
            if missing:
                raise ValueError(
                    f"the {vote.signal} vote cites evidence that is not in the assessment: {missing}"
                )
        return self

    @model_validator(mode="after")
    def model_prose_comes_from_an_answer(self) -> "UpdateAssessment":
        call = self.explanation_call
        if call is not None and call.outcome != "answered" and self.explanation_source == "model":
            raise ValueError(
                f"the explanation is the model's, and the call it came from was {call.outcome}"
            )
        return self

    @computed_field
    @property
    def disagreement(self) -> bool:
        return len({vote.level for vote in self.votes if vote.level is not None}) > 1

    @computed_field
    @property
    def evidence_complete(self) -> bool:
        """Every vote that was cast cites at least one piece of evidence."""
        return all(vote.evidence_ids for vote in self.votes if vote.level is not None)


class RuleSet(WireModel):
    """The rule ids this report was produced under, so a table can name them."""

    semver: Literal["semver-rule/1"] = SEMVER_RULE
    changelog: Literal["changelog-rule/1"] = CHANGELOG_RULE
    usage: Literal["usage-rule/1"] = USAGE_RULE
    arbitration: Literal["safety-first-max/1"] = ARBITRATION_RULE
    strategy: Literal["risk-strategy/1"] = STRATEGY_RULE


class RiskReport(WireModel):
    """The `risk-report` artefact: every update at one deploy version, assessed."""

    version: int = Field(ge=1)
    generated_at: WireDatetime
    rules: RuleSet = Field(default_factory=RuleSet)
    assessments: list[UpdateAssessment] = Field(default_factory=list)
    #: NFR1, in seconds.
    latency_budget_seconds: float = Field(default=30.0, gt=0)
    #: The model and prompt the explanations were asked of, when any was (NFR13).
    explanation_model_id: str = ""
    explanation_prompt_id: str = ""
    explanation_prompt_sha256: str = ""

    @model_validator(mode="after")
    def every_update_is_assessed_once(self) -> "RiskReport":
        ids = [assessment.update_id for assessment in self.assessments]
        if len(ids) != len(set(ids)):
            raise ValueError("an update is assessed more than once")
        return self

    @computed_field
    @property
    def by_level(self) -> dict[str, int]:
        counts = {"low": 0, "medium": 0, "high": 0}
        for assessment in self.assessments:
            counts[assessment.arbitration.final] += 1
        return counts

    @computed_field
    @property
    def disagreements(self) -> int:
        return sum(1 for assessment in self.assessments if assessment.disagreement)

    @computed_field
    @property
    def over_budget(self) -> int:
        return sum(
            1
            for assessment in self.assessments
            if assessment.latency.assessment_seconds > self.latency_budget_seconds
        )

    @computed_field
    @property
    def explanations_refused(self) -> int:
        """Model answers the check refused, each replaced by a rule written summary."""
        return sum(1 for assessment in self.assessments if assessment.explanation_refusal)

    @computed_field
    @property
    def evidence_incomplete(self) -> int:
        return sum(1 for assessment in self.assessments if not assessment.evidence_complete)
