"""Which files use what changed, and which architectural components those files are.

Signal three and the dissertation's second contribution (FR9 to FR11). The
changed symbols come from two places, each tagged: a deterministic API diff of
the two releases, and the symbols named in verified release note claims. The
project's code is indexed once per run (NFR2), every reference to a changed
symbol is re-read from the file before it counts, and every affected file is
mapped to Semantic Architecture Graph nodes through links that are recorded as
evidence, or listed as unmapped. Never guessed.

Three things are enforced here by shape:

**A reference is a span that was checked.** It carries an `EvidenceSpan`, the
same type the validation report uses, and one that did not resolve is a
`RefusedReference` with its reason, counted rather than dropped.

**The usage vote is the rule's.** `usage_level` over the kinds of the changed
symbols actually referenced, re-derived here. Nothing changed in use is low
project specific impact; no changed symbols known at all is an abstention.

**No affected file is silently lost.** Every affected file is either in some
component or in the unmapped list, so the component precision and recall of
Table 5 are computed over everything that was found.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator

from .deploy_rules import ChangeKind, usage_level
from .ids import Traces, UpdateId
from .risk_report import SignalVote
from .sag import GraphNodeKind
from .validation_report import EvidenceSpan
from .wire import WireDatetime, WireModel

SymbolSource = Literal["api-diff", "changelog"]
ApiDiffState = Literal["ran", "unavailable", "failed"]
MatchKind = Literal["import", "member", "identifier"]
ReferenceRefusal = Literal["file-not-found", "span-out-of-range", "snippet-does-not-match"]

#: How a file was tied to a component. `manifest-entity`: the generation
#: manifest says the file implements the entity. `endpoint-entity`: the file
#: implements an endpoint whose contract entity is the node. `build-module`: a
#: project without a graph, where the file sits under the module's build file.
LinkVia = Literal["manifest-entity", "endpoint-entity", "build-module"]

UnmappedReason = Literal[
    "not-in-manifest",
    "implements-nothing-mapped",
    "no-graph-node-matches",
    "graph-unavailable",
    "no-build-module",
]

#: `graph-node` for a platform project mapped through its Semantic Architecture
#: Graph; `module` for a project without one, where the component is its build
#: module. The two are never pooled in one number.
ComponentGranularity = Literal["graph-node", "module"]


class ExtractionRecord(WireModel):
    """The one index this run built, so a reader can see it was built once."""

    extraction_id: str = Field(min_length=1)
    parser: str = Field(min_length=1)
    grammars: list[str] = Field(default_factory=list)
    files_indexed: int = Field(ge=0)
    seconds: float = Field(ge=0)


class ChangedSymbol(WireModel):
    """One symbol an update changes, and who said so."""

    update_id: UpdateId
    symbol: str = Field(min_length=1)
    kind: ChangeKind
    source: SymbolSource
    #: The tool and version, or the claim id: `roseau 0.7.0`, `claim:c3`.
    tool: str = Field(min_length=1)
    detail: str = ""


class UsageReference(WireModel):
    """One place the project uses a changed symbol, checked against the file."""

    symbol: str = Field(min_length=1)
    symbol_kind: ChangeKind
    match: MatchKind
    span: EvidenceSpan


class RefusedReference(WireModel):
    """A reference that did not survive being re-read."""

    update_id: UpdateId
    path: str = Field(min_length=1)
    line: int | None = None
    reason: ReferenceRefusal
    detail: str = ""


class UpdateImpact(WireModel):
    """Signal three for one update."""

    update_id: UpdateId
    #: Whether any source file imports the package at all.
    imports_package: bool
    #: Named in a package script or a build configuration file, where a symbol
    #: search cannot see it but a build still depends on it.
    used_by_scripts: bool = False
    references: list[UsageReference] = Field(default_factory=list)
    #: Changed symbols the project was searched for and does not use.
    unreferenced: list[str] = Field(default_factory=list)
    api_diff: ApiDiffState
    api_diff_reason: str = ""
    vote: SignalVote
    #: How long this update's usage signal took, for NFR1: its API diff, its
    #: search and its read back, plus the whole index build, charged to every
    #: update rather than shared out, which is the cautious reading of the budget.
    seconds: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def the_vote_is_the_rules(self) -> "UpdateImpact":
        if self.vote.signal != "usage":
            raise ValueError("an update impact carries the usage vote")
        expected = usage_level(
            [reference.symbol_kind for reference in self.references],
            changed_symbols_known=bool(self.references or self.unreferenced),
        )
        if self.vote.level != expected:
            raise ValueError(
                f"the usage vote says {self.vote.level}; over these references the rule "
                f"says {expected}"
            )
        return self


class AffectedFile(WireModel):
    """A file that uses something an update changed."""

    path: str = Field(min_length=1)
    update_ids: list[UpdateId] = Field(min_length=1)
    reference_count: int = Field(ge=1)
    #: The generation stage that wrote the file, from the manifest.
    manifest_stage: str | None = None
    #: What the manifest says the file implements: endpoint ids, screen ids,
    #: entity names.
    implements: list[str] = Field(default_factory=list)


class ComponentLink(WireModel):
    """One recorded reason a file belongs to a component."""

    via: LinkVia
    path: str = Field(min_length=1)
    #: What made the link: the entity name, or the endpoint id and its entity.
    detail: str = Field(min_length=1)


class AffectedComponent(WireModel):
    """An architectural component an update reaches, and how that is known."""

    node_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: GraphNodeKind | Literal["module"]
    update_ids: list[UpdateId] = Field(min_length=1)
    files: list[str] = Field(min_length=1)
    links: list[ComponentLink] = Field(min_length=1)
    #: The requirement ids the graph node traces to, so a reader can jump to
    #: the requirement an update endangers.
    traces: Traces


class UnmappedFile(WireModel):
    """An affected file no component could honestly be named for."""

    path: str = Field(min_length=1)
    reason: UnmappedReason
    detail: str = ""


class ImpactReport(WireModel):
    """The `impact-report` artefact."""

    version: int = Field(ge=1)
    generated_at: WireDatetime
    code_version: int = Field(ge=1)
    #: The design version behind the code version, whose graph was read.
    design_version: int | None = None
    granularity: ComponentGranularity = "graph-node"
    extraction: ExtractionRecord
    changed_symbols: list[ChangedSymbol] = Field(default_factory=list)
    per_update: list[UpdateImpact] = Field(default_factory=list)
    affected_files: list[AffectedFile] = Field(default_factory=list)
    affected_components: list[AffectedComponent] = Field(default_factory=list)
    unmapped_files: list[UnmappedFile] = Field(default_factory=list)
    refused_references: list[RefusedReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def every_affected_file_is_accounted_for(self) -> "ImpactReport":
        affected = {item.path for item in self.affected_files}
        referenced = {
            reference.span.path for impact in self.per_update for reference in impact.references
        }
        if affected != referenced:
            raise ValueError(
                "the affected files must be exactly the files a checked reference is in: "
                f"missing {sorted(referenced - affected)}, extra {sorted(affected - referenced)}"
            )
        mapped = {path for component in self.affected_components for path in component.files}
        if not mapped <= affected:
            raise ValueError(
                f"components name files nothing referenced: {sorted(mapped - affected)}"
            )
        unmapped = {item.path for item in self.unmapped_files}
        lost = affected - mapped - unmapped
        if lost:
            raise ValueError(
                f"affected files are neither mapped nor listed as unmapped: {sorted(lost)}"
            )
        return self

    @computed_field
    @property
    def refused_count(self) -> int:
        return len(self.refused_references)
