"""What every route needs: a connection, and the pieces the app holds."""

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Request
from psycopg import AsyncConnection

from .. import accounts
from ..db import store
from ..errors import DomainError, NotFound

#: Methods that only read. No route answering one writes anything.
_READS = frozenset({"GET", "HEAD"})


async def db(request: Request) -> AsyncIterator[AsyncConnection]:
    """One transaction per request that writes, committed on the way out.

    psycopg's pool context manager commits on success and rolls back on an
    exception, which is what makes "write the change and its audit entry
    together" true rather than aspirational.

    A read runs in autocommit instead. It has nothing to commit, and BEGIN and
    COMMIT were two of the three round trips every request paid before its
    first query (Neon answers about 0.2 s after each, from where this is used).
    Each statement still reads committed data, as it did inside a transaction
    at READ COMMITTED. The connection goes back to the pool as it was lent.
    """
    pool = request.app.state.pool
    async with pool.connection() as conn:
        if request.method not in _READS:
            yield conn
            return
        await conn.set_autocommit(True)
        # And each query is asked once: the read models ask some of theirs
        # more than once, and a read-only request cannot change the answer.
        store.remember_reads(conn)
        try:
            yield conn
        finally:
            store.forget_reads(conn)
            await conn.set_autocommit(False)


Db = Annotated[AsyncConnection, Depends(db)]


#: The identity every row before sign-in belongs to (migration 0003), which the
#: first account registered adopts. Tests act as it by default.
DEV_OWNER_ID = "u_local_dev"


async def current_user(request: Request, conn: Db) -> dict[str, Any]:
    """The signed-in account, from the session cookie.

    Every route but sign-in itself and the health check depends on this, so a
    request without a current session is refused before it reads anything.
    """
    token = request.cookies.get(accounts.SESSION_COOKIE)
    if token:
        user = await store.session_user(conn, accounts.token_hash(token))
        if user is not None:
            return dict(user)
    raise DomainError("Sign in to continue.", status_code=401)


CurrentUser = Annotated[dict[str, Any], Depends(current_user)]


async def current_owner(user: CurrentUser) -> str:
    """Whose projects this request may see: the signed-in account's."""
    return str(user["id"])


Owner = Annotated[str, Depends(current_owner)]


async def current_actor(user: CurrentUser) -> str:
    """Who is acting, as the audit log and every decision record it.

    Taken from the session, never from the request body: a decision is recorded
    under the account that made it, whatever a client says.
    """
    return accounts.display_name(user)


Actor = Annotated[str, Depends(current_actor)]


def supervisor(request: Request) -> Any:
    return request.app.state.supervisor


Supervisor = Annotated[Any, Depends(supervisor)]


def watched_now(state: Any) -> frozenset[str]:
    """The deployments a monitoring window watches now, by id.

    Windows live in this process's monitor, not in the database: a window a
    restart ended watches nothing, and the snapshot says so.
    """
    monitor = getattr(state, "monitor", None)
    return frozenset(str(one) for one in monitor.running()) if monitor else frozenset()


def watched(request: Request) -> frozenset[str]:
    return watched_now(request.app.state)


Watched = Annotated[frozenset[str], Depends(watched)]


def components(request: Request) -> dict[str, Any]:
    """The component clients the app opened at startup, by key.

    Routes reach a component directly only where the work is not a run: a run
    goes through the graph and the supervisor, which is where retries, gates
    and audit live. Re-verifying a fix is the one case so far, because it is a
    question asked about two runs that already happened rather than a stage of
    a new one.
    """
    return getattr(request.app.state, "clients", {})


Components = Annotated[dict[str, Any], Depends(components)]


async def require_project(conn: AsyncConnection, project_id: str, owner_id: str) -> store.Row:
    """The project, or a 404.

    Somebody else's project is a 404 rather than a 403, and deliberately: a 403
    confirms the id exists, which is a fact a caller with no claim to the project
    has no business learning.
    """
    project = await store.get_project(conn, project_id, owner_id=owner_id)
    if project is None:
        raise NotFound("project", project_id)
    return project
