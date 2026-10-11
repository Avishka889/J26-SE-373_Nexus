"""Every request says how long it took, in the server's own log.

Choosing a release target took two or three seconds and the log could not say
where: uvicorn's access line has the status and no time.
"""

import logging
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.timing import LOGGER, TimeRequests


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TimeRequests)

    @app.post("/projects/{project_id}/deployment/target")
    async def target(project_id: str) -> dict[str, str]:
        return {"project": project_id}

    @app.get("/broken")
    async def broken() -> None:
        raise RuntimeError("no")

    return app


class _Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def _timed(call) -> list[str]:
    seen = _Lines()
    logger = logging.getLogger(LOGGER)
    logger.addHandler(seen)
    try:
        call(TestClient(_app(), raise_server_exceptions=False))
    finally:
        logger.removeHandler(seen)
    return seen.lines


def test_a_request_is_logged_with_its_method_path_status_and_time() -> None:
    lines = _timed(lambda client: client.post("/projects/p_1/deployment/target?by=x"))

    assert len(lines) == 1
    # The path without its query, which can carry what a person typed.
    assert re.fullmatch(r"POST /projects/p_1/deployment/target 200 \d+ms", lines[0])


def test_a_request_that_raised_is_timed_too() -> None:
    lines = _timed(lambda client: client.get("/broken"))

    assert len(lines) == 1
    assert re.fullmatch(r"GET /broken 500 \d+ms", lines[0])


def test_the_lines_are_written_at_info_whatever_the_root_logger_shows() -> None:
    # The orchestrator's own INFO lines never reached the log: the root logger
    # shows warnings and up, and uvicorn configures only its own loggers.
    logger = logging.getLogger(LOGGER)

    assert logger.isEnabledFor(logging.INFO)
    assert logger.handlers
    assert logger.propagate is False
