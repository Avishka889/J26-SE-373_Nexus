"""A labelled case: one dependency update, one client, and what was observed when it was applied.

The label is not stored. What is stored is what happened (the steps that ran
against the installed version and against the update, their outcomes, the
warning lines, where a failure pointed) and the level is derived from that by
the rubric at load time. A case says how it was observed, by which toolchain,
and where its inputs came from, so a number in a table can be traced to the run
that produced it.

The split is not stored either: it is a function of the update's key, so a case
cannot drift from one side to the other when the corpus is reorganised.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator
from sdlc_contracts import update_key
from sdlc_contracts.wire import WireModel

from .split import held_out

CaseSource = Literal[
    "bump",
    "bump-crossing",
    "maven-negative",
    "npm-platform",
    "npm-seeded",
    "npm-venturini",
    "hand",
]

ObservationMethod = Literal[
    "bump-recorded", "venturini-recorded", "container-reproduction", "platform-staging"
]

StepName = Literal["resolution", "compile", "typecheck", "test", "build", "boot", "health", "smoke"]

#: `unavailable` is a step that failed because a download did, which says
#: nothing about the project or the update.
StepOutcome = Literal["passed", "failed", "not-run", "timed-out", "unavailable"]


class ObservedStep(WireModel):
    name: StepName
    command: str = ""
    exit_code: int | None = None
    outcome: StepOutcome
    seconds: float | None = Field(default=None, ge=0)
    log_sha256: str = ""
    #: The last lines of the step's output, kept so a failure can be read.
    tail: str = ""


class FailureLocation(WireModel):
    """Where an observed failure pointed, such as a compiler error's file and line."""

    path: str = Field(min_length=1)
    line: int | None = None


class Observed(WireModel):
    """What happened when the update was applied, against what happened without it."""

    method: ObservationMethod
    #: When it was observed, as a date.
    captured_at: str = Field(min_length=1)
    toolchain: str = ""
    #: The run at the installed version: the control. A case whose control is
    #: already broken says nothing about the update and is excluded.
    baseline: list[ObservedStep] = Field(default_factory=list)
    #: The run at the target version.
    candidate: list[ObservedStep] = Field(min_length=1)
    #: Warning or deprecation lines that appeared with the update and not
    #: without it, and name the package or a changed symbol.
    warnings: list[str] = Field(default_factory=list)
    #: BUMP's category, when the case comes from BUMP.
    failure_category: str = ""
    #: How many times the case was observed to get runs no download failure
    #: cut short. Only the last observation is stored; earlier ones are not
    #: results, because a lost download says nothing about the update.
    attempts: int = Field(default=1, ge=1)
    failure_locations: list[FailureLocation] = Field(default_factory=list)


class CaseClient(WireModel):
    kind: Literal["github", "platform", "seeded", "npm-package"]
    repo_url: str = ""
    commit: str = ""
    #: A published npm package at one version, such as `env-cmd@9.0.1`, read from
    #: the registry's tarball: exactly what was published.
    package_spec: str = ""
    #: A reproduction image, when one exists.
    image: str = ""
    #: A client frozen in this repository, as a path under `studies/clients/`,
    #: and the hash of its files, so a rerun can tell it is the same client.
    snapshot: str = ""
    snapshot_sha256: str = ""


class CaseUpdate(WireModel):
    ecosystem: Literal["npm", "maven"]
    package: str = Field(min_length=1)
    from_version: str = Field(min_length=1)
    to_version: str = Field(min_length=1)
    #: Every manifest that declares the package; an update moves it in each.
    manifest_paths: list[str] = Field(default_factory=list)
    scope: str = ""

    @property
    def key(self) -> str:
        return update_key(self.ecosystem, self.package, self.from_version, self.to_version)


class LabelledCase(WireModel):
    case_id: str = Field(min_length=1)
    source: CaseSource
    client: CaseClient
    update: CaseUpdate
    #: What the dataset itself called the change, such as BUMP's
    #: `versionUpdateType`, kept beside the rule's own reading.
    source_change: str = ""
    observed: Observed
    #: Inputs frozen at capture, url to sha256, so a re-fetch can detect an edit.
    frozen_inputs: dict[str, str] = Field(default_factory=dict)
    #: Where the case came from, in words: the loader, the dataset and its commit.
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def the_update_is_a_change(self) -> "LabelledCase":
        if self.update.from_version == self.update.to_version:
            raise ValueError(f"case {self.case_id} updates {self.update.package} to itself")
        return self

    @computed_field
    @property
    def split(self) -> Literal["dev", "held-out"]:
        return "held-out" if held_out(self.update.key) else "dev"
