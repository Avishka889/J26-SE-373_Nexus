"""The candidate a release is built from, fixed before anything is built.

A candidate is three things: the code version C2 generated, the lockfile with
the updates the run includes applied to the baseline pin, and the deployment
layer generated here. Its hash is taken over all of them, by path and content,
except the one file that carries the hash (`release.json`, which the frontend's
build serves at `/release.json`). Staging builds exactly this candidate and
checks the container serves this hash; a release deploys it and checks the same;
a rollback is reported restored only when the served hash is the verified one.

**Updates become explicit lockfile changes.** Each included update is applied
to the baseline pin with `npm install <package>@<version> --package-lock-only
--ignore-scripts`, in the workspace whose manifest declares it, in a scratch
directory with the same scrubbed environment as the pin: npm resolves the tree
and rewrites the lockfile and that manifest, and downloads no package and runs
nobody's script. The manifest keeps npm's default caret, now from the new
version, so the project reads as C2 writes it; the lockfile is what pins.

An update npm cannot resolve is not quietly dropped from the run: it is left
out of the lockfile with what npm said, and staging then finds the candidate
without an update the run included, and does not verify it.
"""

import posixpath
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sdlc_contracts import DependencyUpdate

# The hash is a rule a release checks too, so it lives with the rules; it is
# re-exported here for the pipeline's own callers.
from sdlc_contracts.deploy_rules import candidate_hash as candidate_hash

from ..intake.lockfile import (
    LOCKFILE,
    PIN_TIMEOUT_SECONDS,
    npm_version,
    resolution_inputs,
    scrubbed_environment,
)


def image_tag(project_slug: str, version: int) -> str:
    """The candidate's image, as staging builds it and the plan and manifests name it."""
    return f"sdlc-c4-{project_slug}:v{version}"


def fingerprint_path(frontend_dir: str) -> str:
    """Where the fingerprint lives: Vite copies `public/` into the build's root."""
    return f"{frontend_dir}/public/release.json"


@dataclass(frozen=True)
class Resolution:
    lockfile: str
    #: The manifests npm rewrote, by path, and only those.
    manifests: dict[str, str] = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)
    #: Update id to what npm said when it could not apply that update.
    refused: dict[str, str] = field(default_factory=dict)
    resolved_by: str = ""


#: What turns the baseline and the included updates into a candidate's
#: dependencies. The product's is `resolve`; tests pass their own.
Resolver = Callable[[dict[str, str], list[DependencyUpdate]], Resolution]


class ResolutionFailed(RuntimeError):
    """npm is missing, or there is no baseline to apply updates to."""


def _workspaces(update: DependencyUpdate) -> list[str | None]:
    """Every workspace that declares the update, the root as None, each once."""
    found: list[str | None] = []
    for manifest in (update.manifest_path, *update.also_declared_in):
        workspace = posixpath.dirname(manifest) or None
        if workspace not in found:
            found.append(workspace)
    return found


def resolve(
    files: dict[str, str], updates: list[DependencyUpdate], *, cache: Path | None = None
) -> Resolution:
    """Every update applied to the baseline pin in turn, each on the one before it.

    `cache` is npm's cache to keep between runs, the one the baseline pin used
    (see `scrubbed_environment`), so npm finds most of what it needs already there.
    """
    npm = shutil.which("npm")
    if npm is None:
        raise ResolutionFailed("npm is not installed, so no update can be applied")
    if LOCKFILE not in files:
        raise ResolutionFailed("there is no baseline lockfile to apply the updates to")
    inputs = resolution_inputs(files)
    applied: list[str] = []
    refused: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="c4-candidate-") as scratch:
        root = Path(scratch) / "project"
        home = Path(scratch) / "home"
        home.mkdir()
        for path, content in inputs.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        for update in updates:
            if update.ecosystem != "npm":
                refused[update.id] = (
                    f"{update.ecosystem} updates are not applied to an npm lockfile"
                )
                continue
            before = {path: (root / path).read_text() for path in inputs}
            failure = ""
            # In every workspace that declares it: an update applied to one
            # manifest of two ships half applied, with the other still asking
            # for the old range.
            for workspace in _workspaces(update):
                try:
                    done = subprocess.run(
                        [
                            npm,
                            "install",
                            f"{update.package}@{update.to_version}",
                            "--package-lock-only",
                            "--ignore-scripts",
                            "--no-audit",
                            "--no-fund",
                            *(["--workspace", workspace] if workspace else []),
                        ],
                        cwd=root,
                        env=scrubbed_environment(home, cache=cache),
                        capture_output=True,
                        text=True,
                        timeout=PIN_TIMEOUT_SECONDS,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    failure = f"it did not finish within {PIN_TIMEOUT_SECONDS} s"
                    break
                if done.returncode != 0:
                    failure = " | ".join((done.stderr or done.stdout).strip().splitlines()[-5:])
                    break
            if failure:
                for path, content in before.items():
                    (root / path).write_text(content)
                refused[update.id] = "npm could not apply it: " + failure
                continue
            applied.append(update.id)
        after = {path: (root / path).read_text() for path in inputs}
    return Resolution(
        lockfile=after[LOCKFILE],
        manifests={
            path: text for path, text in after.items() if path != LOCKFILE and text != inputs[path]
        },
        applied=applied,
        refused=refused,
        resolved_by=f"{npm_version()} install <package>@<version> --package-lock-only "
        "--ignore-scripts",
    )
