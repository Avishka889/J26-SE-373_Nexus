"""Feedback (FR22): what a window and an assessment suggest for requirements, by `feedback-rule/1`.

Monitoring reports are written here state by state; the dependency side uses a
real reference (the Express `app.del` case the usage tests read) and a risk
report from the real assessment, so the rule is checked against the shapes it
will be given rather than against hand made ones that might not validate.
"""

from datetime import UTC, datetime, timedelta

from c4.feedback import FEEDBACK_RULE, dependency_items, derive, item_id, runtime_items
from c4.risk import assess
from c4.service import C4
from sdlc_contracts import (
    AffectedComponent,
    AffectedFile,
    ComponentLink,
    ExtractionRecord,
    ImpactReport,
    MonitoringReport,
    ProbeSummary,
    StateInterval,
)

from .test_assessment import _changelog, _update, _updates
from .test_usage_signal import APP, _impact, _symbol

NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
EXPRESS = _update("express", old="4.21.2", new="5.1.0", change="major")
UNUSED = _update("left-pad", old="1.0.0", new="2.0.0", change="major")


def _window(state: str, *, evidence: str = "", probes=(), idle: float | None = None, at=NOW):
    return MonitoringReport(
        version=3,
        generated_at=at + timedelta(minutes=10),
        deployment_id="d-3",
        target="cloud",
        urls=["https://app.example"],
        source="orchestrator HTTP probes from this host, 20 rounds 30s apart",
        window_start=at,
        window_end=at + timedelta(minutes=10),
        probe_interval_seconds=30,
        probes=list(probes),
        states=[
            StateInterval(
                state=state,
                start=at,
                end=at + timedelta(minutes=10),
                samples=20,
                evidence=evidence or f"the window found it {state}",
            )
        ],
        current_state=state,
        expected_candidate_hash="a" * 64,
        idle_seconds=idle,
        idle_from="last-sample" if idle is not None else None,
    )


def _probe(path: str, *, ok: int = 20, samples: int = 20, p95: float | None = 80.0, error=""):
    return ProbeSummary(
        probe=f"GET {path}", samples=samples, ok=ok, p50_ms=40.0, p95_ms=p95, last_error=error
    )


def _impact_report() -> ImpactReport:
    """`src/app.ts` calls `server.del`, which Express 5 removed; the file is the Items API."""
    symbol = _symbol(EXPRESS, "app.del")
    impact, _ = _impact(EXPRESS, {"src/app.ts": APP}, symbol)
    return ImpactReport(
        version=3,
        generated_at=NOW,
        code_version=2,
        extraction=ExtractionRecord(
            extraction_id="x-1", parser="tree-sitter", files_indexed=1, seconds=0.1
        ),
        changed_symbols=[symbol],
        per_update=[impact],
        affected_files=[
            AffectedFile(path="src/app.ts", update_ids=[EXPRESS.id], reference_count=1)
        ],
        affected_components=[
            AffectedComponent(
                node_id="n-items",
                label="Items API",
                kind="service",
                update_ids=[EXPRESS.id],
                files=["src/app.ts"],
                links=[
                    ComponentLink(
                        via="manifest-entity", path="src/app.ts", detail="implements Item"
                    )
                ],
                traces=["R-2", "R-4"],
            )
        ],
    )


class TestWhatAWindowSuggests:
    def test_a_healthy_or_unknown_window_suggests_nothing(self) -> None:
        assert runtime_items(_window("healthy"), fault_injected=None) == []
        assert runtime_items(_window("unknown"), fault_injected=None) == []

    def test_a_release_found_down_asks_for_availability(self) -> None:
        [item] = runtime_items(
            _window("down", evidence="the last 3 rounds of probes all failed"),
            fault_injected=None,
        )
        assert (item.kind, item.source) == ("runtime", "monitoring")
        assert item.evidence_ref == "monitoring-report@3#down"
        assert item.evidence.startswith("The last 3 rounds of probes all failed")
        assert "keep answering every page and API request" in item.suggested_requirement

    def test_a_slow_request_is_named_with_its_threshold(self) -> None:
        window = _window("degraded", probes=[_probe("/tasks", p95=3400.0), _probe("/")])
        [item] = runtime_items(window, fault_injected=None)
        assert item.evidence_ref == "monitoring-report@3#slow:GET /tasks"
        assert "3400 ms at the 95th percentile" in item.evidence
        assert item.suggested_requirement == (
            "GET /tasks shall answer within 2 s at the 95th percentile."
        )

    def test_a_request_that_failed_sometimes_is_named(self) -> None:
        window = _window("degraded", probes=[_probe("/tasks", ok=17, error="None ")])
        [item] = runtime_items(window, fault_injected=None)
        assert item.evidence_ref == "monitoring-report@3#failing:GET /tasks"
        assert "failed 3 of 20 requests" in item.evidence

    def test_the_platforms_fingerprint_is_never_a_requirement(self) -> None:
        """Book Tracker's window suggested "GET https://p-57370cfbc78f.vercel.app/
        release.json shall answer within 2 s": a platform file, at a host the
        next release replaces, in the application's requirements."""
        window = _window(
            "degraded",
            probes=[_probe("https://p-1.vercel.app/release.json", p95=2606.0, ok=19), _probe("/")],
        )
        [item] = runtime_items(window, fault_injected=None)
        assert item.evidence_ref == "monitoring-report@3#degraded"
        assert "release.json" not in item.suggested_requirement

    def test_a_requirement_names_the_route_not_the_host(self) -> None:
        window = _window(
            "degraded", probes=[_probe("https://p-1.vercel.app/api/tasks", p95=3400.0)]
        )
        [item] = runtime_items(window, fault_injected=None)
        assert item.summary == "GET /api/tasks was slow on deploy version 3."
        assert item.suggested_requirement == (
            "GET /api/tasks shall answer within 2 s at the 95th percentile."
        )
        # The evidence keeps the address it was measured at.
        assert "https://p-1.vercel.app/api/tasks" in item.evidence

    def test_degraded_with_no_one_request_to_blame_is_one_item_for_the_window(self) -> None:
        [item] = runtime_items(_window("degraded", probes=[_probe("/")]), fault_injected=None)
        assert item.evidence_ref == "monitoring-report@3#degraded"

    def test_a_slow_wake_asks_for_a_first_answer_in_time(self) -> None:
        [item] = runtime_items(_window("cold-start", idle=1200.0), fault_injected=None)
        assert "after 20 idle minutes within 2 s" in item.suggested_requirement

    def test_a_controlled_failure_says_so_in_what_it_suggests(self) -> None:
        [item] = runtime_items(_window("down"), fault_injected="stop-container")
        assert item.summary.startswith("In a controlled failure (`stop-container`): ")
        assert item.evidence.startswith("In a controlled failure (`stop-container`): ")

    def test_the_same_evidence_in_a_later_window_is_the_same_item(self) -> None:
        first = runtime_items(_window("down"), fault_injected=None)
        later = runtime_items(_window("down", at=NOW + timedelta(hours=3)), fault_injected=None)
        assert [item.id for item in first] == [item.id for item in later]
        assert first[0].id == item_id("runtime", "monitoring", "down")


class TestWhatAnAssessmentSuggests:
    def test_a_high_update_the_code_uses_names_its_components_and_requirements(self) -> None:
        impact = _impact_report()
        risk = assess.report(
            _updates(EXPRESS), _changelog((EXPRESS, "removal", "high")), impact, version=3
        )

        [item] = dependency_items(risk, impact)

        assert (item.kind, item.source) == ("dependency", "risk-assessment")
        assert item.node_ids == ["n-items"] and item.traces == ["R-2", "R-4"]
        assert item.evidence_ref == f"risk-report@3#{EXPRESS.id}"
        assert "app.del" in item.evidence and "src/app.ts" in item.evidence
        assert item.suggested_requirement == (
            "Items API shall be changed to work with express 5.1.0, which changes app.del."
        )

    def test_a_high_update_nothing_uses_is_a_release_decision_not_a_requirement(self) -> None:
        impact = _impact_report()
        risk = assess.report(
            _updates(EXPRESS, UNUSED),
            _changelog((EXPRESS, "removal", "high"), (UNUSED, "removal", "high")),
            impact,
            version=3,
        )

        items = dependency_items(risk, impact)

        assert [item.evidence_ref for item in items] == [f"risk-report@3#{EXPRESS.id}"]


class TestTheReport:
    def test_it_names_every_report_its_items_came_from(self) -> None:
        impact = _impact_report()
        risk = assess.report(
            _updates(EXPRESS), _changelog((EXPRESS, "removal", "high")), impact, version=3
        )

        report = derive(_window("down"), risk, impact, project_id="p1", deploy_version=3, now=NOW)

        assert report.source_reports == ["monitoring-report@3", "risk-report@3", "impact-report@3"]
        assert [item.kind for item in report.items] == ["runtime", "dependency"]

    async def test_the_component_answers_with_the_rule_and_a_count(self) -> None:
        answer = await C4("deepseek:deepseek-flash").summarise_feedback(
            _window("down"), None, None, project_id="p1", deploy_version=3
        )
        assert answer.notes == {"rule": FEEDBACK_RULE, "items": 1}
        assert answer.summary.startswith("1 suggestion(s) for requirements")
