"""The C4 back to C1 seam: what running in production taught the project.

A full draft. This is the edge that makes the pipeline a loop rather than a
line, and it is the one both earlier documents described in prose and never
named. Each item is evidence plus a suggested requirement, so a maintenance run
starts from something a human can accept or reject rather than from a metric.

Extended when C4 was built (2026-09-27): an item names the Semantic
Architecture Graph nodes it concerns, because the proposal's FR22 has C1 consume
this when it updates the graph for the next sprint, and names the report its
evidence came from, so a suggestion can be traced back to the probe or the
assessment that produced it.
"""

from typing import Literal

from pydantic import Field

from .ids import Traces
from .wire import WireDatetime, WireModel

FeedbackKind = Literal["dependency", "runtime", "security"]

#: Which C4 report the evidence came from.
FeedbackSource = Literal["monitoring", "risk-assessment", "release"]


class FeedbackItem(WireModel):
    id: str = Field(min_length=1)
    kind: FeedbackKind
    source: FeedbackSource
    summary: str = Field(min_length=1)
    #: What was observed, with its source, so the suggestion can be judged
    #: rather than taken on trust.
    evidence: str = Field(min_length=1)
    #: Where the evidence lives: an artefact kind and version, and the entry in
    #: it, such as `monitoring-report@3#down`.
    evidence_ref: str = ""
    #: Phrased as a requirement because that is what C1 consumes. A new run
    #: starts from this text.
    suggested_requirement: str = Field(min_length=1)
    #: The requirements this concerns, when it concerns existing ones.
    traces: Traces
    #: The Semantic Architecture Graph nodes this concerns.
    node_ids: list[str] = Field(default_factory=list)


class FeedbackReport(WireModel):
    report_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    generated_at: WireDatetime
    #: The deploy version whose release this report is about.
    deploy_version: int | None = Field(default=None, ge=1)
    #: The artefacts the items were derived from, as `kind@version`.
    source_reports: list[str] = Field(default_factory=list)
    items: list[FeedbackItem] = Field(default_factory=list)
