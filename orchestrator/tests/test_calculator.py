"""The calculator corpus, end to end, twice.

One input of five words, through the real component, the real graph, the real
store and the real read model, and then the assembled snapshot is read as a whole.

Twice, because the two runs answer different questions. The golden pass fixes the
model's answers and so tests our code: if a stage summary were written from a
template copied out of demo data, or the read model fell back to a seed, or a
prompt carried an example the pipeline then stored, the leakage guard fires here
and it fires deterministically. The live pass uses a real provider and so tests
the prompts: whether a model given five words invents thirty confident
requirements, and whether anything it writes belongs to somebody else's product.

The assertions are shared, and most of them are about restraint rather than
capability. A thin input should produce a handful of requirements with the gaps
named, a small graph, a monolith out of arithmetic and at most three questions.
Producing more than that from five words is the failure this corpus exists to
catch.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from c1.rules.confidence import LOW_CONFIDENCE_BELOW
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.c1 import InProcessC1
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests
from sdlc_contracts import ARTEFACT_STAGE_IDS, DesignSnapshot

from .calculator_script import calculator_model
from .conftest import needs_db
from .corpus import (
    CALCULATOR_INPUT,
    MIN_ARITHMETIC_WORDS,
    assert_grounded,
    assert_no_leakage,
    grounding,
)

#: This file drives a whole design run against a real database, so it belongs
#: behind the same gate as every other test that does. Without the marker the
#: `settings` fixture asserted its way to nine errors when the compose database
#: was down, while its neighbours skipped cleanly: a test that cannot run
#: should say so the way the others do rather than failing the suite.
pytestmark = needs_db


async def _run_the_calculator(client: httpx.AsyncClient) -> tuple[str, dict]:
    """Start a project from the one line input and take it to the gate."""
    created = (
        await client.post("/projects", json={"name": "Calculator", "description": "A calculator."})
    ).json()
    project_id = created["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]

    # The requirement text arriving is the whole start signal: there is no
    # separate "run the pipeline" call.
    await client.patch(f"/projects/{project_id}", json={"requirementText": CALCULATOR_INPUT})
    run = (await client.get("/runs", params={"project": project_id})).json()[0]

    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(run["id"])
    # Five words leave questions, and the design asks them before it builds the
    # rest. This corpus reads the whole design, so it goes on with the
    # assumptions, which leaves the questions open as they were.
    if (await client.get(f"/projects/{project_id}/design")).json()["questionsPending"]:
        continued = await client.post(
            f"/projects/{project_id}/design/questions/continue", json={"kind": "assumptions"}
        )
        assert continued.status_code == 200, continued.text
        await supervisor.advance(run["id"])

    snapshot = (await client.get(f"/projects/{project_id}/design")).json()
    return project_id, snapshot


async def _everything_said(client: httpx.AsyncClient, project_id: str, snapshot: dict) -> dict:
    """The snapshot plus the other places a leak could surface.

    The audit log especially. Its detail lines are written by us from templates,
    which makes them one of the likeliest carriers and one of the least likely to
    be looked at.
    """
    audit = (await client.get("/audit", params={"project": project_id})).json()
    runs = (await client.get("/runs", params={"project": project_id})).json()
    project = (await client.get(f"/projects/{project_id}")).json()
    return {"snapshot": snapshot, "audit": audit, "runs": runs, "project": project}


def assert_a_restrained_design(snapshot: dict) -> None:
    """What five words should and should not produce.

    Shared by both passes. Bands rather than exact counts: pinning the number of
    requirements would be pinning the answer, and the claim is about the size of
    the answer rather than its contents.
    """
    DesignSnapshot.model_validate(snapshot)

    requirements = snapshot["requirements"]
    # Only the ceiling is a claim. Five words describing a calculator contain one
    # stated requirement, and a real model returns exactly that: demanding a
    # second would be demanding that it invent one, which is the failure this
    # corpus exists to catch rather than a standard to hold it to. What the gaps
    # become is an assumption or a question, asserted below.
    assert 1 <= len(requirements) <= 8, (
        f"{len(requirements)} requirements from five words is not a handful"
    )

    # The honest response to a thin input is to say what was assumed and to ask,
    # not to fill the gaps with confident detail.
    assert snapshot["assumptions"], "a five word input should have produced assumptions"
    assert len(snapshot["questions"]) <= 3, "more than three open questions is a form to fill in"

    # Confidence is computed from checkable properties, so a requirement read
    # from a real sentence has to outscore one that was worked out.
    #
    # Neither kind is required to be present, and that is not a weakened
    # assertion. Five words may honestly yield nothing quotable: "a user enters
    # numbers" is not in the sentence "Build a simple calculator app", and the
    # component's own instructions prefer marking that inferred over pointing at
    # a sentence that does not say it. Demanding one of each would be demanding
    # the model cite something that is not there.
    read = [r for r in requirements if r["sourceQuote"]]
    inferred = [r for r in requirements if not r["sourceQuote"]]
    if read and inferred:
        assert min(r["confidence"] for r in read) > max(r["confidence"] for r in inferred), (
            "an inferred requirement scored as high as one that was read"
        )
    assert all(r["confidence"] <= 98 for r in requirements), "nothing read from prose is certain"

    # Whatever it landed on, the analysis decides what counts as low rather than
    # leaving the client to pick a threshold. On an input this thin most of these
    # should be flagged, and a run where none is has stopped being honest about
    # how much it was working from.
    for r in requirements:
        assert r["lowConfidence"] == (r["confidence"] < LOW_CONFIDENCE_BELOW), (
            f"{r['id']} is at {r['confidence']} and lowConfidence is {r['lowConfidence']}"
        )

    # A small design, and every part of it traceable to something asked for.
    graph = snapshot["graph"]
    assert 2 <= len(graph["nodes"]) <= 8, f"{len(graph['nodes'])} nodes is not a calculator"
    known = {r["id"] for r in requirements}
    for node in graph["nodes"]:
        assert node["traces"], f"node {node['id']} traces to nothing"
        assert set(node["traces"]) <= known, f"node {node['id']} traces outside the requirements"
    for edge in graph["edges"]:
        assert set(edge["traces"]) <= known

    # The recommendation is arithmetic over the design, and for this design the
    # arithmetic has one obvious answer. The margin is not asserted: a correct
    # answer is allowed to be a confident one.
    architecture = snapshot["architecture"]
    assert architecture["recommendedCandidateId"] == "modular-monolith"
    assert architecture["selectedCandidateId"] is None, "nobody has chosen yet"
    assert architecture["style"]["id"] == "layered", "a calculator needs no more than layers"
    assert len({c["score"] for c in architecture["candidates"]}) > 1, "every shape scored the same"
    for candidate in architecture["candidates"]:
        assert len(candidate["cons"]) >= 2, f"{candidate['id']} shipped with only upside"

    # Every stage a component produces finished and said so.
    for stage_id in ARTEFACT_STAGE_IDS:
        assert snapshot["stages"][stage_id]["status"] == "complete", f"{stage_id} did not finish"
        assert snapshot["stages"][stage_id]["summary"]

    # Coverage is derived at read time from two artefacts that never saw each
    # other, so a row that reads covered is a real agreement.
    coverage = snapshot["wireframes"]["coverage"]
    assert coverage, "no stories to cover, or no coverage computed"
    assert any(row["covered"] for row in coverage), "not one story has a screen"

    # Nothing in the assembled design disagrees with anything else in it.
    errors = [f for f in snapshot["consistency"] if f["severity"] == "error"]
    assert not errors, f"the artefacts disagree: {[f['reason'] for f in errors]}"

    # The plan estimates and never reports.
    sprint = snapshot["sprint"]
    assert sprint["proposed"], "no stories proposed"
    assert sprint["estimatedPoints"] == sum(s["points"] for s in sprint["proposed"])
    assert "not measured" in sprint["velocityAssumption"]["basis"]
    for story in sprint["proposed"]:
        assert story["points"] in {1, 2, 3, 5, 8, 13, 21}
        assert story["acceptance"], f"{story['id']} cannot be told apart from unfinished"


@pytest.fixture
async def golden_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """The whole system with the model's answers fixed.

    The real component, built the way it is built in production, with a scripted
    model in place of a provider. Everything else is real, which is what makes a
    failure here a failure in our code.
    """
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    app.state.c1 = InProcessC1(calculator_model())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            created: list[str] = []
            c.created_projects = created  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


class TestTheGoldenCase:
    """Fixed answers, so this tests our code rather than the model."""

    async def test_five_words_produce_a_restrained_design(
        self, golden_client: httpx.AsyncClient
    ) -> None:
        _, snapshot = await _run_the_calculator(golden_client)
        assert_a_restrained_design(snapshot)

    async def test_nothing_from_another_project_reaches_the_snapshot(
        self, golden_client: httpx.AsyncClient
    ) -> None:
        project_id, snapshot = await _run_the_calculator(golden_client)
        everything = await _everything_said(golden_client, project_id, snapshot)

        assert_no_leakage(everything)
        # The pairing that matters. Without this an empty snapshot passes the
        # guard above, and an empty snapshot is the likeliest way this breaks.
        assert_grounded(everything)

    async def test_the_grounding_check_would_notice_an_empty_design(
        self, golden_client: httpx.AsyncClient
    ) -> None:
        # Proving the mirror assertion is not vacuous, which is the whole reason
        # it exists. If this passed on nothing, so would the test above.
        with pytest.raises(AssertionError):
            assert_grounded({"snapshot": {"requirements": [], "graph": {"nodes": []}}})

    async def test_the_leakage_guard_would_notice_a_seed_bleeding_through(
        self, golden_client: httpx.AsyncClient
    ) -> None:
        # The same, for the guard itself. A guard nobody has seen fail is a guard
        # that might be searching the wrong text.
        _, snapshot = await _run_the_calculator(golden_client)
        snapshot["stages"]["wireframes"]["summary"] = "2 flows covering the payment journey"
        with pytest.raises(AssertionError, match="payment"):
            assert_no_leakage(snapshot)

    @pytest.mark.parametrize(
        "where,plant",
        [
            (
                "the velocity basis",
                lambda e: e["snapshot"]["sprint"]["velocityAssumption"].update(
                    {"basis": "measured on the shopflow team"}
                ),
            ),
            ("an audit detail", lambda e: e["audit"][0].update({"detail": "for patient records"})),
            (
                "a thread message",
                lambda e: e["snapshot"]["thread"][0].update({"content": "refund flow generated"}),
            ),
            (
                "a stage summary",
                lambda e: e["snapshot"]["stages"]["sprint-plan"].update(
                    {"summary": "3 stories for the checkout"}
                ),
            ),
        ],
    )
    async def test_it_searches_the_places_nobody_thinks_of_as_content(
        self, golden_client: httpx.AsyncClient, where: str, plant
    ) -> None:
        # A leak is most likely somewhere unglamorous, and every one of these is
        # a real field we write from a template. Planting one proves the guard
        # walks the whole structure rather than a list of fields somebody
        # remembered.
        project_id, snapshot = await _run_the_calculator(golden_client)
        everything = await _everything_said(golden_client, project_id, snapshot)
        assert_no_leakage(everything)

        plant(everything)
        with pytest.raises(AssertionError):
            assert_no_leakage(everything)

    async def test_the_arithmetic_words_are_found_in_the_real_output(
        self, golden_client: httpx.AsyncClient
    ) -> None:
        # Reported rather than only asserted, so a run that scrapes past the
        # threshold is visible instead of silently passing.
        project_id, snapshot = await _run_the_calculator(golden_client)
        everything = await _everything_said(golden_client, project_id, snapshot)
        names_it, found = grounding(everything)

        print(f"\ncalculator named: {names_it}; arithmetic words: {found}")
        assert len(found) >= MIN_ARITHMETIC_WORDS


@pytest.mark.live
class TestAgainstARealModel:
    """The same assertions, with the prompts on trial instead of the code."""

    @pytest.fixture
    async def live_client(
        self, settings: Settings, allow_live_requests, live_model_name: str
    ) -> AsyncIterator[httpx.AsyncClient]:
        app = create_app(settings, lifespan_factory=lifespan_for_tests)
        # Entered here, so the provider connections are closed when the test
        # finishes. Without it every live test passed and the process still
        # exited non-zero on a ResourceWarning, which makes "the live suite is
        # green" something a person has to decide rather than a script.
        async with InProcessC1(live_model_name) as c1:
            app.state.c1 = c1
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                    c.app = app  # type: ignore[attr-defined]
                    created: list[str] = []
                    c.created_projects = created  # type: ignore[attr-defined]
                    try:
                        yield c
                    finally:
                        async with app.state.pool.connection() as conn:
                            for project_id in created:
                                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)

    async def test_a_real_model_given_five_words_stays_restrained(
        self, live_client: httpx.AsyncClient
    ) -> None:
        project_id, snapshot = await _run_the_calculator(live_client)
        everything = await _everything_said(live_client, project_id, snapshot)

        # Report before asserting, and report defensively. A leaf stage is
        # allowed to fail at runtime, so this must print the reason rather than
        # crash on a missing artefact: a diagnostic that dies on the failure it
        # is meant to explain is worse than none.
        print(f"\ninput: {CALCULATOR_INPUT!r}")
        for stage_id in ARTEFACT_STAGE_IDS:
            stage = snapshot["stages"][stage_id]
            mark = "" if stage["status"] == "complete" else f"  <-- {stage['status']}"
            print(f"  {stage_id:30} {stage['summary'] or stage['error'] or ''}{mark}")

        for r in snapshot["requirements"]:
            how = "read" if r["sourceQuote"] else "inferred"
            print(f"  {r['id']} [{how} {r['confidence']}] {r['text']}")
        for a in snapshot["assumptions"]:
            print(f"  assumed: {a['text']}")
        for q in snapshot["questions"]:
            print(f"  asking: {q['question']}")

        graph = snapshot["graph"]
        print(f"  graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
        for node in graph["nodes"]:
            print(f"    {node['id']} {node['kind']:10} {node['label']}")
        if snapshot["architecture"]:
            scores = [(c["id"], c["score"]) for c in snapshot["architecture"]["candidates"]]
            print(f"  shape: {snapshot['architecture']['recommendedCandidateId']} {scores}")
            print(f"  style: {snapshot['architecture']['style']['name']}")
        if snapshot["sprint"]:
            print(
                f"  screens: {sum(len(f['screens']) for f in snapshot['wireframes']['flows'])}, "
                f"stories: {len(snapshot['sprint']['proposed'])}, "
                f"points: {snapshot['sprint']['estimatedPoints']}"
            )
        for f in snapshot["consistency"]:
            print(f"  {f['severity']}: {f['reason']}")

        assert_a_restrained_design(snapshot)
        assert_no_leakage(everything)
        assert_grounded(everything)
