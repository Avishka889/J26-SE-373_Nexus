"""What monitoring saw of a release, over a window it names.

FR21 and Table 7. The orchestrator probes a live release in bounded windows,
never continuously, because a free host that is probed forever never sleeps and
spends its monthly hours on being watched. Each window becomes one report.

The platform's rule for any number on a screen applies here in the type: a
report names its `source` and its window, or it does not validate. A health
state without a window is a claim about a moment nobody can locate.

The rule that turns samples into states, `health-rule/1`, is `classify_window`
in `deploy_rules`. This contract fixes the shape it produces: named states in
ordered intervals inside the window, the current state being the last one, the
fingerprint the release was expected to serve beside what it served, and how
long the release had gone unasked when the window opened.
"""

from typing import Literal

from pydantic import Field, model_validator

from .deploy_plan import ReleaseTarget
from .deploy_rules import HEALTH_RULE, HealthState
from .wire import WireDatetime, WireModel

EventKind = Literal[
    "released",
    "verified",
    "degraded",
    "down",
    "recovered",
    "rollback-requested",
    "rollback-approved",
    "rolled-back",
    "rollback-failed",
]


class HealthThresholds(WireModel):
    """The numbers the health rule compares against, recorded with its verdict."""

    degraded_p95_ms: int = Field(default=2000, ge=1)
    #: A request after this much idle time on a free host may be a cold start.
    cold_start_idle_seconds: int = Field(default=900, ge=1)
    #: How slow a first request may be and still count as waking, not failing.
    #: Render documents a free web service's wake as "about one minute" (checked
    #: 2026-09-28); half as much again is allowed. After an idle spell, the first
    #: request of a window is given this long to answer.
    cold_start_first_ms: int = Field(default=90000, ge=1)
    min_samples: int = Field(default=3, ge=1)


class ProbeSummary(WireModel):
    """One kind of probe across the window."""

    #: The request, such as `GET /release.json`.
    probe: str = Field(min_length=1)
    samples: int = Field(ge=0)
    ok: int = Field(ge=0)
    p50_ms: float | None = Field(default=None, ge=0)
    p95_ms: float | None = Field(default=None, ge=0)
    last_error: str = ""

    @model_validator(mode="after")
    def ok_is_a_part_of_samples(self) -> "ProbeSummary":
        if self.ok > self.samples:
            raise ValueError(f"{self.probe}: more answers were ok than were sampled")
        return self


class StateInterval(WireModel):
    """One stretch of the window in one state, and what put it there."""

    state: HealthState
    start: WireDatetime
    end: WireDatetime
    samples: int = Field(ge=0)
    evidence: str = Field(min_length=1)


class DeploymentEvent(WireModel):
    at: WireDatetime
    kind: EventKind
    deployment_id: str = Field(min_length=1)
    detail: str = ""


class MonitoringReport(WireModel):
    """The `monitoring-report` artefact."""

    version: int = Field(ge=1)
    generated_at: WireDatetime
    deployment_id: str = Field(min_length=1)
    target: ReleaseTarget
    urls: list[str] = Field(min_length=1)
    #: Where every number here came from, such as "orchestrator HTTP probes
    #: every 30 s from this host". Required, by the platform's metric rule.
    source: str = Field(min_length=1)
    window_start: WireDatetime
    window_end: WireDatetime
    probe_interval_seconds: int = Field(ge=1)
    rule_id: Literal["health-rule/1"] = HEALTH_RULE
    thresholds: HealthThresholds = Field(default_factory=HealthThresholds)
    probes: list[ProbeSummary] = Field(default_factory=list)
    states: list[StateInterval] = Field(default_factory=list)
    current_state: HealthState
    expected_candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: None until a fingerprint probe answered.
    fingerprint_matches: bool | None = None
    events: list[DeploymentEvent] = Field(default_factory=list)
    #: How long the release had gone unasked by this platform when the window
    #: opened: since its last recorded probe, or since it was released. An upper
    #: bound on the host's own idle time, because traffic from anyone else is not
    #: seen. None when neither is on record.
    idle_seconds: float | None = Field(default=None, ge=0)
    idle_from: Literal["last-sample", "released", "given"] | None = None

    @model_validator(mode="after")
    def idle_time_says_where_it_came_from(self) -> "MonitoringReport":
        if (self.idle_seconds is None) != (self.idle_from is None):
            raise ValueError("an idle time names where it was measured from, and only then")
        return self

    @model_validator(mode="after")
    def the_states_fit_the_window(self) -> "MonitoringReport":
        if self.window_end < self.window_start:
            raise ValueError("the window ends before it starts")
        previous_end = self.window_start
        for interval in self.states:
            if interval.end < interval.start:
                raise ValueError(f"a {interval.state} interval ends before it starts")
            if interval.start < previous_end or interval.end > self.window_end:
                raise ValueError("state intervals overlap, run backwards, or leave the window")
            previous_end = interval.end
        last = self.states[-1].state if self.states else "unknown"
        if self.current_state != last:
            raise ValueError(
                f"the current state is {self.current_state}, but the last interval says {last}"
            )
        return self
