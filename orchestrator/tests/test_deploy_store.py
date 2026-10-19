"""The deploy axis in the store: its own counter, its own files, its own freeze.

Three facts a deployment run needs that no earlier phase did. The counter is
separate, so analysing updates does not consume a test version. The deployment
files are kept apart from C2's, because C2 replaces the whole repository tree on
every push. And the gate freezes what it approved, except the two artefacts that
are written after an approval by design.
"""

import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from sdlc_contracts import DEPLOY_STAGE_IDS

from .conftest import needs_db

pytestmark = needs_db


@pytest.fixture
async def pool(settings: Settings):
    from orchestrator.db.pool import create_app_pool

    pool = create_app_pool(settings.database_url, max_size=2)
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def project(pool):
    async with pool.connection() as conn:
        row = await store.create_project(conn, name="Deploy axis case", owner_id=DEV_OWNER_ID)
    try:
        yield row["id"]
    finally:
        async with pool.connection() as conn:
            await store.delete_project(conn, row["id"], owner_id=DEV_OWNER_ID)


async def _approve_deploy_version(conn, project: str, version: int) -> None:
    run = await store.create_run(
        conn, project_id=project, requirements_version=version, component="c4", source_version=1
    )
    gate = await store.open_gate(
        conn,
        run_id=run["id"],
        project_id=project,
        requirements_version=version,
        payload={},
        interrupt_id=None,
        kind="c4-deploy-review",
    )
    await store.resolve_gate(conn, gate["id"], decision="approved", by="you", note=None)


class TestTheVersionCounter:
    async def test_it_starts_at_one_and_ignores_the_testing_axis(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_artefact(
                conn, project_id=project, kind="test-report", version=3, body={}
            )
            assert await store.next_deploy_version(conn, project) == 1
            assert await store.current_deploy_version(conn, project) == 0

    async def test_a_claimed_version_is_not_handed_out_twice(self, pool, project) -> None:
        async with pool.connection() as conn:
            first = await store.next_deploy_version(conn, project)
            await store.create_run(
                conn, project_id=project, requirements_version=first, component="c4"
            )
            assert await store.next_deploy_version(conn, project) == first + 1

    async def test_the_ten_stages_are_seeded_once(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.seed_deploy_stages(conn, project)
            await store.seed_deploy_stages(conn, project)
            rows = await store.stage_states(conn, project)
        # Project creation seeds the design stages; only the deploy ones are ours.
        deploy = [row["stage_id"] for row in rows if row["stage_id"] in DEPLOY_STAGE_IDS]
        assert sorted(deploy) == sorted(DEPLOY_STAGE_IDS)


class TestTheDeploymentFiles:
    async def test_a_stage_replaces_exactly_its_own_files(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_deploy_files(
                conn, project, version=1, stage_id="dependency-updates", files={"notes/a.md": "a"}
            )
            await store.put_deploy_files(
                conn,
                project,
                version=1,
                stage_id="pipeline-generation",
                files={"Dockerfile": "FROM node:22", "vercel.json": "{}"},
            )
            await store.put_deploy_files(
                conn, project, version=1, stage_id="pipeline-generation", files={"Dockerfile": "x"}
            )
            analysis = await store.deploy_files(
                conn, project, version=1, stage_id="dependency-updates"
            )
            layer = await store.deploy_files(
                conn, project, version=1, stage_id="pipeline-generation"
            )
            one = await store.deploy_file(
                conn, project, version=1, stage_id="dependency-updates", path="notes/a.md"
            )
        assert analysis == {"notes/a.md": "a"}
        assert layer == {"Dockerfile": "x"}
        assert one == "a"

    async def test_two_stages_hold_the_same_path_each_its_own(self, pool, project) -> None:
        """Detection keeps the baseline lockfile it pinned; pipeline generation
        writes the candidate's, the baseline with the included updates applied.
        Under 0011's key the second write took the first stage's row over, and the
        baseline read back as the candidate's lockfile."""
        async with pool.connection() as conn:
            await store.put_deploy_files(
                conn,
                project,
                version=1,
                stage_id="dependency-updates",
                files={"package-lock.json": "baseline"},
            )
            await store.put_deploy_files(
                conn,
                project,
                version=1,
                stage_id="pipeline-generation",
                files={"package-lock.json": "candidate"},
            )
            baseline = await store.deploy_file(
                conn, project, version=1, stage_id="dependency-updates", path="package-lock.json"
            )
            candidate = await store.deploy_file(
                conn, project, version=1, stage_id="pipeline-generation", path="package-lock.json"
            )
        assert (baseline, candidate) == ("baseline", "candidate")

    async def test_they_never_mix_with_the_generated_code(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_deploy_files(
                conn, project, version=1, stage_id="pipeline-generation", files={"a": "b"}
            )
            assert await store.code_files(conn, project, version=1) == {}


class TestTheGateFreezesWhatItApproved:
    async def test_an_approved_risk_report_cannot_be_rewritten(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_artefact(
                conn, project_id=project, kind="risk-report", version=1, body={}
            )
            await _approve_deploy_version(conn, project, 1)
            with pytest.raises(store.VersionAlreadyApproved):
                await store.put_artefact(
                    conn, project_id=project, kind="risk-report", version=1, body={"x": 1}
                )

    async def test_monitoring_is_written_after_the_approval_by_design(self, pool, project) -> None:
        async with pool.connection() as conn:
            await _approve_deploy_version(conn, project, 1)
            await store.put_artefact(
                conn, project_id=project, kind="monitoring-report", version=1, body={}
            )
            await store.put_artefact(conn, project_id=project, kind="feedback", version=1, body={})
