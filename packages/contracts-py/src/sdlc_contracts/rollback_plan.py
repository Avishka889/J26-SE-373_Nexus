"""The rollback prepared before a release: where it would return to, and how that is checked.

FR19 and FR20. A rollback plan is written for every release before the release
runs, naming the previous verified release a restore would return to, the steps
that would do it, and the checks that decide whether it did. Approval is not a
setting: `approval` has one value, `required`, because FR20 lets only a human
start a rollback and a plan that could say otherwise would be one edit away from
an automatic one.

**A restore returns to a release that was verified, or nowhere.** A plan with no
verified release behind it is not restorable and says why, and every High update
on such a release is marked unavailable, which the release guards refuse: FR17
asks for a prepared rollback and there is nothing to prepare one from.

**Restored means the fingerprint is back.** Every restorable plan carries a
fingerprint check, so the guard that reports a rollback restored compares what
is served with what was verified, rather than trusting that a redeploy finished.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator

from .deploy_plan import ProviderId, ReleaseTarget, TargetRole
from .ids import UpdateId
from .remediation_proposal import RiskLevel
from .wire import WireDatetime, WireModel

CheckKind = Literal["fingerprint", "health", "smoke"]

UpdateRollbackStatus = Literal["prepared", "not-required", "unavailable"]


class VerifiedRelease(WireModel):
    """A release that passed verification where it runs, which a restore can return to."""

    deployment_id: str = Field(min_length=1)
    deploy_version: int = Field(ge=1)
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    lockfile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    target: ReleaseTarget
    image_digest: str | None = None
    commit_sha: str | None = None
    render_deploy_id: str | None = None
    vercel_deployment_id: str | None = None
    url: str | None = None
    verified_at: WireDatetime


class RestoreStep(WireModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    provider: ProviderId
    #: What the step does, in words a reviewer can check.
    action: str = Field(min_length=1)
    moves_traffic: bool = False
    #: A provider limit that bears on the step, such as how far back its own
    #: rollback can reach.
    constraint: str = ""


class VerificationCheck(WireModel):
    id: str = Field(min_length=1)
    kind: CheckKind
    role: TargetRole
    #: What passing looks like: the hash expected, the status expected.
    expect: str = Field(min_length=1)


class UpdateRollback(WireModel):
    """Whether a rollback is prepared for one update, as FR17 and FR19 require."""

    update_id: UpdateId
    level: RiskLevel
    status: UpdateRollbackStatus
    reason: str = ""

    @model_validator(mode="after")
    def high_is_prepared_or_says_why_not(self) -> "UpdateRollback":
        if self.level == "high" and self.status == "not-required":
            raise ValueError("a high update always needs a prepared rollback (FR17)")
        if self.status == "unavailable" and not self.reason.strip():
            raise ValueError("an unavailable rollback must say why")
        return self


class RollbackPlan(WireModel):
    """The `rollback-plan` artefact."""

    version: int = Field(ge=1)
    generated_at: WireDatetime
    #: The candidate this plan would roll back from.
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy: Literal["application-only"] = "application-only"
    approval: Literal["required"] = "required"
    restore_target: VerifiedRelease | None = None
    restorable: bool
    unrestorable_reason: str = ""
    steps: list[RestoreStep] = Field(default_factory=list)
    checks: list[VerificationCheck] = Field(default_factory=list)
    updates: list[UpdateRollback] = Field(default_factory=list)
    provider_constraints: list[str] = Field(default_factory=list)
    #: What a restore does to data. The generated projects keep data in memory,
    #: so a restore starts them empty, and a reviewer should know that first.
    data_note: str = ""

    @model_validator(mode="after")
    def restorable_means_there_is_somewhere_to_go(self) -> "RollbackPlan":
        if self.restorable:
            if self.restore_target is None or not self.steps:
                raise ValueError("a restorable plan names a verified release and the steps to it")
            if not any(check.kind == "fingerprint" for check in self.checks):
                raise ValueError(
                    "a restorable plan checks the served fingerprint, or restored means nothing"
                )
            if self.restore_target.candidate_hash == self.candidate_hash:
                raise ValueError("a plan cannot restore the candidate it would roll back from")
        elif not self.unrestorable_reason.strip():
            raise ValueError("a plan that cannot restore must say why")
        if not self.restorable and any(item.status == "prepared" for item in self.updates):
            raise ValueError("no update can have a prepared rollback when the plan cannot restore")
        return self

    @computed_field
    @property
    def blocks(self) -> list[str]:
        """High updates whose rollback is unavailable, which the release guards refuse."""
        return [
            item.update_id
            for item in self.updates
            if item.level == "high" and item.status == "unavailable"
        ]
