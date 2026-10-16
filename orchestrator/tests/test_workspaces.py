"""Writing a version of the file store out as a directory a lane can run.

The rules here are all about what survives and what does not, and each of them
is a way a number could go wrong: a stale file that keeps being tested, an
install thrown away four times a run, a disk filling with old versions, or an
empty directory reported as a project whose tests all passed.
"""

import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store

from orchestrator import workspaces

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
async def created(pool):
    """Projects this module made, removed afterwards whatever a test did."""
    made: list[str] = []
    try:
        yield made
    finally:
        async with pool.connection() as conn:
            for project_id in made:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _project_with_code(pool, created, *, version: int, files: dict[str, str]) -> str:
    async with pool.connection() as conn:
        project = await store.create_project(conn, name="Workspace case", owner_id=DEV_OWNER_ID)
        created.append(project["id"])
        await store.put_code_files(
            conn,
            project["id"],
            version=version,
            stage_id="frontend-code",
            files=files,
        )
    return project["id"]


class TestWhatGetsWritten:
    async def test_every_file_at_that_version_lands(self, pool, created, tmp_path) -> None:
        project_id = await _project_with_code(
            pool,
            created,
            version=1,
            files={"package.json": "{}\n", "apps/web/src/total.ts": "export const a = 1;\n"},
        )

        root = await workspaces.materialise(pool, project_id, code_version=1, base=str(tmp_path))

        assert (root / "package.json").read_text() == "{}\n"
        assert (root / "apps/web/src/total.ts").read_text() == "export const a = 1;\n"

    async def test_a_version_with_no_files_is_refused_rather_than_run(
        self, pool, created, tmp_path
    ) -> None:
        """A lane pointed at an empty directory installs nothing, runs nothing
        and reports a suite of no tests, which reads as a project whose tests
        all passed."""
        project_id = await _project_with_code(
            pool, created, version=1, files={"package.json": "{}"}
        )

        with pytest.raises(FileNotFoundError, match="no generated files at code version 2"):
            await workspaces.materialise(pool, project_id, code_version=2, base=str(tmp_path))

    async def test_two_versions_live_side_by_side(self, pool, created, tmp_path) -> None:
        """The honesty guard runs a repaired test against the code it was
        written for, which is the previous version, so both have to exist."""
        project_id = await _project_with_code(pool, created, version=1, files={"a.ts": "one"})
        async with pool.connection() as conn:
            await store.put_code_files(
                conn, project_id, version=2, stage_id="frontend-code", files={"a.ts": "two"}
            )

        first = await workspaces.materialise(pool, project_id, code_version=1, base=str(tmp_path))
        second = await workspaces.materialise(pool, project_id, code_version=2, base=str(tmp_path))

        assert first != second
        assert (first / "a.ts").read_text() == "one"
        assert (second / "a.ts").read_text() == "two"


class TestWhatSurvivesAndWhatDoesNot:
    async def test_an_install_is_not_thrown_away(self, pool, created, tmp_path) -> None:
        """Otherwise every stage of every run pays for a cold install, and a
        testing run touches the same tree four times."""
        project_id = await _project_with_code(
            pool, created, version=1, files={"package.json": "{}"}
        )
        root = await workspaces.materialise(pool, project_id, code_version=1, base=str(tmp_path))
        (root / "node_modules").mkdir()
        (root / "node_modules" / "marker").write_text("expensive")

        await workspaces.materialise(pool, project_id, code_version=1, base=str(tmp_path))

        assert (root / "node_modules" / "marker").read_text() == "expensive"

    async def test_a_file_the_store_no_longer_has_is_cleared_out(
        self, pool, created, tmp_path
    ) -> None:
        """A test file deleted by a regeneration that stayed in the workspace
        would be run, pass, and be counted."""
        project_id = await _project_with_code(
            pool, created, version=1, files={"a.ts": "one", "gone.test.ts": "old"}
        )
        root = await workspaces.materialise(pool, project_id, code_version=1, base=str(tmp_path))
        async with pool.connection() as conn:
            await store.put_code_files(
                conn, project_id, version=1, stage_id="frontend-code", files={"a.ts": "one"}
            )

        await workspaces.materialise(pool, project_id, code_version=1, base=str(tmp_path))

        assert not (root / "gone.test.ts").exists()
        assert (root / "a.ts").exists()

    async def test_the_disk_is_bounded_to_this_version_and_the_last(
        self, pool, created, tmp_path
    ) -> None:
        """A workspace with an install in it is a few hundred megabytes, and
        this machine has under six gigabytes. The guard needs the previous
        version; nothing needs the one before that."""
        project_id = await _project_with_code(pool, created, version=1, files={"a.ts": "one"})
        async with pool.connection() as conn:
            for version in (2, 3):
                await store.put_code_files(
                    conn,
                    project_id,
                    version=version,
                    stage_id="frontend-code",
                    files={"a.ts": str(version)},
                )
        for version in (1, 2):
            await workspaces.materialise(pool, project_id, code_version=version, base=str(tmp_path))

        await workspaces.materialise(pool, project_id, code_version=3, base=str(tmp_path))

        assert not workspaces.workspace_path(str(tmp_path), project_id, 1).exists()
        assert workspaces.workspace_path(str(tmp_path), project_id, 2).exists()
        assert workspaces.workspace_path(str(tmp_path), project_id, 3).exists()

    async def test_a_deleted_project_leaves_nothing_behind(self, pool, created, tmp_path) -> None:
        project_id = await _project_with_code(pool, created, version=1, files={"a.ts": "one"})
        await workspaces.materialise(pool, project_id, code_version=1, base=str(tmp_path))

        workspaces.forget(str(tmp_path), project_id)

        assert not (tmp_path / project_id).exists()


def test_the_two_preserve_lists_are_the_same_fact() -> None:
    """The harness has its own copy, for the copy it makes of a checked-in
    sample. They are not shared code because the orchestrator does not import
    the component, so this is what keeps them from drifting apart."""
    from c3.harness.targets import NOT_COPIED

    assert set(NOT_COPIED) <= workspaces.PRESERVED
