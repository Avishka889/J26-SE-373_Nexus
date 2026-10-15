"""The code axis in the store: its own version counter and its own file store.

Everything here is about the two facts a code run needs that a design run
never did. The version counter is separate, so regenerating code does not
consume a design version or read as though the requirements changed. The
files are rows, so three stages can write them, one can read them all back,
and one can be served on its own.
"""

import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from sdlc_contracts import CODE_STAGE_IDS

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
    """A project of its own, removed afterwards whatever the test did."""
    async with pool.connection() as conn:
        row = await store.create_project(conn, name="Code axis case", owner_id=DEV_OWNER_ID)
    try:
        yield row["id"]
    finally:
        async with pool.connection() as conn:
            await store.delete_project(conn, row["id"], owner_id=DEV_OWNER_ID)


class TestTheVersionCounter:
    async def test_it_starts_at_one_and_ignores_the_design_axis(self, pool, project) -> None:
        async with pool.connection() as conn:
            # A design already several versions along says nothing about code.
            await store.put_artefact(
                conn, project_id=project, kind="requirements", version=4, body={}
            )
            assert await store.next_code_version(conn, project) == 1
            assert await store.current_code_version(conn, project) == 0

    async def test_a_claimed_version_is_not_handed_out_twice(self, pool, project) -> None:
        """The run claims it, before any artefact exists at it.

        Without runs in the count, a second regeneration started before the
        first wrote anything would be given the same number and upsert over
        the first one's artefacts.
        """
        async with pool.connection() as conn:
            first = await store.next_code_version(conn, project)
            await store.create_run(
                conn,
                project_id=project,
                requirements_version=first,
                component="c2",
                source_version=2,
            )
            assert await store.next_code_version(conn, project) == first + 1

    async def test_an_artefact_moves_the_current_version(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_artefact(
                conn, project_id=project, kind="tech-stack", version=1, body={}
            )
            await store.put_artefact(
                conn, project_id=project, kind="api-contract", version=2, body={}
            )
            assert await store.current_code_version(conn, project) == 2
            assert await store.next_code_version(conn, project) == 3


class TestPinningTheDesignVersion:
    async def test_artefacts_at_reads_the_version_asked_for_not_the_newest(
        self, pool, project
    ) -> None:
        """The bug this exists to prevent: a design regenerated while a code
        run was in flight would otherwise change what the code was generated
        from, halfway through generating it."""
        async with pool.connection() as conn:
            await store.put_artefact(
                conn,
                project_id=project,
                kind="sprint-plan",
                version=1,
                body={"sprintName": "the pinned one"},
            )
            await store.put_artefact(
                conn,
                project_id=project,
                kind="sprint-plan",
                version=2,
                body={"sprintName": "the newer one"},
            )
            pinned = await store.artefacts_at(conn, project, version=1, kinds=("sprint-plan",))
            latest = await store.latest_artefacts(conn, project)

            assert pinned["sprint-plan"]["body"]["sprintName"] == "the pinned one"
            assert latest["sprint-plan"]["body"]["sprintName"] == "the newer one"

    async def test_a_kind_absent_at_that_version_is_simply_absent(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_artefact(
                conn, project_id=project, kind="sprint-plan", version=1, body={}
            )
            at = await store.artefacts_at(
                conn, project, version=1, kinds=("sprint-plan", "wireframes")
            )
            assert set(at) == {"sprint-plan"}

    async def test_a_run_records_the_upstream_version_it_read(self, pool, project) -> None:
        async with pool.connection() as conn:
            run = await store.create_run(
                conn,
                project_id=project,
                requirements_version=1,
                component="c2",
                source_version=3,
            )
            stored = await store.get_run(conn, run["id"])
            assert stored is not None
            assert stored["source_version"] == 3
            assert stored["requirements_version"] == 1

    async def test_a_design_run_records_no_upstream_version(self, pool, project) -> None:
        async with pool.connection() as conn:
            run = await store.create_run(conn, project_id=project, requirements_version=1)
            assert run["source_version"] is None


class TestTheFileStore:
    async def test_files_round_trip_whole_and_one_at_a_time(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_code_files(
                conn,
                project,
                version=1,
                stage_id="frontend-code",
                files={"apps/web/src/App.tsx": "export const App = 1;\n", "README.md": "# x\n"},
            )
            await store.put_code_files(
                conn,
                project,
                version=1,
                stage_id="backend-code",
                files={"apps/api/src/app.ts": "export const app = 1;\n"},
            )
            everything = await store.code_files(conn, project, version=1)
            assert set(everything) == {
                "apps/web/src/App.tsx",
                "README.md",
                "apps/api/src/app.ts",
            }
            one = await store.code_file(conn, project, version=1, path="apps/api/src/app.ts")
            assert one == "export const app = 1;\n"

    async def test_a_regeneration_leaves_no_orphans_from_the_same_stage(
        self, pool, project
    ) -> None:
        """The manifest and the file store must name the same set. An upsert
        alone would leave the first run's extra file behind, invisible to the
        manifest and servable by the file route."""
        async with pool.connection() as conn:
            await store.put_code_files(
                conn,
                project,
                version=1,
                stage_id="frontend-code",
                files={"a.tsx": "1", "b.tsx": "2", "c.tsx": "3"},
            )
            await store.put_code_files(
                conn,
                project,
                version=1,
                stage_id="frontend-code",
                files={"a.tsx": "one"},
            )
            everything = await store.code_files(conn, project, version=1)
            assert everything == {"a.tsx": "one"}

    async def test_one_stage_does_not_delete_another_stages_files(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_code_files(
                conn, project, version=1, stage_id="frontend-code", files={"a.tsx": "1"}
            )
            await store.put_code_files(
                conn, project, version=1, stage_id="backend-code", files={"b.ts": "2"}
            )
            await store.put_code_files(
                conn, project, version=1, stage_id="frontend-code", files={"a.tsx": "again"}
            )
            assert await store.code_files(conn, project, version=1) == {
                "a.tsx": "again",
                "b.ts": "2",
            }

    async def test_versions_do_not_see_each_other(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_code_files(
                conn, project, version=1, stage_id="build", files={"a": "v1"}
            )
            await store.put_code_files(
                conn, project, version=2, stage_id="build", files={"a": "v2"}
            )
            assert (await store.code_files(conn, project, version=1)) == {"a": "v1"}
            assert (await store.code_files(conn, project, version=2)) == {"a": "v2"}

    async def test_a_missing_file_is_none_rather_than_an_error(self, pool, project) -> None:
        async with pool.connection() as conn:
            assert await store.code_file(conn, project, version=1, path="nope.ts") is None

    async def test_an_empty_stage_clears_its_files(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.put_code_files(
                conn, project, version=1, stage_id="frontend-code", files={"a.tsx": "1"}
            )
            await store.put_code_files(conn, project, version=1, stage_id="frontend-code", files={})
            assert await store.code_files(conn, project, version=1) == {}


class TestSeedingTheCodeStages:
    async def test_the_eight_rows_appear_once_however_often_it_is_called(
        self, pool, project
    ) -> None:
        async with pool.connection() as conn:
            await store.seed_code_stages(conn, project)
            await store.seed_code_stages(conn, project)
            rows = await store.stage_states(conn, project)
            code_rows = [row for row in rows if row["stage_id"] in CODE_STAGE_IDS]
            assert len(code_rows) == len(CODE_STAGE_IDS)
            assert all(row["status"] == "pending" for row in code_rows)

    async def test_it_does_not_reset_a_stage_that_already_moved(self, pool, project) -> None:
        """A second code run calls this again, and a reset would wipe the
        first run's completed stages back to pending under the reader."""
        async with pool.connection() as conn:
            await store.seed_code_stages(conn, project)
            await store.set_stage(
                conn, project, "tech-stack", status="complete", version=1, summary="MERN"
            )
            await store.seed_code_stages(conn, project)
            rows = {row["stage_id"]: row for row in await store.stage_states(conn, project)}
            assert rows["tech-stack"]["status"] == "complete"
            assert rows["tech-stack"]["summary"] == "MERN"

    async def test_the_design_stages_are_untouched(self, pool, project) -> None:
        async with pool.connection() as conn:
            await store.seed_code_stages(conn, project)
            rows = {row["stage_id"] for row in await store.stage_states(conn, project)}
            assert "requirements" in rows and "design-review" in rows
