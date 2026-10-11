"""How long each request took, in the server's log."""

from __future__ import annotations

import logging
import sys
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Its own logger with its own handler. The root logger shows warnings and up
#: and uvicorn configures only its own loggers, so an INFO line on any other
#: logger here never reaches the log.
LOGGER = "orchestrator.requests"

_log = logging.getLogger(LOGGER)
if not _log.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("TIMING:   %(message)s"))
    _log.addHandler(_handler)
_log.setLevel(logging.INFO)
_log.propagate = False


class TimeRequests:
    """One line per request: method, path, status and milliseconds.

    Uvicorn's access line has the status and no time, so a slow action could
    not be told from a slow network, nor one slow route from all of them.
    Added last, so it is outermost and times everything the request passes
    through. The path is logged without its query, which can carry what a
    person typed. A request that raised is timed and logged as a 500, and the
    exception goes on to whoever answers it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        began = time.perf_counter()
        answered = 500

        async def watching(message: Message) -> None:
            nonlocal answered
            if message["type"] == "http.response.start":
                answered = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, watching)
        finally:
            took = round((time.perf_counter() - began) * 1000)
            _log.info("%s %s %d %dms", scope["method"], scope["path"], answered, took)
