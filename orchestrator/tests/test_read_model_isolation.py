"""C2 rows must not crash or corrupt the C1 read model.

The design snapshot types its stages and thread messages over the eight design
stage ids and reads "the" gate decision. All three were written when C1's rows
were the only rows. These tests plant code phase shaped rows next to a real
project and assert the design snapshot still composes, still validates, and
still reads its status from the design gate rather than the code one.

Found by planning rather than by an incident, which is the cheap way round.
"""

import importlib.util
import uuid
from pathlib import Path
from typing import get_args

import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.readmodel.assemble import compose, project_view
from orchestrator.readmodel.code import compose_code
from sdlc_contracts import (
    ARTEFACT_KINDS,
    CODE_ARTEFACT_KINDS,
    CODE_OVERLAY_KINDS,
    CODE_STAGE_IDS,
    DEPLOY_ARTEFACT_KINDS,
    DEPLOY_OVERLAY_KINDS,
    DEPLOY_STAGE_IDS,
    DESIGN_STAGE_IDS,
    TEST_ARTEFACT_KINDS,
    TEST_OVERLAY_KINDS,
    TEST_STAGE_IDS,
    CodeSnapshot,
    DesignSnapshot,
)

from .conftest import DATABASE_URL, needs_db

pytestmark = needs_db


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url=DATABASE_URL, database_direct_url=DATABASE_URL)


@pytest.fixture
async def pool(settings: Settings):
    from orchestrator.db.pool import create_app_pool

    pool = create_app_pool(settings.database_url, max_size=2)
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        await pool.close()


async def _project_with_c2_rows(conn) -> str:
    project = await store.create_project(conn, name="Isolation case", owner_id=DEV_OWNER_ID)
    project_id = project["id"]

    # Version 1 opened first. A gate is recorded against the version it decides,
    # and the snapshot reports the decision covering the version the project is
    # on, so a project left at version 0 with a gate at version 1 is a state no
    # run can produce: the decision would rightly read as covering something
    # else. Planting it was harmless while the read model reported the newest
    # decision whatever its version, and that was the bug.
    await store.open_version(conn, project_id, note=None, by="A. Chen", applied=True)

    # A resolved design gate, so the design status has a real source.
    design_run = await store.create_run(
        conn, project_id=project_id, requirements_version=1, component="c1"
    )
    design_gate = await store.open_gate(
        conn,
        run_id=design_run["id"],
        project_id=project_id,
        requirements_version=1,
        payload={},
        interrupt_id=str(uuid.uuid4()),
        kind="c1-design-review",
    )
    await store.resolve_gate(conn, design_gate["id"], decision="approved", by="A. Chen", note=None)

    # Now everything a C2 run would leave behind. The stage row is a raw
    # INSERT: set_stage is an UPDATE and only the design rows are seeded at
    # project creation, so going through the store would silently plant
    # nothing and every assertion below would pass against an empty threat.
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO app.stage_states (project_id, stage_id, status, summary)
            VALUES (%s, 'build', 'complete', 'Built')
            """,
            (project_id,),
        )
    await store.post_thread_message(
        conn,
        project_id,
        kind="stage_summary",
        author="Code agent",
        content="2 workspaces typechecked",
        stage_id="build",
    )
    # A valid artefact, not a placeholder. The design snapshot never reads this
    # kind, so `{"candidates": []}` sat here unnoticed until the code snapshot,
    # which does read it, refused the whole compose: a fixture that cannot be
    # composed proves nothing about composing.
    await store.put_artefact(
        conn,
        project_id=project_id,
        kind="tech-stack",
        version=1,
        body={
            "candidates": [
                {
                    "id": "mern",
                    "name": "MERN",
                    "layers": [{"name": "backend", "choice": "Express"}],
                    "score": 60,
                }
            ],
            "recommendedId": "mern",
        },
    )
    code_run = await store.create_run(
        conn, project_id=project_id, requirements_version=1, component="c2"
    )
    code_gate = await store.open_gate(
        conn,
        run_id=code_run["id"],
        project_id=project_id,
        requirements_version=1,
        payload={},
        interrupt_id=str(uuid.uuid4()),
        kind="c2-code-review",
    )
    # Resolved later than the design gate, and differently: if the design
    # snapshot reads this row, its status and decision both go wrong.
    await store.resolve_gate(
        conn, code_gate["id"], decision="changes", by="A. Chen", note="tighten the api"
    )
    return project_id


class TestTheDesignSnapshotIgnoresCodeRows:
    async def test_it_composes_validates_and_keeps_its_own_gate(self, pool) -> None:
        async with pool.connection() as conn:
            project_id = await _project_with_c2_rows(conn)
            try:
                project = await store.get_project(conn, project_id, owner_id=DEV_OWNER_ID)
                snapshot = await compose(conn, project)

                # It validates, which the unfiltered version did not survive.
                DesignSnapshot.model_validate(snapshot.model_dump(by_alias=True))

                # Exactly the eight design stages, no build row.
                assert set(snapshot.stages) == set(DESIGN_STAGE_IDS)

                # The code stage summary stays out of the design thread.
                assert all("typechecked" not in m.content for m in snapshot.thread)

                # The decision is the design gate's, not the later code gate's.
                assert snapshot.gate.decision is not None
                assert snapshot.gate.decision.kind == "approved"

                # And the status ladder still reads from the design gate: the
                # code gate here was resolved with changes, not approved, so
                # the project stays at code.
                facts = await store.project_progress(
                    conn, owner_id=DEV_OWNER_ID, project_id=project_id
                )
                assert project_view(facts[project_id])["status"] == "code"

                # Through the list path too, which aggregates in SQL.
                progress = await store.project_progress(conn, owner_id=DEV_OWNER_ID)
                row = progress[project_id]
                assert bool(row["approved"]) is True
                assert bool(row["code_approved"]) is False
            finally:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)

    async def test_an_approved_code_review_reads_as_testing(self, pool) -> None:
        """The rung itself, end to end through the one derivation.

        Planted as a run leaves it: design version 1 applied, code version 1
        written from it, each approved at its own review. Approvals with no
        version behind them were enough while any approval ever counted.
        """
        async with pool.connection() as conn:
            project = await store.create_project(conn, name="Testing rung", owner_id=DEV_OWNER_ID)
            project_id = project["id"]
            try:
                await store.open_version(conn, project_id, note=None, by="A. Chen", applied=True)
                await store.put_artefact(
                    conn, project_id=project_id, kind="api-contract", version=1, body={}
                )
                for kind, decision in (
                    ("c1-design-review", "approved"),
                    ("c2-code-review", "approved"),
                ):
                    run = await store.create_run(
                        conn,
                        project_id=project_id,
                        requirements_version=1,
                        component="c1" if kind.startswith("c1") else "c2",
                        source_version=None if kind.startswith("c1") else 1,
                    )
                    gate = await store.open_gate(
                        conn,
                        run_id=run["id"],
                        project_id=project_id,
                        requirements_version=1,
                        payload={},
                        interrupt_id=str(uuid.uuid4()),
                        kind=kind,
                    )
                    await store.resolve_gate(
                        conn, gate["id"], decision=decision, by="A. Chen", note=None
                    )

                progress = await store.project_progress(conn, owner_id=DEV_OWNER_ID)
                assert project_view(progress[project_id])["status"] == "testing"
            finally:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)

    async def test_a_code_artefact_kind_is_storable_at_all(self, pool) -> None:
        """The migration's whole point: before 0004 this INSERT violated the
        CHECK constraint."""
        async with pool.connection() as conn:
            project = await store.create_project(conn, name="Check width", owner_id=DEV_OWNER_ID)
            try:
                for kind in CODE_ARTEFACT_KINDS:
                    await store.put_artefact(
                        conn, project_id=project["id"], kind=kind, version=1, body={}
                    )
                stored = await store.latest_artefacts(conn, project["id"])
                assert set(CODE_ARTEFACT_KINDS) <= set(stored)
            finally:
                await store.delete_project(conn, project["id"], owner_id=DEV_OWNER_ID)


class TestTheMigrationMatchesTheVocabulary:
    """The CHECK lists in the migrations and the Literal types must be the
    same sets, or a kind is writable that the contract does not know, or vice
    versa.

    The newest migration defining a list wins, because a later one widens what
    an earlier one wrote: pinning the test to a file number meant the check
    silently stopped describing the database the first time a CHECK was
    rewritten.
    """

    @staticmethod
    def _newest_defining(attribute: str):
        versions = (
            Path(__file__).resolve().parents[1] / "orchestrator" / "db" / "migrations" / "versions"
        )
        found = None
        for path in sorted(versions.glob("[0-9]*.py")):
            spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, attribute):
                found = module
        assert found is not None, f"no migration defines {attribute}"
        return found

    def test_artefact_kinds(self) -> None:
        migration = self._newest_defining("ARTEFACT_KINDS")
        assert set(migration.ARTEFACT_KINDS) == (
            set(ARTEFACT_KINDS)
            | set(CODE_ARTEFACT_KINDS)
            | set(TEST_ARTEFACT_KINDS)
            | set(DEPLOY_ARTEFACT_KINDS)
        )

    def test_overlay_kinds(self) -> None:
        migration = self._newest_defining("OVERLAY_KINDS")
        c1_overlays = set(get_args(store.OverlayKind))
        assert set(migration.OVERLAY_KINDS) == (
            c1_overlays
            | set(CODE_OVERLAY_KINDS)
            | set(TEST_OVERLAY_KINDS)
            | set(DEPLOY_OVERLAY_KINDS)
        )


async def _project_with_c3_rows(conn) -> str:
    """A project carrying testing phase rows beside its design and code ones."""
    project_id = await _project_with_c2_rows(conn)

    # Raw INSERT for the same reason the C2 fixture uses one: set_stage is an
    # UPDATE, and only the design rows are seeded at project creation, so going
    # through the store would plant nothing and every assertion below would
    # pass against an empty threat.
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO app.stage_states (project_id, stage_id, status, summary)
            VALUES (%s, 'security-scan', 'complete', '3 findings, 1 high')
            """,
            (project_id,),
        )
    await store.post_thread_message(
        conn,
        project_id,
        kind="stage_summary",
        author="Security agent",
        content="scanned 41 files, three origins agreed on one finding",
        stage_id="security-scan",
    )
    await store.put_artefact(
        conn,
        project_id=project_id,
        kind="validation-report",
        version=1,
        body={"findings": []},
    )
    test_run = await store.create_run(
        conn, project_id=project_id, requirements_version=1, component="c3"
    )
    gate = await store.open_gate(
        conn,
        run_id=test_run["id"],
        project_id=project_id,
        requirements_version=1,
        payload={},
        interrupt_id=str(uuid.uuid4()),
        kind="c3-test-review",
    )
    # Resolved differently again, so a read model that picks up the wrong row
    # gets a visibly wrong answer rather than a coincidentally right one.
    await store.resolve_gate(conn, gate["id"], decision="approved", by="Someone Else", note=None)
    return project_id


@needs_db
class TestTheEarlierSnapshotsIgnoreTestingRows:
    """A C3 row must not reach the C1 or C2 snapshot.

    The same hazard C2 had, checked before C3 can produce a row rather than
    after: both snapshots type their stages and thread messages over their own
    stage ids, and both read "the" gate decision. A testing stage id, a testing
    thread message or a testing gate reaching either one is a validation error
    at best and a wrong status at worst.
    """

    async def test_the_design_snapshot_composes_and_keeps_its_own_gate(self, pool) -> None:
        async with pool.connection() as conn:
            project_id = await _project_with_c3_rows(conn)
            try:
                project = await store.get_project(conn, project_id, owner_id=DEV_OWNER_ID)
                snapshot = await compose(conn, project)

                DesignSnapshot.model_validate(snapshot.model_dump(by_alias=True))
                assert set(snapshot.stages) == set(DESIGN_STAGE_IDS)
                assert all("three origins" not in m.content for m in snapshot.thread)
                assert snapshot.gate.decision is not None
                assert snapshot.gate.decision.by == "A. Chen", (
                    "the design snapshot read another phase's decision"
                )
            finally:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)

    async def test_the_code_snapshot_composes_and_keeps_its_own_gate(self, pool) -> None:
        async with pool.connection() as conn:
            project_id = await _project_with_c3_rows(conn)
            try:
                project = await store.get_project(conn, project_id, owner_id=DEV_OWNER_ID)
                snapshot = await compose_code(conn, project)

                CodeSnapshot.model_validate(snapshot.model_dump(by_alias=True))
                assert set(snapshot.stages) == set(CODE_STAGE_IDS)
                assert all("three origins" not in m.content for m in snapshot.thread)
                decided_by = [d.by for d in [snapshot.gate.decision, *snapshot.gate.history] if d]
                assert "Someone Else" not in decided_by, (
                    "the code snapshot read the testing gate's decision"
                )
            finally:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _project_with_c4_rows(conn) -> str:
    """A project carrying deployment rows beside every earlier phase's."""
    project_id = await _project_with_c3_rows(conn)
    async with conn.cursor() as cur:
        # The C3 fixture's report is a placeholder the earlier snapshots never
        # parse; this test composes the testing snapshot too, so it goes.
        await cur.execute(
            "DELETE FROM app.artefacts WHERE project_id = %s AND kind = 'validation-report'",
            (project_id,),
        )
        await cur.execute(
            """
            INSERT INTO app.stage_states (project_id, stage_id, status, summary)
            VALUES (%s, 'risk-assessment', 'complete', '1 high, 1 medium, 1 low')
            """,
            (project_id,),
        )
    # One deploy artefact, so the phase has a version and its gate decision at
    # that version is the one the snapshot reads.
    await store.put_artefact(
        conn,
        project_id=project_id,
        kind="feedback",
        version=1,
        body={"reportId": "f1", "projectId": project_id, "generatedAt": "2026-09-27 12:00"},
    )
    await store.post_thread_message(
        conn,
        project_id,
        kind="stage_summary",
        author="Deployment agent",
        content="three signals disagreed and the cautious one won",
        stage_id="risk-assessment",  # type: ignore[arg-type]
    )
    deploy_run = await store.create_run(
        conn, project_id=project_id, requirements_version=1, component="c4", source_version=1
    )
    gate = await store.open_gate(
        conn,
        run_id=deploy_run["id"],
        project_id=project_id,
        requirements_version=1,
        payload={},
        interrupt_id=str(uuid.uuid4()),
        kind="c4-deploy-review",
    )
    await store.resolve_gate(conn, gate["id"], decision="approved", by="A Deployer", note=None)
    return project_id


@needs_db
class TestNoPhaseReadsAnotherPhasesDeployRows:
    """A deployment row must not reach an earlier snapshot, and theirs must not
    reach the deployment snapshot. Every phase shares the stage, thread and gate
    tables, and each snapshot types its stages over its own ids and reads "the"
    gate decision, so a row crossing over is a validation error at best and a
    wrong decision shown to a reader at worst."""

    async def test_the_design_code_and_testing_snapshots_ignore_them(self, pool) -> None:
        from orchestrator.readmodel.testing import compose_testing

        async with pool.connection() as conn:
            project_id = await _project_with_c4_rows(conn)
            try:
                project = await store.get_project(conn, project_id, owner_id=DEV_OWNER_ID)
                design = await compose(conn, project)
                code = await compose_code(conn, project)
                testing = await compose_testing(conn, project)
            finally:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)

        assert set(design.stages) == set(DESIGN_STAGE_IDS)
        assert set(code.stages) == set(CODE_STAGE_IDS)
        assert set(testing.stages) == set(TEST_STAGE_IDS)
        for snapshot in (design, code, testing):
            assert all("cautious one won" not in m.content for m in snapshot.thread)
            decided = [d.by for d in [snapshot.gate.decision, *snapshot.gate.history] if d]
            assert "A Deployer" not in decided, "an earlier phase read the deployment decision"

    async def test_the_deployment_snapshot_ignores_every_earlier_row(self, pool) -> None:
        from orchestrator.readmodel.deployment import compose_deployment

        async with pool.connection() as conn:
            project_id = await _project_with_c4_rows(conn)
            try:
                project = await store.get_project(conn, project_id, owner_id=DEV_OWNER_ID)
                snapshot = await compose_deployment(conn, project)
            finally:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)

        assert set(snapshot.stages) == set(DEPLOY_STAGE_IDS)
        assert snapshot.stages["risk-assessment"].summary == "1 high, 1 medium, 1 low"
        assert [m.content for m in snapshot.thread] == [
            "three signals disagreed and the cautious one won"
        ]
        assert snapshot.gate.decision is not None
        assert snapshot.gate.decision.by == "A Deployer"
        decided = [d.by for d in [snapshot.gate.decision, *snapshot.gate.history] if d]
        assert "Someone Else" not in decided, "the deployment snapshot read the testing decision"
