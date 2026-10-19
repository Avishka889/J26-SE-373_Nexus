"""Feedback (FR22, M5): what a release taught, phrased as requirements C1 can accept or reject.

`feedback-rule/1`, a rule and not a model: every item is evidence the platform
recorded, phrased as a requirement, naming the report entry it came from and,
where that evidence names them, the Semantic Architecture Graph nodes and the
requirements it concerns. Nothing here is sent anywhere. A person decides item
by item, and only an item they send becomes a design change note for C1's next
run.

From a monitoring window (source `monitoring`, kind `runtime`):

- `down`: the release stopped serving what was verified;
- `degraded`: each request whose p95 was over the threshold, and each request
  that failed in some rounds; when no single request accounts for it, one item
  for the window;
- `cold-start`: the host woke slowly after an idle spell.

`healthy` and `unknown` teach nothing and give no item.

From the risk and impact reports (source `risk-assessment`, kind `dependency`):
each High update the project's own code is found using, naming the components
and requirements the impact analysis linked those files to. A High from SemVer
alone, with nothing in the project using what changed, is a release decision the
review already took, not a requirement.

A window over a release a controlled failure was injected into still gives its
items, marked as such in their summary and evidence, so the loop can be shown
without anyone mistaking a planned outage for a lesson from production.

An item's id is a hash of what it is about, not of when it was seen, so the
same evidence in a later window is the same item and a decision taken on it
still applies.
"""

import hashlib
from datetime import UTC, datetime

from sdlc_contracts import (
    FeedbackItem,
    FeedbackReport,
    ImpactReport,
    MonitoringReport,
    RiskReport,
)

FEEDBACK_RULE = "feedback-rule/1"


def item_id(*about: str) -> str:
    return "fb-" + hashlib.sha256("|".join(about).encode()).hexdigest()[:12]


def _is_fingerprint(probe: str) -> bool:
    """`GET https://host/release.json`: the platform's check of which release answers."""
    return probe.split("?", 1)[0].endswith("/release.json")


def _route(probe: str) -> str:
    """`GET https://p-1.vercel.app/tasks` as `GET /tasks`.

    A requirement is about the application, wherever it is deployed: the host
    in it named the platform's deployment, which the next release replaces.
    """
    method, _, target = probe.partition(" ")
    if "://" in target:
        target = "/" + target.split("://", 1)[1].partition("/")[2]
    return f"{method} {target}".strip()


def _injected(fault: str | None) -> str:
    return f"In a controlled failure (`{fault}`): " if fault else ""


def runtime_items(
    monitoring: MonitoringReport, *, fault_injected: str | None
) -> list[FeedbackItem]:
    """What one monitoring window says about the running application."""
    state = monitoring.current_state
    version = monitoring.version
    evidence = monitoring.states[-1].evidence if monitoring.states else state
    window = f"{monitoring.source}; {monitoring.window_start:%Y-%m-%d %H:%M} UTC"
    prefix = _injected(fault_injected)
    items: list[FeedbackItem] = []

    def add(about: str, summary: str, observed: str, requirement: str) -> None:
        items.append(
            FeedbackItem(
                id=item_id("runtime", "monitoring", about),
                kind="runtime",
                source="monitoring",
                summary=prefix + summary,
                evidence=f"{prefix}{observed} ({window}).",
                evidence_ref=f"monitoring-report@{version}#{about}",
                suggested_requirement=requirement,
                traces=[],
            )
        )

    threshold = monitoring.thresholds.degraded_p95_ms
    if state == "down":
        add(
            "down",
            f"Deploy version {version} stopped serving its verified release.",
            evidence[0].upper() + evidence[1:],
            "The application shall keep answering every page and API request it was released "
            "with, and a release that stops answering shall be restored to the last verified "
            "release once a person approves.",
        )
    elif state == "degraded":
        # The application's own requests only: the fingerprint is the
        # platform's file, and a requirement about it would ask the app to
        # serve something it never wrote.
        own = [probe for probe in monitoring.probes if not _is_fingerprint(probe.probe)]
        slow = [probe for probe in own if probe.p95_ms is not None and probe.p95_ms > threshold]
        failing = [probe for probe in own if probe.ok < probe.samples]
        for probe in slow:
            route = _route(probe.probe)
            add(
                f"slow:{probe.probe}",
                f"{route} was slow on deploy version {version}.",
                f"{probe.probe} answered in {probe.p95_ms:.0f} ms at the 95th percentile over "
                f"{probe.samples} requests, over the {threshold} ms threshold",
                f"{route} shall answer within {threshold / 1000:g} s at the 95th percentile.",
            )
        for probe in failing:
            route = _route(probe.probe)
            add(
                f"failing:{probe.probe}",
                f"{route} failed some requests on deploy version {version}.",
                f"{probe.probe} failed {probe.samples - probe.ok} of {probe.samples} requests"
                + (f", the last with {probe.last_error}" if probe.last_error else ""),
                f"{route} shall answer every request while the application is released.",
            )
        if not slow and not failing:
            add(
                "degraded",
                f"Deploy version {version} was degraded.",
                evidence[0].upper() + evidence[1:],
                f"Every request the application was released with shall answer within "
                f"{threshold / 1000:g} s at the 95th percentile.",
            )
    elif state == "cold-start":
        idle = monitoring.idle_seconds
        add(
            "cold-start",
            f"The host of deploy version {version} woke slowly after an idle spell.",
            evidence[0].upper() + evidence[1:],
            "The application shall answer its first request after "
            + (f"{idle / 60:.0f} idle minutes" if idle else "an idle spell")
            + f" within {monitoring.thresholds.degraded_p95_ms / 1000:g} s, or its hosting "
            "shall keep it awake.",
        )
    return items


def dependency_items(risk: RiskReport, impact: ImpactReport | None) -> list[FeedbackItem]:
    """Each High update the project's own code uses, with where the code is."""
    used = {
        entry.update_id: entry
        for entry in (impact.per_update if impact else [])
        if entry.references
    }
    items: list[FeedbackItem] = []
    for assessment in risk.assessments:
        if assessment.arbitration.final != "high" or assessment.update_id not in used:
            continue
        references = used[assessment.update_id].references
        symbols = sorted({reference.symbol for reference in references})
        files = sorted({reference.span.path for reference in references})
        components = [
            component
            for component in (impact.affected_components if impact else [])
            if assessment.update_id in component.update_ids
        ]
        where = (
            ", ".join(component.label for component in components)
            if components
            else f"{len(files)} file(s)"
        )
        traces = sorted({trace for component in components for trace in component.traces})
        items.append(
            FeedbackItem(
                id=item_id("dependency", "risk-assessment", assessment.key),
                kind="dependency",
                source="risk-assessment",
                summary=(
                    f"{assessment.package} {assessment.from_version} to {assessment.to_version} "
                    f"is High risk, and the project uses what it changes."
                ),
                evidence=(
                    f"{len(references)} use(s) of {', '.join(symbols)} in {', '.join(files)}; "
                    f"decided by {', '.join(assessment.arbitration.decided_by) or 'no signal'}"
                    + (
                        f". {assessment.arbitration.advisory}"
                        if assessment.arbitration.advisory
                        else ""
                    )
                    + "."
                ),
                evidence_ref=f"risk-report@{risk.version}#{assessment.update_id}",
                suggested_requirement=(
                    f"{where} shall be changed to work with {assessment.package} "
                    f"{assessment.to_version}, which changes {', '.join(symbols)}."
                ),
                traces=traces,
                node_ids=[component.node_id for component in components],
            )
        )
    return items


def derive(
    monitoring: MonitoringReport,
    risk: RiskReport | None,
    impact: ImpactReport | None,
    *,
    project_id: str,
    deploy_version: int,
    fault_injected: str | None = None,
    now: datetime | None = None,
) -> FeedbackReport:
    """`feedback-rule/1` over one window and the assessment of the release it watched."""
    items = runtime_items(monitoring, fault_injected=fault_injected)
    sources = [f"monitoring-report@{monitoring.version}"]
    if risk is not None:
        items += dependency_items(risk, impact)
        sources.append(f"risk-report@{risk.version}")
    if impact is not None:
        sources.append(f"impact-report@{impact.version}")
    return FeedbackReport(
        report_id=f"feedback-{project_id}-v{deploy_version}",
        project_id=project_id,
        generated_at=now or datetime.now(UTC),
        deploy_version=deploy_version,
        source_reports=sources,
        items=items,
    )
