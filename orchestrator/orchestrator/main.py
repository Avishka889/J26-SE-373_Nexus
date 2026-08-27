"""The one front door.

The browser calls this and nothing else. Component services are internal and are
reached through typed clients, so a browser can never be pointed at C1 directly
and no component has to grow its own authentication or CORS policy.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from . import accounts
from .api import auth, code, connections, deployment, design, documents, process, projects, testing
from .api import settings as settings_api
from .api.deps import DEV_OWNER_ID, current_user
from .clients.canned import CannedC1, CannedC2, CannedC3
from .clients.canned_c4 import CannedC4
from .components import COMPONENTS
from .config import Settings, get_settings
from .db.pool import create_app_pool, create_checkpointer_pool
from .deploy.adapters.checks import HttpChecks
from .deploy.adapters.github_actions import GithubActions
from .deploy.adapters.local_docker import LocalDocker, reap_leftovers
from .deploy.adapters.render import RenderDeploys
from .deploy.supervisor import MonitorSupervisor
from .errors import AnswerUnexpectedErrors, install_error_handlers
from .graph.build import build_graph
from .graph.code_graph import build_code_graph
from .graph.deployment_graph import build_deployment_graph
from .graph.runner import RunSupervisor
from .graph.testing_graph import build_testing_graph
from .previews import PreviewSupervisor
from .saga.runner import SagaRunner

log = logging.getLogger(__name__)

#: Which environment variable each provider's client reads its key from.
#:
#: Keyed by the prefix of `c1_model`, because that string is the only place the
#: provider is chosen. Each settings field is the lowercase of its variable,
#: which is how the check below finds the one the configured model needs, so
#: adding a provider is an entry here, the matching field on `Settings`, and the
#: pydantic-ai extra in C1's dependencies. Nothing else.
PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def resolve_provider_key(settings: Settings, model: str | None = None) -> tuple[str, str]:
    """The environment variable a component's model client reads, and its key.

    A function rather than a block inside `lifespan` so it can be tested without
    a database: `lifespan` opens both pools before it reaches this, and a wrong
    mapping here is not a failed request, it is a server that will not start.

    Settings win over the ambient environment so a repository `.env` is the one
    place a key lives, and so a stale export in someone's shell cannot quietly
    answer for a provider they are not using.

    `model` defaults to C1's for the callers that predate the registry; every
    component resolves its own model string through the same map.
    """
    model = model or settings.c1_model
    provider = model.split(":", 1)[0]
    variable = PROVIDER_KEYS.get(provider)
    if variable is None:
        known = ", ".join(sorted(PROVIDER_KEYS))
        raise RuntimeError(
            f"The model is {model!r}, whose provider {provider!r} has no "
            f"key configured. Known providers are: {known}."
        )
    key = getattr(settings, variable.lower(), "") or os.environ.get(variable, "")
    if not key:
        raise RuntimeError(
            f"The mode is 'inprocess' and the model is {model!r}, but no "
            f"{variable} is set. Put it in the repository's .env, or use the http "
            "mode to call the component over the wire instead."
        )
    return variable, key


def place_provider_key(settings: Settings, model: str) -> None:
    """Resolve the key for `model` and put it where the model client looks.

    The model client reads its key from the process environment, and settings
    read it from .env, so this is the one place the two meet. Missing is
    refused here, at startup, rather than three stages into the first run.
    """
    variable, key = resolve_provider_key(settings, model)
    os.environ.setdefault(variable, key)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the pools, compile the graph, start the supervisor.

    Two pools, and they are not interchangeable: the application uses the pooled
    URL, and the checkpointer needs the direct one because it holds state across
    statements that a transaction pooler is free to split apart.

    The graph is compiled once per process. It has to be one instance, because a
    gate opened before a restart resumes against the compiled definition it finds
    when the process comes back.
    """
    settings: Settings = app.state.settings

    app_pool = create_app_pool(settings.database_url)
    await app_pool.open(wait=True)
    app.state.pool = app_pool

    checkpointer_pool = create_checkpointer_pool(settings.checkpointer_url)
    await checkpointer_pool.open(wait=True)
    app.state.checkpointer_pool = checkpointer_pool

    checkpointer = AsyncPostgresSaver(checkpointer_pool)  # type: ignore[arg-type]
    # Creates the checkpoint tables if they are missing. Cheap and idempotent,
    # and keeping it here means a fresh database needs no extra step.
    await checkpointer.setup()
    app.state.checkpointer = checkpointer

    # One client and one compiled graph per registered component. In process a
    # client holds the component's agents, and each of those holds a provider
    # connection, so building one per run would leak a socket per run. The
    # graphs must be single instances too: a gate opened before a restart
    # resumes against the compiled definition it finds when the process comes
    # back.
    clients: dict[str, object] = {}
    graphs: dict[str, object] = {}
    for key, spec in COMPONENTS.items():
        client = spec.make_client(settings)
        if hasattr(client, "__aenter__"):
            await client.__aenter__()
        clients[key] = client
        graphs[key] = spec.build_graph(app_pool, checkpointer, client)

    # The single component attributes stay pointed at C1 for everything that
    # predates the registry: the design routes and the tests reach the client
    # and the graph this way.
    app.state.c1 = clients["c1"]
    app.state.graph = graphs["c1"]
    app.state.clients = clients
    app.state.graphs = graphs

    supervisor = RunSupervisor(pool=app_pool, graphs=graphs, clients=clients)
    await supervisor.start()
    app.state.supervisor = supervisor

    # The saga carries out approved releases, outside any run. What staging and
    # the checks left behind is reaped first; a release container never is,
    # because it is production and outlives this process by design.
    reaped = await reap_leftovers(settings.c4_local_lane)
    if reaped:
        log.info("removed %d container(s) staging or a check left behind", reaped)
    saga = SagaRunner(
        pool=app_pool,
        adapters={
            "local-docker": LocalDocker(
                release_port=settings.c4_local_release_port, lane=settings.c4_local_lane
            ),
            "github": GithubActions(pool=app_pool, secret_key=settings.secret_key),
            # The backend of a cloud release, deployed through Render's API with the
            # key that never leaves this process.
            "render": RenderDeploys(pool=app_pool, secret_key=settings.secret_key),
            "checks": HttpChecks(),
        },
    )
    await saga.start()
    app.state.saga = saga

    # One bounded window after every verified release, and one when a person
    # asks; never a probe that runs forever.
    monitor = MonitorSupervisor(pool=app_pool, c4=clients["c4"], **_monitor_window(settings))
    await monitor.start()
    app.state.monitor = monitor

    # Previews are real processes serving generated code. Anything a previous
    # process left running is killed before this one starts: the row says
    # running, but this orchestrator did not spawn it and cannot supervise it.
    previews = PreviewSupervisor(app_pool)
    await previews.reap_orphans()
    await previews.start_sweeper()
    app.state.previews = previews

    log.info("orchestrator ready")
    try:
        yield
    finally:
        # Previews first: a server outliving the orchestrator that started it
        # is the leak the whole record keeping exists to prevent.
        await previews.stop_all()
        await monitor.stop()
        await saga.stop()
        await supervisor.stop()
        for client in clients.values():
            if hasattr(client, "__aexit__"):
                await client.__aexit__(None, None, None)
        await checkpointer_pool.close()
        await app_pool.close()


def _monitor_window(settings: Settings) -> dict[str, int]:
    """The configured window, as rounds of probes an interval apart."""
    interval = settings.c4_monitor_interval_seconds
    return {"rounds": max(1, settings.c4_monitor_window_seconds // interval), "interval": interval}


def signed_in_for_tests() -> dict[str, str]:
    """The account tests act as: the identity from before sign-in."""
    return {"id": DEV_OWNER_ID, "email": "dev@localhost", "name": "Local development"}


@asynccontextmanager
async def lifespan_for_tests(app: FastAPI) -> AsyncIterator[None]:
    """The same wiring with an in memory checkpointer and no supervisor.

    `InMemorySaver` has identical interrupt and resume semantics, so graph
    behaviour can be tested without a database round trip. One integration test
    uses the Postgres saver to prove that wiring separately.

    Signed in, unless a test says otherwise: these tests are about runs, gates
    and versions, and sign-in has tests of its own, which remove the override.
    """
    app.dependency_overrides.setdefault(current_user, signed_in_for_tests)
    settings: Settings = app.state.settings
    app_pool = create_app_pool(settings.database_url, max_size=4)
    await app_pool.open(wait=True)
    app.state.pool = app_pool
    checkpointer = InMemorySaver()
    app.state.checkpointer = checkpointer
    # A canned component, never a real one. These tests are about runs,
    # gates, versions and resume, and none of that is more true for having
    # waited three minutes and spent money to find out. A test that wants a
    # different component sets `app.state.c1` before entering the lifespan.
    c1 = getattr(app.state, "c1", None) or CannedC1()
    c2 = getattr(app.state, "c2", None) or CannedC2()
    c3 = getattr(app.state, "c3", None) or CannedC3()
    c4 = getattr(app.state, "c4", None) or CannedC4()
    app.state.c1 = c1
    app.state.c2 = c2
    app.state.c3 = c3
    app.state.c4 = c4
    app.state.graph = build_graph(app_pool, checkpointer, c1)
    # Every component, because each phase's routes and its gate are part of
    # what these tests drive, and a graph that is only compiled in production
    # is a graph nothing has run.
    clients = {"c1": c1, "c2": c2, "c3": c3, "c4": c4}
    graphs = {
        "c1": app.state.graph,
        "c2": build_code_graph(app_pool, checkpointer, c2),
        "c3": build_testing_graph(app_pool, checkpointer, c3),
        "c4": build_deployment_graph(app_pool, checkpointer, c4),
    }
    app.state.clients = clients
    app.state.graphs = graphs
    # No background workers: tests drive `advance` themselves so the timing is
    # theirs rather than a race against a poller.
    app.state.supervisor = RunSupervisor(pool=app_pool, graphs=graphs, clients=clients)
    # Present but idle: the routes are reachable and nothing spawns a process
    # unless a test asks for one. No sweeper, so the timing stays the test's.
    app.state.previews = PreviewSupervisor(app_pool)
    # Idle too: no poller, so a window opens only when a test or a route asks.
    monitor = MonitorSupervisor(pool=app_pool, c4=c4, **_monitor_window(settings))
    app.state.monitor = monitor
    try:
        yield
    finally:
        await monitor.stop()
        await app_pool.close()


def create_app(settings: Settings | None = None, *, lifespan_factory=lifespan) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="SDLC orchestrator",
        version="0.1.0",
        summary="Projects, runs, gates, audit, and the design read model",
        lifespan=lifespan_factory,
    )
    app.state.settings = settings
    app.state.supervisor = None
    # Per app, so one app's wrong passwords never count against another's.
    app.state.sign_in_throttle = accounts.SignInThrottle()

    # Added first so it sits inside CORS: an unexpected error then answers with
    # the CORS headers the browser needs to read it (errors.AnswerUnexpectedErrors).
    app.add_middleware(AnswerUnexpectedErrors)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Authorization"],
    )

    install_error_handlers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Sign-in answers without a session; nothing else does. The dependency is
    # on each router rather than each route, so a route added later is behind
    # sign-in without anyone remembering to put it there.
    app.include_router(auth.router)
    signed_in = [Depends(current_user)]
    app.include_router(projects.router, dependencies=signed_in)
    app.include_router(design.router, dependencies=signed_in)
    app.include_router(code.router, dependencies=signed_in)
    app.include_router(testing.router, dependencies=signed_in)
    app.include_router(deployment.router, dependencies=signed_in)
    app.include_router(process.router, dependencies=signed_in)
    app.include_router(documents.router, dependencies=signed_in)
    app.include_router(connections.router, dependencies=signed_in)
    app.include_router(settings_api.router, dependencies=signed_in)

    return app


app = create_app()
