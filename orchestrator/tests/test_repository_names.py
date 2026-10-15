"""Each project pushes to a repository of its own.

The repository was named after the project alone, so the twelve projects
called "Calculator" shared one: generating code for any of them replaced the
released one's repository, deployment files and all, and a 422 "already exists"
was taken for the same project pushing again.

The lookup then read a field the record never has (`pointer`, where the push
records `repository`), and these tests planted that field, so the two agreed
with each other and not with the product: every project's name was derived
again, and a renamed project pushed to a new repository. They plant the record
the push writes now.
"""

from collections.abc import AsyncIterator

import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.db import store
from orchestrator.db.pool import create_app_pool
from orchestrator.graph.code_nodes import _repository_for, _repository_name
from psycopg.types.json import Jsonb
from sdlc_contracts import CodeRepository, RepositoryPointer

from .conftest import DATABASE_URL, needs_db


def test_two_projects_with_one_name_get_two_repositories() -> None:
    first = _repository_name("Calculator", "p_83e9ab3a5273")
    second = _repository_name("Calculator", "p_8f7449b67de7")

    assert first == "calculator-83e9ab3a5273"
    assert second == "calculator-8f7449b67de7"


def test_a_long_or_empty_name_still_fits_and_still_names_the_project() -> None:
    long = _repository_name("x" * 300, "p_0123456789ab")
    blank = _repository_name("!!!", "p_0123456789ab")

    assert len(long) <= 100 and long.endswith("-0123456789ab")
    assert blank == "generated-app-0123456789ab"


@pytest.fixture
async def pool() -> AsyncIterator[object]:
    assert DATABASE_URL is not None
    pool = create_app_pool(DATABASE_URL, max_size=2)
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        await pool.close()


async def _project(conn: object, name: str) -> str:
    project = await store.create_project(conn, name=name, owner_id=DEV_OWNER_ID)  # type: ignore[arg-type]
    return str(project["id"])


def _pointer(name: str) -> RepositoryPointer:
    return RepositoryPointer(
        owner="vinozhan",
        name=name,
        default_branch="main",
        commit_sha="a" * 40,
        url=f"https://github.com/vinozhan/{name}",
    )


async def _pushed(conn: object, project_id: str, name: str, *, days_ago: int) -> None:
    """A code version pushed to `name`, recorded as the build records it."""
    record = CodeRepository(version=1, repository=_pointer(name))
    await conn.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO app.artefacts (project_id, kind, version, body, created_at)
        VALUES (%s, 'code-repository', 1, %s, now() - make_interval(days => %s))
        """,
        (project_id, Jsonb(record.model_dump(by_alias=True, mode="json")), days_ago),
    )


@needs_db
class TestTheRepositoryAProjectPushesTo:
    async def test_a_project_that_pushed_before_keeps_its_repository(self, pool) -> None:
        async with pool.connection() as conn:
            released = await _project(conn, "Calculator")
            try:
                await _pushed(conn, released, "calculator", days_ago=5)
                await conn.commit()

                name = await _repository_for(pool, released, "Calculator")
            finally:
                await store.delete_project(conn, released, owner_id=DEV_OWNER_ID)

        # The released project's repository, and the deployment layer on it, stay put.
        assert name == "calculator"

    async def test_a_later_project_that_shared_it_gets_one_of_its_own(self, pool) -> None:
        async with pool.connection() as conn:
            released = await _project(conn, "Calculator")
            later = await _project(conn, "Calculator")
            try:
                await _pushed(conn, released, "calculator", days_ago=5)
                await _pushed(conn, later, "calculator", days_ago=1)
                await conn.commit()

                name = await _repository_for(pool, later, "Calculator")
            finally:
                await store.delete_project(conn, released, owner_id=DEV_OWNER_ID)
                await store.delete_project(conn, later, owner_id=DEV_OWNER_ID)

        assert name == f"calculator-{later.removeprefix('p_')}"

    async def test_a_push_recorded_after_the_build_is_found_too(self, pool) -> None:
        """A version approved before GitHub was connected is pushed later, and the
        record that push writes is read back the same way."""
        async with pool.connection() as conn:
            released = await _project(conn, "Calculator")
            try:
                unpushed = CodeRepository(version=1, not_pushed_reason="not pushed: no GitHub")
                await store.put_artefact(
                    conn,
                    project_id=released,
                    kind="code-repository",
                    version=1,
                    body=unpushed.model_dump(by_alias=True, mode="json"),
                )
                pointer = _pointer("calculator").model_dump(by_alias=True, mode="json")
                assert await store.record_late_push(conn, released, version=1, pointer=pointer)
                await conn.commit()

                name = await _repository_for(pool, released, "Calculator")
            finally:
                await store.delete_project(conn, released, owner_id=DEV_OWNER_ID)

        assert name == "calculator"

    async def test_a_project_that_never_pushed_gets_one_of_its_own(self, pool) -> None:
        async with pool.connection() as conn:
            fresh = await _project(conn, "Calculator")
            await conn.commit()
            try:
                name = await _repository_for(pool, fresh, "Calculator")
            finally:
                await store.delete_project(conn, fresh, owner_id=DEV_OWNER_ID)

        assert name == f"calculator-{fresh.removeprefix('p_')}"
