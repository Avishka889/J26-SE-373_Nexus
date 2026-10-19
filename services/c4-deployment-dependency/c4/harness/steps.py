"""The steps a project is verified with, defined once for staging and the study.

A generated MERN project is checked the way its own CI checks it (typecheck and
tests), then built, then booted and requested: the smoke step starts the one
process that serves both sides and asks it for the page and for each path given,
which for a generated project are the contract's GET endpoints that take no
parameter (`smoke_paths`). Staging runs these steps against a release
candidate, and the study runs the same steps against a project with and without
an update, so what the study counts as a break is exactly what staging would
have refused.
"""

import re
from pathlib import Path

from .container import StepSpec

#: Where the smoke script sits inside the container, beside the project.
SMOKE_SCRIPT = ".c4/smoke.mjs"

#: The port the smoke step starts the app on, inside the container.
SMOKE_PORT = 3001

#: How a generated MERN project's server is started (see its README).
MERN_START = "node --experimental-strip-types apps/api/src/server.ts"

#: Where a generated MERN project keeps the typed client C2 derives from its
#: API contract. Every method carries an `implements` header, which C2's own
#: agreement checker reads: `// implements get-tasks GET /tasks`.
MERN_CLIENT = "packages/contract/src/client.ts"

_IMPLEMENTS = re.compile(r"^\s*//\s*implements\s+\S+\s+GET\s+(/\S*)\s*$", re.MULTILINE)


def smoke_paths(files: dict[str, str]) -> list[str]:
    """The contract's GET endpoints that take no parameter, read from the generated client.

    Those are the requests a smoke check can make without inventing an id. A
    project without the client, or whose client declares no such endpoint, is
    smoke checked on its page alone.
    """
    client = files.get(MERN_CLIENT, "")
    return sorted({path for path in _IMPLEMENTS.findall(client) if "{" not in path})


def smoke_script() -> str:
    return (Path(__file__).parent / "smoke.mjs").read_text()


def smoke_step(paths: list[str], start: str, *, port: int = SMOKE_PORT) -> StepSpec:
    return StepSpec(
        "smoke", f"node {SMOKE_SCRIPT} {port} {' '.join(paths)} -- {start}", timeout=120
    )


def mern_steps(smoke_paths: list[str]) -> list[StepSpec]:
    """Typecheck, test, build, then boot and request `/` and each smoke path."""
    return [
        StepSpec("typecheck", "npm run typecheck", timeout=600),
        StepSpec("test", "npm test", timeout=900),
        StepSpec("build", "npm run build", timeout=900),
        smoke_step(["/", *smoke_paths], MERN_START),
    ]


def with_smoke_script(files: dict[str, str]) -> dict[str, str]:
    """The project's files plus the smoke script, which the smoke step runs."""
    return {**files, SMOKE_SCRIPT: smoke_script()}
