"""Connection pools, and the checkpointer that needs its own.

Two pools on purpose, and they are not interchangeable.

The application pool uses the pooled URL and disables prepared statements,
because Neon's pooler is pgbouncer in transaction mode and a named prepared
statement does not survive a connection being handed to somebody else.

The checkpointer pool uses the direct URL, runs in autocommit with dict rows
(which is what `AsyncPostgresSaver` expects), and must not go through a
transaction pooler at all: the saver holds state across statements that a pooler
is free to split apart.

Both check a connection when it is taken out. Neon closes connections it no
longer wants (a compute that suspends when idle, a proxy that drops idle ones),
and a pool that hands one out fails the statement that uses it. That is how the
deployment walkthrough of 2026-09-28 lost a run at its gate, when the checkpoint
written at the interrupt went to a closed connection. The check costs one round
trip per checkout and replaces a dead connection before anything uses it.
"""

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def create_app_pool(pooled_url: str, *, max_size: int = 10) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        conninfo=pooled_url,
        min_size=1,
        max_size=max_size,
        # Safe through a transaction pooler. Without this, psycopg 3 starts
        # naming prepared statements after five executions and the pooler hands
        # the next one to a connection that has never seen them.
        kwargs={"prepare_threshold": None},
        check=AsyncConnectionPool.check_connection,
        open=False,
    )


def create_checkpointer_pool(direct_url: str, *, max_size: int = 4) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        conninfo=direct_url,
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None},
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
