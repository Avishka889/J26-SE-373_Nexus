"""The candidate a release would ship, built and proved in a container first.

The staging stage installs the candidate from its lockfile, typechecks it, runs
its tests, builds it, boots it in a container and smoke tests it, and reads back
the fingerprint it serves. This is the preview in preview then promote: the
deployment review decides about a candidate that has already run, and the
release deploys exactly that candidate, by hash.

`verified` is computed, never set. It needs every step to have passed, an image
digest, the served fingerprint to equal the candidate hash, and at least one
smoke check with every one of them answering. A failed build is an outcome of
this stage, recorded as `verified = false`, not a failure of the stage: a
candidate that does not build is exactly what the staging step exists to find.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator

from .code_repository import BuildStepReport
from .ids import UpdateId
from .wire import WireDatetime, WireModel

ExclusionReason = Literal[
    "rejected",
    "deferred",
    "no-restore-target",
    "superseded",
    "out-of-scope",
]


class ExcludedUpdate(WireModel):
    """An update left out of the candidate, and why."""

    update_id: UpdateId
    reason: ExclusionReason
    detail: str = Field(min_length=1)


class SmokeCheck(WireModel):
    """One request against the booted candidate."""

    method: Literal["GET"] = "GET"
    path: str = Field(min_length=1)
    status_code: int | None = None
    ok: bool
    detail: str = ""


class ReleaseCandidate(WireModel):
    """The `release-candidate` artefact."""

    version: int = Field(ge=1)
    generated_at: WireDatetime
    code_version: int = Field(ge=1)
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    lockfile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    included: list[UpdateId] = Field(default_factory=list)
    excluded: list[ExcludedUpdate] = Field(default_factory=list)
    image: str = ""
    image_digest: str | None = None
    #: What ran the build, as the code repository's build report says it.
    toolchain: str = Field(min_length=1)
    isolation: str = Field(min_length=1)
    steps: list[BuildStepReport] = Field(min_length=1)
    smoke: list[SmokeCheck] = Field(default_factory=list)
    #: The candidate hash as the booted container served it in `release.json`.
    fingerprint: str | None = None

    @model_validator(mode="after")
    def an_update_is_in_or_out_never_both(self) -> "ReleaseCandidate":
        both = set(self.included) & {item.update_id for item in self.excluded}
        if both:
            raise ValueError(f"updates both included and excluded: {sorted(both)}")
        return self

    @computed_field
    @property
    def verified(self) -> bool:
        return (
            all(step.outcome == "passed" for step in self.steps)
            and bool(self.image_digest)
            and self.fingerprint == self.candidate_hash
            and bool(self.smoke)
            and all(check.ok for check in self.smoke)
        )
