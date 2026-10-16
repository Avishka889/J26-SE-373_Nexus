"""Writing a generated project out of the file store so a lane can run it.

C3's harness works on a directory. The file store holds a version of a project
as rows. Somebody has to turn one into the other, and it has to be this side of
the seam: the component has no database access on purpose, so that the same
code runs whether it is imported or reached over HTTP.

Three decisions are worth stating.

**Keyed by version, not by project.** The honesty guard needs two versions of
the same project on disk at once: a repaired test has to be run against the
unchanged production code it was written for, which is the previous version.
One directory per project would make that impossible.

**Reused, not rebuilt.** A workspace keeps its `node_modules` and its `target`
between stages and between runs, because a cold install is minutes and a
testing run touches the same tree four times. Everything the store knows about
is rewritten from the store on every call, so what runs is always exactly the
version the run pinned; only what the store does not know about survives.

**Bounded by construction.** A workspace with an install in it is a few hundred
megabytes, and this machine has under six gigabytes. Materialising version N
removes that project's workspaces older than N-1, which keeps the current and
the previous, which is what the guard needs and nothing more. No clock is
involved, so a sweep can never delete a workspace a run is using.
"""

import shutil
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from .db import store

#: What a build leaves behind and what a materialise must not delete.
#:
#: The harness has the same list, for the copy it makes of a checked-in sample
#: (`c3.harness.targets.NOT_COPIED`), and the two have to agree: this is the
#: same fact seen from two sides, and a test asserts they still match. It is
#: not shared code because the orchestrator does not import the component.
PRESERVED = frozenset(
    {"node_modules", ".git", "target", ".stryker-tmp", "dist", "coverage", ".c3", "reports"}
)


def root(base: str) -> Path:
    return Path(base)


def workspace_path(base: str, project_id: str, code_version: int) -> Path:
    return root(base) / project_id / f"v{code_version}"


async def materialise(
    pool: AsyncConnectionPool, project_id: str, *, code_version: int, base: str
) -> Path:
    """Write every generated file at one code version into its workspace.

    Returns the directory. Raises when the version has no files: a lane pointed
    at an empty directory would install nothing, run nothing and report a suite
    of no tests, which is the shape of lie this component exists to prevent.
    """
    async with pool.connection() as conn:
        files = await store.code_files(conn, project_id, version=code_version)
    if not files:
        raise FileNotFoundError(
            f"{project_id} has no generated files at code version {code_version}, "
            "so there is no repository to test"
        )

    destination = workspace_path(base, project_id, code_version)
    destination.mkdir(parents=True, exist_ok=True)
    _clear(destination)
    for path, content in files.items():
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _forget_older_than(base, project_id, keep_from=code_version - 1)
    return destination


def _clear(destination: Path) -> None:
    """Remove what the store no longer has, keep what a build left.

    A file deleted upstream that stayed in the workspace would be compiled, run
    and counted: a green test for code that is not in the repository.
    """
    for existing in destination.iterdir():
        if existing.name in PRESERVED:
            continue
        if existing.is_dir():
            shutil.rmtree(existing, ignore_errors=True)
        else:
            existing.unlink(missing_ok=True)


def _forget_older_than(base: str, project_id: str, *, keep_from: int) -> None:
    """Delete this project's workspaces below a version, never above it."""
    project_root = root(base) / project_id
    if not project_root.is_dir():
        return
    for entry in project_root.iterdir():
        if not entry.is_dir() or not entry.name.startswith("v"):
            continue
        try:
            version = int(entry.name[1:])
        except ValueError:
            continue
        if version < keep_from:
            shutil.rmtree(entry, ignore_errors=True)


def forget(base: str, project_id: str) -> None:
    """Everything this project has on disk, for a project being deleted."""
    shutil.rmtree(root(base) / project_id, ignore_errors=True)
