"""The monitor supervisor: one bounded window after every verified release, and none forever.

A release is watched once, soon after it is verified, and otherwise only when a
person asks (`POST /projects/{id}/deployment/monitoring/window`). Never
continuously: a free host probed forever never sleeps, and spends its monthly
hours on being watched.

A poller finds what to watch in the record, not in memory: verified releases
that still serve, finished within the last hour, and not probed since. So a
restart still watches a release verified just before it, and a release is
watched once, because its window's first probe is a sample after it finished.
At most one window runs per release. A release a later deployment replaced is
never watched: what its address serves is no longer its to answer for.

After each window C4 is asked what it suggests for requirements (FR22), and its
answer is kept for a person to send or not (`deploy/feedback.py`).
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from psycopg_pool import AsyncConnectionPool

from ..db import store
from .adapters.checks import Prober, probe
from .feedback import after_window
from .monitor import watch

log = logging.getLogger(__name__)

POLL_SECONDS = 10.0

#: Only a release verified this recently is watched without being asked; an
#: older one waits for a person to open a window.
RECENT_SECONDS = 3600


class MonitorSupervisor:
    def __init__(
        self,
        *,
        pool: AsyncConnectionPool,
        rounds: int,
        interval: float,
        c4: Any = None,
        prober: Prober = probe,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll_seconds: float = POLL_SECONDS,
        recent_seconds: int = RECENT_SECONDS,
        every_seconds: int = 0,
        for_seconds: int = 0,
        cloud: bool = False,
    ) -> None:
        self._pool = pool
        self._c4 = c4
        self._rounds = rounds
        self._interval = interval
        self._prober = prober
        self._sleep = sleep
        self._poll_seconds = poll_seconds
        self._recent_seconds = recent_seconds
        #: A window again on what still serves: how often, for how long after it
        #: went out, and whether a cloud release is included (review item C4-10).
        self._every_seconds, self._for_seconds, self._cloud = every_seconds, for_seconds, cloud
        self._windows: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._poller: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._poller = asyncio.create_task(self._poll(), name="monitor-poller")

    async def stop(self) -> None:
        tasks = [task for task in (self._poller, *self._windows.values()) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._windows.clear()
        self._poller = None

    def open(
        self,
        deployment_id: uuid.UUID,
        *,
        rounds: int | None = None,
        interval: float | None = None,
        quiet: bool = False,
    ) -> bool:
        """Start a window on one release unless one is running on it; whether one started."""
        if deployment_id in self._windows:
            return False
        task = asyncio.create_task(
            self._window(
                deployment_id, rounds or self._rounds, interval or self._interval, quiet=quiet
            ),
            name=f"monitor-{deployment_id}",
        )
        self._windows[deployment_id] = task
        task.add_done_callback(lambda _, key=deployment_id: self._windows.pop(key, None))
        return True

    def running(self) -> set[uuid.UUID]:
        return set(self._windows)

    async def wait(self) -> None:
        """Until every window running now has ended."""
        await asyncio.gather(*self._windows.values(), return_exceptions=True)

    async def sweep(self) -> list[uuid.UUID]:
        """One pass: a window on each verified release that is due one; their ids.

        A window opened again says nothing unless it finds something wrong: a
        line in the conversation every few hours is noise.
        """
        async with self._pool.connection() as conn:
            rows = await store.unwatched_releases(
                conn,
                recent_seconds=self._recent_seconds,
                every_seconds=self._every_seconds,
                for_seconds=self._for_seconds,
                cloud=self._cloud,
            )
        return [
            row["id"] for row in rows if self.open(row["id"], quiet=bool(row["watched_before"]))
        ]

    async def _window(
        self, deployment_id: uuid.UUID, rounds: int, interval: float, *, quiet: bool = False
    ) -> None:
        try:
            async with self._pool.connection() as conn:
                row = await store.get_deployment(conn, deployment_id)
                if row is not None and not quiet:
                    await store.post_thread_message(
                        conn,
                        row["project_id"],
                        kind="system",
                        author="platform",
                        content=(
                            f"Watching deploy version {row['deploy_version']}: {rounds} rounds, "
                            f"{interval:g}s apart."
                        ),
                        stage_id="monitoring",  # type: ignore[arg-type]
                    )
            report = await watch(
                self._pool,
                deployment_id,
                rounds=rounds,
                interval=interval,
                prober=self._prober,
                sleep=self._sleep,
            )
        except asyncio.CancelledError:
            raise
        except ValueError as refused:
            log.info("no monitoring window on %s: %s", deployment_id, refused)
            return
        except Exception:
            log.exception("the monitoring window on %s failed", deployment_id)
            return
        if self._c4 is None:
            return
        try:
            await after_window(self._pool, self._c4, report)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The window's report is kept either way; only the suggestions are missing.
            log.exception("feedback after the window on %s failed", deployment_id)

    async def _poll(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._poll_seconds)
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the monitor poller failed; it will try again")
