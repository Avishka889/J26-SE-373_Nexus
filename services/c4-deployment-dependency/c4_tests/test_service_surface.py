"""The component's surface.

A stage that is not built says so and names the phase it lands in, rather than
returning something empty a reader could take for a result. Every stage is built
now, so the rule is held by a component that claims one is not, and each stage's
own tests hold what it does. The HTTP app validates every body into contract
types and turns the two non-results into statuses the orchestrator's client can
read back.
"""

from datetime import datetime

import httpx
import pytest
from c4.app import create_app
from c4.service import C4, NotApplicable, NotBuilt, StageAnswer
from sdlc_contracts import DependencyUpdates, MonitoringReport

WHEN = datetime(2026, 9, 27, 12, 0)
UPDATES = DependencyUpdates(
    version=1, generated_at=WHEN, code_version=1, test_version=1, target="generated"
)

#: Stage, the phase it lands in, and a call that reaches it.
MONITORING = MonitoringReport(
    version=1,
    generated_at=WHEN,
    deployment_id="d-1",
    target="local",
    urls=["http://127.0.0.1:18080"],
    source="scripted",
    window_start=WHEN,
    window_end=WHEN,
    probe_interval_seconds=30,
    current_state="unknown",
    expected_candidate_hash="0" * 64,
)


class _Unbuilt(C4):
    """A component with its feedback stage not built, as it was until Phase 6."""

    async def summarise_feedback(self, *args, **kwargs) -> StageAnswer:
        raise NotBuilt("feedback", "Phase 6")


async def test_an_unbuilt_stage_says_so_and_when() -> None:
    with pytest.raises(NotBuilt) as raised:
        await _Unbuilt("deepseek:deepseek-flash").summarise_feedback(
            MONITORING, None, None, project_id="p", deploy_version=1
        )
    assert (raised.value.stage, raised.value.phase) == ("feedback", "Phase 6")
    assert "Nothing was run" in str(raised.value)


def test_the_component_names_its_model_and_its_targets() -> None:
    c4 = C4("deepseek:deepseek-flash")
    assert c4.model == "deepseek:deepseek-flash"
    assert [target["id"] for target in c4.targets()] == ["generated"]


@pytest.fixture
async def http():
    app = create_app(C4("deepseek:deepseek-flash"))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://c4") as client:
            yield client


async def test_the_service_answers_its_health_check(http) -> None:
    answer = await http.get("/health")
    assert answer.json() == {"status": "ok", "model": "deepseek:deepseek-flash"}


async def test_a_body_that_is_not_the_contract_is_refused(http) -> None:
    answer = await http.post("/stages/risk-assessment", json={"version": 1, "updates": {}})
    assert answer.status_code == 422


async def test_an_unbuilt_stage_answers_501_with_its_phase() -> None:
    app = create_app(_Unbuilt("deepseek:deepseek-flash"))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://c4") as client:
            answer = await client.post(
                "/stages/feedback",
                json={
                    "monitoring": MONITORING.model_dump(by_alias=True, mode="json"),
                    "projectId": "p",
                    "deployVersion": 1,
                },
            )
    assert answer.status_code == 501
    assert answer.json()["phase"] == "Phase 6"


async def test_the_feedback_stage_answers_over_the_wire(http) -> None:
    answer = await http.post(
        "/stages/feedback",
        json={
            "monitoring": MONITORING.model_dump(by_alias=True, mode="json"),
            "projectId": "p",
            "deployVersion": 1,
            "faultInjected": "stop-container",
        },
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["artefact"]["items"] == []


class _NothingToDo(C4):
    async def assess_risk(self, *args, **kwargs) -> StageAnswer:
        raise NotApplicable("risk-assessment", "there are no updates to assess")


async def test_a_stage_with_nothing_to_do_answers_409_and_says_why() -> None:
    app = create_app(_NothingToDo("deepseek:deepseek-flash"))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://c4") as client:
            answer = await client.post(
                "/stages/risk-assessment",
                json={"version": 1, "updates": UPDATES.model_dump(by_alias=True, mode="json")},
            )
    assert answer.status_code == 409
    assert answer.json() == {
        "detail": "there are no updates to assess",
        "stage": "risk-assessment",
        "notApplicable": True,
    }


class TestNpmKeepsItsCache:
    """The pin and the candidate's resolution both run npm, and both are given the
    cache the service keeps in its cache directory; with no directory, npm gets a
    scratch cache per run, as it always had."""

    @staticmethod
    def _spied(monkeypatch) -> list:
        from c4.intake import lockfile
        from c4.pipeline import candidate

        from .test_detect import PIN
        from .test_pipeline_generation import _scripted

        given: list = []

        def pin(files, *, cache=None):
            given.append(("pin", cache))
            return PIN

        def resolve(files, updates, *, cache=None):
            given.append(("resolve", cache))
            return _scripted()(files, updates)

        monkeypatch.setattr(lockfile, "pin", pin)
        monkeypatch.setattr(candidate, "resolve", resolve)
        return given

    @staticmethod
    async def _run(component: C4) -> None:
        from sdlc_contracts import RiskReport

        from .test_detect import FILES
        from .test_pipeline_generation import CONTRACT, SUPERTEST, TRACKER
        from .test_pipeline_generation import UPDATES as TRACKER_UPDATES

        await component.detect_updates(
            FILES, target="generated", version=1, code_version=1, test_version=1
        )
        await component.generate_pipeline(
            TRACKER,
            TRACKER_UPDATES,
            RiskReport.model_construct(),
            stack_id="mern",
            contract=CONTRACT,
            release_target="local",
            included=[SUPERTEST.id],
            settings={"project_id": "p", "project_slug": "p-1"},
            version=2,
            code_version=3,
        )

    async def test_both_npm_runs_are_given_the_kept_cache(self, monkeypatch, tmp_path) -> None:
        from .test_detect import ROUTES, _registry
        from .test_pipeline_generation import _no_linters

        given = self._spied(monkeypatch)
        component = C4(
            "deepseek:deepseek-flash",
            http=httpx.AsyncClient(transport=_registry(ROUTES)),
            cache_dir=str(tmp_path),
            validator=_no_linters,
        )
        await self._run(component)
        assert component.npm_cache == tmp_path / "npm"
        assert given == [("pin", tmp_path / "npm"), ("resolve", tmp_path / "npm")]

    async def test_without_a_cache_directory_npm_keeps_nothing(self, monkeypatch) -> None:
        from .test_detect import ROUTES, _registry
        from .test_pipeline_generation import _no_linters

        given = self._spied(monkeypatch)
        component = C4(
            "deepseek:deepseek-flash",
            http=httpx.AsyncClient(transport=_registry(ROUTES)),
            validator=_no_linters,
        )
        await self._run(component)
        assert component.npm_cache is None
        assert given == [("pin", None), ("resolve", None)]
