"""What updates exist for a project's dependencies, and what is known about each.

The first C4 artefact, and the proposal's FR1 to FR3: the updates the
registries offer (FR1), the metadata retrieved for each (FR2), and every update
that could not be analysed, with the reason in words a developer can act on
(FR3). A rejection is a first class row rather than an absence: the study counts
coverage, and an update that vanished from the report would flatter the engine
with the cases it could not handle.

**The version change is a fact, not a vote.** `change` says what moved between
the two numbers. The SemVer rule's level is derived from it by
`deploy_rules.semver_level`, and the risk report re-derives it, so nobody can
record a patch that the rule calls high.

**Release notes are snapshotted, not linked.** Every text a model will be asked
to quote from is stored with its sha256 when it is read, because the check that
refuses an invented quote has to run against exactly the text the model saw.
Upstream notes get edited; a quote verified against today's copy of last
month's notes proves nothing.
"""

import hashlib
from typing import Literal

from pydantic import Field, computed_field, model_validator

from .deploy_rules import VersionChange
from .ids import UpdateId
from .wire import WireDatetime, WireModel

Ecosystem = Literal["npm", "maven"]

#: Where a dependency is declared. npm's and Maven's own words, kept distinct
#: rather than mapped onto each other, because a test scoped Maven dependency and
#: an npm dev dependency are not the same risk to a deployed application.
DependencyScope = Literal[
    "prod",
    "dev",
    "peer",
    "optional",
    "compile",
    "test",
    "runtime",
    "provided",
    "plugin",
    "import",
    "system",
]

#: `in-range` is the newest release the declared range already admits;
#: `latest` is the registry's latest, which may need the range widened.
CandidateKind = Literal["in-range", "latest"]

#: Facts about the two numbers that the SemVer rule does not use and a reader
#: should see. `initial-development` is a 0.y.z source, where SemVer itself says
#: anything may change; the rule still maps by position, and the flag says so.
VersionFlag = Literal["initial-development", "prerelease-target", "build-metadata", "qualifier"]

NoteSource = Literal["github-release", "changelog-file", "migration-guide"]

#: FR3's reasons, each of which the detail sentence expands.
RejectionReason = Literal[
    "package-not-found",
    "version-not-found",
    "not-a-registry-dependency",
    "registry-unreachable",
    "unresolvable-version",
    "not-an-upgrade",
    "unsupported-ecosystem",
]

Sha256 = str


def update_key(ecosystem: Ecosystem, package: str, from_version: str, to_version: str) -> str:
    """The readable name of an update: `npm:express@4.21.2->5.1.0`."""
    return f"{ecosystem}:{package}@{from_version}->{to_version}"


def update_id_for(key: str) -> str:
    """The URL safe id an update is addressed by, stable across deploy versions."""
    return "u-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


class RegistryQuery(WireModel):
    """One question asked of a registry, and whether it answered.

    Recorded so that "no newer version" can be told apart from "the registry
    was not reachable", which read the same in a list of updates.
    """

    registry: str = Field(min_length=1)
    url: str = Field(min_length=1)
    at: WireDatetime
    #: The HTTP status, or None when nothing answered at all.
    status: int | None = None
    note: str = ""


class ReleaseNoteRef(WireModel):
    """One release note text, as read, with where the stored copy lives."""

    source: NoteSource
    url: str = Field(min_length=1)
    #: The release the text belongs to. A changelog file covers many; its
    #: windowed section is stored, and this names the newest release in it.
    version: str = Field(min_length=1)
    #: Where the snapshot is stored among the deployment files.
    path: str = Field(min_length=1)
    sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    chars: int = Field(ge=0)
    #: True when the text was cut to fit, so a reader knows a quote may exist
    #: beyond what the model was shown.
    truncated: bool = False


class TransitiveShift(WireModel):
    """A package the update moves without being asked to, seen in the lockfile.

    `added` and `removed` are a package appearing in or leaving the tree, which
    is not a move between two versions and is not given a SemVer name.
    """

    package: str = Field(min_length=1)
    from_version: str | None = None
    to_version: str | None = None
    change: VersionChange | Literal["added", "removed"]


class DependencyUpdate(WireModel):
    """One update the registry offers, and everything retrieved about it."""

    id: UpdateId
    key: str = Field(min_length=1)
    ecosystem: Ecosystem
    package: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    manifest_line: int | None = Field(default=None, ge=1)
    #: Other manifests that declare the same package at the same installed
    #: version. It is one update, assessed and decided once, and a candidate
    #: applies it in every one of them, or a release would ship it half applied.
    also_declared_in: list[str] = Field(default_factory=list)
    scope: DependencyScope
    #: The range or version as the manifest declares it, `^4.3.0` or `2.7.3`.
    declared: str = Field(min_length=1)
    from_version: str = Field(min_length=1)
    to_version: str = Field(min_length=1)
    candidate: CandidateKind
    #: A newer release than this candidate, when one exists: the in range
    #: candidate beside a latest that needs the range widened.
    superseded_by: str | None = None
    change: VersionChange
    flags: list[VersionFlag] = Field(default_factory=list)
    published_at: WireDatetime | None = None
    repository_url: str | None = None
    notes: list[ReleaseNoteRef] = Field(default_factory=list)
    #: Why the release notes could not be read when a source refused to answer
    #: (GitHub's rate limit), so that is never reported as a release without
    #: notes. Empty when notes were read, or when there were none to read.
    notes_unavailable: str = ""
    transitive: list[TransitiveShift] = Field(default_factory=list)

    @model_validator(mode="after")
    def the_name_and_the_id_say_the_same_thing(self) -> "DependencyUpdate":
        expected = update_key(self.ecosystem, self.package, self.from_version, self.to_version)
        if self.key != expected:
            raise ValueError(f"the key {self.key!r} does not name this update ({expected!r})")
        if self.id != update_id_for(self.key):
            raise ValueError(f"the id {self.id!r} is not the hash of its key")
        if self.change == "downgrade":
            raise ValueError(
                "a downgrade is not an update; it is rejected with `not-an-upgrade` instead"
            )
        return self


class RejectedUpdate(WireModel):
    """An update that could not be analysed, and why (FR3)."""

    package: str = Field(min_length=1)
    ecosystem: Ecosystem
    manifest_path: str = Field(min_length=1)
    declared: str = Field(min_length=1)
    from_version: str | None = None
    to_version: str | None = None
    reason: RejectionReason
    #: The descriptive message FR3 requires: what was asked, what came back.
    detail: str = Field(min_length=1)


class BaselinePin(WireModel):
    """The exact dependency set the analysis starts from.

    The generated projects carry no lockfile and caret ranges throughout, so
    until this was recorded nothing said which versions the tested build had
    installed. A rollback that restores "the previous release" restores this.
    """

    lockfile_path: str = Field(min_length=1)
    lockfile_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    packages: int = Field(ge=0)
    direct: int = Field(ge=0)
    #: The command that produced it, with the tool's version.
    resolved_by: str = Field(min_length=1)


class DependencyUpdates(WireModel):
    """The `dependency-updates` artefact: one deploy version's view of the registries."""

    #: The deploy version this was produced at.
    version: int = Field(ge=1)
    generated_at: WireDatetime
    code_version: int = Field(ge=1)
    test_version: int = Field(ge=1)
    #: `generated`, or `sample:<name>` for a checked in sample project.
    target: str = Field(min_length=1)
    baseline: BaselinePin | None = None
    updates: list[DependencyUpdate] = Field(default_factory=list)
    rejected: list[RejectedUpdate] = Field(default_factory=list)
    #: Packages already at the newest release, named so that a short list of
    #: updates is visibly short rather than possibly truncated.
    up_to_date: list[str] = Field(default_factory=list)
    queried: list[RegistryQuery] = Field(default_factory=list)

    @model_validator(mode="after")
    def every_update_is_listed_once(self) -> "DependencyUpdates":
        ids = [update.id for update in self.updates]
        if len(ids) != len(set(ids)):
            raise ValueError("an update is listed more than once")
        return self

    @computed_field
    @property
    def rejected_count(self) -> int:
        return len(self.rejected)
