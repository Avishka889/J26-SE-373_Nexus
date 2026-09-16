"""Running a generated app, so somebody can look at it.

This is the highest risk code in the repository and it is worth saying why in
one place. Everything else here reads a database, calls a model, or writes a
file. This starts a long lived process that serves code a language model
wrote, on a port, from a button in a web page. The build sandbox already
executes `npm install`, so arbitrary execution is not new; what is new is that
the process stays up.

Four things keep that reasonable, and none of them is optional:

**A minimal explicit environment.** The orchestrator's own process holds the
provider keys, the database URL and the secret that encrypts stored tokens. A
child that inherited `os.environ` would hand all of that to generated code.
Install and build get the build sandbox's allowlist, which needs `HOME` and an
npm cache or every preview re-downloads the world; the server gets a tighter
one still, because a process that only has to listen needs neither.

**Loopback only.** The generated server binds `HOST`, defaulting to all
interfaces because a container must; a preview sets `127.0.0.1` so it is
reachable from this machine and nowhere else. On a shared network the default
would put a model's code on the LAN.

**Caps.** One per project, because a preview is of a project's current code
version and two would be two answers to one question. Three in total, because
this is somebody's laptop. The fourth is refused by name rather than evicting
one silently: killing something a person is looking at, to make room, is the
kind of quiet behaviour this codebase avoids everywhere else.

**A record that outlives the process.** The row in `app.previews` is what lets
a restarted orchestrator find and kill a server the previous one started.
Without it a hard kill leaks a process holding a port, permanently.
"""

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from psycopg_pool import AsyncConnectionPool

from .db import store

log = logging.getLogger(__name__)

#: One per project by key; three at once because this runs on a workstation.
GLOBAL_CAP = 3

#: Stopped after this long without anybody reading its status. The snapshot is
#: polled while a reader has the page open, so "nobody has looked in twenty
#: minutes" is a fair reading of "nobody is using it".
IDLE_SECONDS = 20 * 60

INSTALL_TIMEOUT = 420.0
BUILD_TIMEOUT = 240.0
BOOT_TIMEOUT = 40.0
#: How often the idle sweep runs.
SWEEP_SECONDS = 60.0

HOST = "127.0.0.1"


def _build_env() -> dict[str, str]:
    """What install and build may see: the build sandbox's allowlist.

    `HOME` and the npm cache are here and nowhere else, because npm needs them
    and a preview that re-downloaded its dependencies every time would take
    minutes rather than seconds.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "CI": "1",
        "npm_config_cache": str(Path(tempfile.gettempdir()) / "c2-npm-cache"),
    }


def _server_env(port: int) -> dict[str, str]:
    """What the long lived process may see, which is less.

    No `HOME`, no npm configuration, and above all nothing of this process's
    environment: it holds `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL`
    and `SECRET_KEY`, and generated code has no business reading any of them.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOST": HOST,
        "PORT": str(port),
        "NODE_ENV": "production",
    }


class PreviewRefused(RuntimeError):
    """The preview cannot start, for a reason a reader can act on."""


@dataclass(frozen=True)
class PreviewView:
    """What the browser is told. Never a pid, never a directory."""

    status: str
    code_version: int
    url: str | None
    error: str | None
    started_at: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "codeVersion": self.code_version,
            "url": self.url,
            "error": self.error,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
        }


def _free_port() -> int:
    """A port the operating system says is free.

    Released before the child claims it, so there is a small race; the
    alternative is a fixed range that collides with whatever the developer
    already has running.
    """
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _kill(pid: int) -> None:
    """Stop a process group, tolerating one that has already gone.

    The group rather than the process: `npm start` spawns node, and killing
    only the wrapper leaves a server holding the port.
    """
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        for _ in range(20):
            try:
                os.killpg(pid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.25)


class PreviewSupervisor:
    """Starts, watches and stops one preview per project."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool
        self._sweeper: asyncio.Task[None] | None = None

    # ------------------------------------------------------------- lifecycle

    async def start_sweeper(self) -> None:
        self._sweeper = asyncio.create_task(self._sweep_forever(), name="preview-sweeper")

    async def stop_all(self) -> None:
        """Shut every preview down with the orchestrator.

        A preview outliving the process that started it is the leak this exists
        to prevent, so shutdown is where it is prevented.
        """
        if self._sweeper is not None:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
            self._sweeper = None
        async with self._pool.connection() as conn:
            rows = await store.live_previews(conn)
        for row in rows:
            await self._tear_down(row, reason="the orchestrator shut down")

    async def reap_orphans(self) -> None:
        """Kill anything a previous process left running.

        A row saying running at startup describes a server this orchestrator
        did not spawn and cannot supervise. It still holds a port and still
        serves generated code, so it is killed rather than adopted.
        """
        async with self._pool.connection() as conn:
            rows = await store.live_previews(conn)
        for row in rows:
            log.warning(
                "reaping preview for %s left by an earlier process (pid %s, port %s)",
                row["project_id"],
                row["pid"],
                row["port"],
            )
            await self._tear_down(row, reason="the orchestrator restarted")

    async def _sweep_forever(self) -> None:
        while True:
            try:
                await asyncio.sleep(SWEEP_SECONDS)
                async with self._pool.connection() as conn:
                    rows = await store.idle_previews(conn, seconds=IDLE_SECONDS)
                for row in rows:
                    log.info("stopping idle preview for %s", row["project_id"])
                    await self._tear_down(row, reason="nobody had looked at it for a while")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the preview sweeper failed; it will try again")

    # ----------------------------------------------------------------- reads

    async def view(self, project_id: str) -> PreviewView | None:
        async with self._pool.connection() as conn:
            row = await store.get_preview(conn, project_id)
            if row is None:
                return None
            if row["status"] in {"starting", "running"}:
                await store.touch_preview(conn, project_id)
        return _view_of(row)

    # ---------------------------------------------------------------- writes

    async def start(self, project_id: str, *, code_version: int, sources: dict[str, str]):
        """Install, build and serve one version of one project's code."""
        if not sources:
            raise PreviewRefused("nothing has been generated for this project yet")

        async with self._pool.connection() as conn:
            existing = await store.get_preview(conn, project_id)
            live = await store.live_previews(conn)

        if existing is not None and existing["status"] in {"starting", "running"}:
            if existing["code_version"] == code_version:
                return _view_of(existing)
            # A newer version supersedes: the old process serves code the
            # reader is no longer looking at.
            await self._tear_down(existing, reason="a newer code version replaced it")
            live = [row for row in live if row["project_id"] != project_id]

        others = [row for row in live if row["project_id"] != project_id]
        if len(others) >= GLOBAL_CAP:
            names = ", ".join(row["project_id"] for row in others)
            raise PreviewRefused(
                f"{len(others)} previews are already running ({names}). Stop one before "
                "starting another: each is a real server on this machine."
            )

        port = _free_port()
        workdir = Path(tempfile.mkdtemp(prefix=f"c2-preview-{project_id}-"))
        for path, content in sources.items():
            target = workdir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        async with self._pool.connection() as conn:
            await store.put_preview(
                conn,
                project_id,
                code_version=code_version,
                port=port,
                pid=0,
                workdir=str(workdir),
                status="starting",
            )

        try:
            await self._install_and_build(workdir)
            pid = await self._spawn(workdir, port)
        except Exception as error:
            shutil.rmtree(workdir, ignore_errors=True)
            async with self._pool.connection() as conn:
                await store.set_preview_status(
                    conn, project_id, status="failed", error=str(error)[:500]
                )
                row = await store.get_preview(conn, project_id)
            assert row is not None
            return _view_of(row)

        async with self._pool.connection() as conn:
            row = await store.put_preview(
                conn,
                project_id,
                code_version=code_version,
                port=port,
                pid=pid,
                workdir=str(workdir),
                status="running",
            )
        return _view_of(row)

    async def stop(self, project_id: str) -> None:
        async with self._pool.connection() as conn:
            row = await store.get_preview(conn, project_id)
        if row is None:
            return
        await self._tear_down(row, reason=None)

    # --------------------------------------------------------------- helpers

    async def _install_and_build(self, workdir: Path) -> None:
        env = _build_env()
        for command, timeout, what in (
            (["npm", "install", "--no-audit", "--no-fund"], INSTALL_TIMEOUT, "install"),
            (["npm", "run", "build"], BUILD_TIMEOUT, "build"),
        ):
            done = await asyncio.to_thread(
                subprocess.run,
                command,
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if done.returncode != 0:
                tail = (done.stdout + done.stderr)[-600:]
                raise RuntimeError(f"npm {what} failed: {tail}")

    async def _spawn(self, workdir: Path, port: int) -> int:
        child = subprocess.Popen(
            ["npm", "start"],
            cwd=workdir,
            env=_server_env(port),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Its own process group, so stopping it stops node as well as the
            # npm wrapper, and its pid is the group id.
            start_new_session=True,
        )
        base = f"http://{HOST}:{port}"
        deadline = asyncio.get_running_loop().time() + BOOT_TIMEOUT
        async with httpx.AsyncClient(timeout=3.0) as client:
            while asyncio.get_running_loop().time() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(
                        f"the server exited with code {child.returncode} before answering"
                    )
                try:
                    await client.get(base + "/")
                    return child.pid
                except httpx.HTTPError:
                    await asyncio.sleep(0.4)
        _kill(child.pid)
        raise RuntimeError(f"the server did not answer on {base} within {BOOT_TIMEOUT:.0f}s")

    async def _tear_down(self, row: store.Row, *, reason: str | None) -> None:
        """Stop the process, delete the tree, record why."""
        if row["pid"]:
            await asyncio.to_thread(_kill, int(row["pid"]))
        shutil.rmtree(row["workdir"], ignore_errors=True)
        async with self._pool.connection() as conn:
            if reason is None:
                await store.delete_preview(conn, row["project_id"])
            else:
                await store.set_preview_status(
                    conn, row["project_id"], status="stopped", error=reason
                )


def _view_of(row: store.Row) -> PreviewView:
    running = row["status"] == "running"
    return PreviewView(
        status=row["status"],
        code_version=row["code_version"],
        url=f"http://{HOST}:{row['port']}" if running else None,
        error=row["error"],
        started_at=row["started_at"],
    )
