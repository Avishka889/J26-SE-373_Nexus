"""Test setup for the orchestrator.

The first line is the important one, and it was missing until the corpus case
needed it. Real model requests are blocked at import, so a test that reaches a
provider fails loudly instead of quietly spending money. That mattered less while
the graph ran a stub; now the orchestrator builds real Component 1 agents, and a
mistake in the wiring would have been a live call from a suite nobody expects to
make one.

Tests that genuinely want a real model opt back in explicitly and are marked
`live`, so the ordinary suite stays offline and deterministic.

The database fixture lives here rather than in one test file because more than one
file needs it, and the reachability check runs once at import: this points at a
shared Neon branch, and a suite that hangs on a connection timeout per test is
worse than one that skips.
"""

import os
import pathlib
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from orchestrator.config import Settings, get_settings
from psycopg import sql
from pydantic_ai import models

#: Blocked before any test module is imported. pydantic-ai raises rather than
#: calling out, which is what we want: an accidental live call in CI is a bill
#: and a flake.
models.ALLOW_MODEL_REQUESTS = False


#: Where the compose file puts Postgres, and the message that names it.
COMPOSE_HINT = (
    "Start it with `docker compose up -d db`, which serves postgres:16 on "
    "localhost:5433. If Docker is not running, either start Docker Desktop or "
    "set TEST_DATABASE_URL at a Neon test branch instead."
)


#: What went wrong reaching the test database, kept for the skip reason.
_FAILURE: str | None = None


def _same_database(left: str, right: str) -> bool:
    """Whether two URLs address one database.

    Compared by host, port and name rather than as strings: two URLs differing
    only by a query parameter or a password still reach the same rows, and it
    is the rows this refusal exists to protect.
    """
    a, b = urlsplit(left), urlsplit(right)
    return (a.hostname, a.port or 5432, a.path) == (b.hostname, b.port or 5432, b.path)


def _docker_is_running() -> bool:
    try:
        done = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _ensure_database(url: str) -> None:
    """Create the test database if the server is there and it is not.

    The compose file ships one database, `sdlc`, and the test database is a
    second one beside it. Creating it here rather than in a setup script means
    a fresh clone runs the suite after `docker compose up -d db` and nothing
    else.
    """
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    if not name:
        return
    maintenance = urlunsplit(parts._replace(path="/postgres"))
    with psycopg.connect(maintenance, connect_timeout=8, autocommit=True) as conn:
        found = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if found.fetchone() is None:
            # The name comes from the developer's own environment, and psycopg
            # cannot parameterise an identifier, so it is quoted rather than
            # interpolated raw.
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _ensure_schema(url: str) -> None:
    """Bring the test database up to head, whether it is new or merely behind.

    So that a fresh clone runs the suite after `docker compose up -d db` and
    nothing else. Alembic cannot create the database it connects to, so this
    has to happen here rather than as a documented step somebody forgets: the
    step before it is the one that creates the database.

    A database an earlier run created is upgraded too. This used to return as
    soon as the schema existed, so a migration that landed later never reached
    the test database, and the obvious manual fix, `alembic upgrade head` with
    `DATABASE_URL` pointed at it, migrated the development database instead,
    because migrations read the direct URL. That happened once, with 0011, and
    was reverted the same minute. Upgrading an up to date database is a no-op.
    """
    from alembic import command
    from alembic.config import Config

    root = pathlib.Path(__file__).resolve().parents[2] / "orchestrator"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "orchestrator" / "db" / "migrations"))

    # The env module reads the settings, so the URL travels the way it does in
    # every other entry point rather than through a second mechanism. The cache
    # has to be cleared around it: `get_settings` is `lru_cache`d, so the first
    # version of this set the environment variable and migrated the development
    # database anyway, which is the exact accident this whole change exists to
    # prevent. It was harmless only because that database was already at head.
    previous = os.environ.get("DATABASE_DIRECT_URL")
    os.environ["DATABASE_DIRECT_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_DIRECT_URL", None)
        else:
            os.environ["DATABASE_DIRECT_URL"] = previous
        get_settings.cache_clear()

    # And check it landed where it was aimed. A migration that runs against the
    # wrong database reports success just as loudly as one that does not, and
    # now that an existing schema is upgraded too, the schema merely existing
    # proves nothing: the test database has to be at head itself.
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(config).get_current_head()
    with psycopg.connect(url, connect_timeout=8) as conn:
        landed = conn.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'app'"
        ).fetchone()
        at = (
            conn.execute("SELECT version_num FROM app.alembic_version").fetchone()
            if landed is not None
            else None
        )
    if landed is None or at is None or at[0] != head:
        raise RuntimeError(
            f"migrations reported success but {url.rsplit('/', 1)[-1]} is not at {head}, "
            "so they ran somewhere else. Check DATABASE_DIRECT_URL."
        )


def _database_url() -> str | None:
    """The database the suite may write to, or None when none is reachable.

    Required, with no fallback to the development database. It used to fall
    back, and the fallback deleted a real GitHub credential: the connections
    tests clean up by deleting the stored token of the owner they ran as, and
    the owner they ran as was the developer's. A suite that shares a database
    with a running server is one careless DELETE from somebody's data, and the
    fix is not to be careful, it is to point the suite somewhere else.

    A misconfiguration is a hard failure here; being offline is a skip. They
    are different problems: the first means the suite would run somewhere it
    must not, the second means it cannot run at all.
    """
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set, and these tests will not fall back to "
            f"DATABASE_URL: they delete rows. {COMPOSE_HINT}"
        )
    dev = (get_settings().database_url or "").strip()
    if dev and _same_database(url, dev):
        raise RuntimeError(
            "TEST_DATABASE_URL addresses the same database as DATABASE_URL. The "
            "suite deletes projects, settings rows and stored credentials, so it "
            f"needs a database of its own. {COMPOSE_HINT}"
        )
    global _FAILURE
    try:
        _ensure_database(url)
        _ensure_schema(url)
        with psycopg.connect(url, connect_timeout=8) as conn:
            conn.execute("select 1")
    except Exception as error:
        # Kept, not swallowed. A bare `return None` here turned every database
        # test into a skip reading "nothing answered", which is a guess about
        # the cause rather than the cause: the first time it fired, the real
        # reason was something else entirely and the message sent the reader
        # to Docker.
        _FAILURE = f"{type(error).__name__}: {error}"
        return None
    return url


def _unreachable_reason(url: str) -> str:
    """Why the database could not be used, in the terms of what to do about it.

    Leads with what actually went wrong. Only when the failure looks like a
    refused connection to a local host does it pay for a `docker info` call to
    tell a stopped daemon from a stopped container, because those have
    different fixes and look identical from the connection error alone.
    """
    detail = _FAILURE or "no failure was recorded"
    host = (urlsplit(url).hostname or "").lower()
    local = host in {"localhost", "127.0.0.1", "::1"}
    refused = "connection" in detail.lower() or "OperationalError" in detail
    if local and refused and not _docker_is_running():
        return (
            "the Docker daemon is not reachable, so the compose database cannot "
            "be running. Start Docker Desktop, then `docker compose up -d db`, or "
            f"set TEST_DATABASE_URL at a Neon test branch. ({detail})"
        )
    return f"the test database could not be used: {detail}"


DATABASE_URL = _database_url()
needs_db = pytest.mark.skipif(
    DATABASE_URL is None,
    reason=_unreachable_reason(os.environ.get("TEST_DATABASE_URL", "").strip()),
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        database_url=DATABASE_URL,
        database_direct_url=DATABASE_URL,
        # Per test, so a run under test can never write into, or sweep away,
        # a workspace a real run is using.
        c3_workspace_root=str(tmp_path / "workspaces"),
    )


@pytest.fixture
def allow_live_requests() -> Iterator[None]:
    """Opt one test back into calling a real provider.

    Restores the block afterwards even if the test fails, so one live test cannot
    leave the door open for the rest of the session.
    """
    models.ALLOW_MODEL_REQUESTS = True
    try:
        yield
    finally:
        models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture(scope="session")
def live_model_name() -> str:
    """The model a live run pins, from configuration.

    Never a literal in a test. Which model answered is part of a result, and a
    hardcoded name makes a recorded number impossible to reproduce.
    """
    return os.environ.get("C1_MODEL", get_settings().c1_model)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip live and cloud tests unless they were asked for by name.

    `-m live` or `-m cloud` runs them. Anything else, including a bare `pytest`,
    does not, so the suite stays offline, free and deterministic by default, and
    nothing is spent or deployed by accident.
    """
    asked = config.getoption("-m")
    for marker, reason in (
        ("live", "needs a real provider; run with -m live"),
        ("cloud", "calls a real cloud provider; run with -m cloud, and only with a go ahead"),
    ):
        if asked == marker:
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)


#: The identity every test that touches the credential store acts as.
#:
#: Not `DEV_OWNER_ID`. Tests share one database with the development server and
#: the credential store is keyed by owner, so a test cleaning up after itself
#: was deleting the developer's real GitHub token and connection: silently,
#: with no audit line and no request, because the cleanup goes straight to the
#: store. It read as credentials being lost on restart, since a restart is what
#: tends to happen around a test run.
#:
#: A test owner needs no row in `app.users`: the settings and secrets tables
#: are keyed by plain text, and only `projects.owner_id` carries the key.
TEST_OWNER_ID = "u_test_owner"


def refuse_the_developers_store(owner_id: str) -> str:
    """Guard the one deletion in this suite that destroys something real.

    A cleanup that deletes a token cannot be allowed to run against the
    identity the development server uses, and asserting it here means a future
    edit that drops the dependency override fails loudly on the first test
    rather than quietly on somebody's credentials.
    """
    from orchestrator.api.deps import DEV_OWNER_ID

    if owner_id == DEV_OWNER_ID:
        raise AssertionError(
            "a test was about to delete the credential store of the identity the "
            "development server runs as. Tests act as TEST_OWNER_ID, because this "
            "database is shared with that server."
        )
    return owner_id
