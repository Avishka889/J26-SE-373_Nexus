"""A pool replaces a connection the server closed, rather than failing on it.

Neon closes connections it no longer wants: a compute that suspends after its
idle minutes takes every connection with it, and its proxy drops idle ones. A
pool that hands such a connection out fails the next statement ("SSL error:
unexpected eof", "server closed the connection unexpectedly"), which is how the
deployment walkthrough of 2026-09-28 lost a run at its gate: the checkpoint
written at the interrupt failed, and the run with it. Checked on checkout, a
dead connection is replaced before anything uses it.

Each test closes the pooled connection from the server's side, with
`pg_terminate_backend`, and then asks the pool for a connection again.
"""

import psycopg
from orchestrator.config import Settings
from orchestrator.db.pool import create_app_pool, create_checkpointer_pool
from psycopg_pool import AsyncConnectionPool

from .conftest import needs_db

pytestmark = needs_db


async def _survives_a_closed_connection(pool: AsyncConnectionPool, url: str) -> int:
    await pool.open(wait=True)
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute("SELECT pg_backend_pid() AS pid")).fetchone()
            pid = row["pid"] if isinstance(row, dict) else row[0]
        async with await psycopg.AsyncConnection.connect(url, autocommit=True) as admin:
            await admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        async with pool.connection() as conn:
            row = await (await conn.execute("SELECT 1 AS one")).fetchone()
            return row["one"] if isinstance(row, dict) else row[0]
    finally:
        await pool.close()


async def test_the_application_pool_replaces_a_closed_connection(settings: Settings) -> None:
    pool = create_app_pool(settings.database_url, max_size=1)
    assert await _survives_a_closed_connection(pool, settings.database_url) == 1


async def test_the_checkpointer_pool_replaces_a_closed_connection(settings: Settings) -> None:
    pool = create_checkpointer_pool(settings.checkpointer_url, max_size=1)
    assert await _survives_a_closed_connection(pool, settings.checkpointer_url) == 1
