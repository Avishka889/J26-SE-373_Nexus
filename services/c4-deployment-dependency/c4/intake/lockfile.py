"""The exact dependency set an analysis starts from.

The generated projects carry no lockfile and caret ranges throughout, so every
install resolves whatever is newest inside each range at that moment, and until
this ran nothing recorded which versions the tested build had installed. The pin
is taken with `npm install --package-lock-only --ignore-scripts`: it resolves the
tree and writes `package-lock.json` without downloading packages or running
anyone's install scripts, in a scratch directory with a scrubbed environment.

This is the first record of those versions, not a recovery of the ones C3's
test run used, and the report says so. From here on the lockfile is committed
with every release, so a rollback restores an exact set and an update is an
explicit change to it rather than whatever the next install happened to pick.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sdlc_contracts import BaselinePin, TransitiveShift

from ..risk.semver_rule import SameRelease, npm_movement

#: A cold resolution of a real project's tree is tens of seconds.
PIN_TIMEOUT_SECONDS = 300

LOCKFILE = "package-lock.json"


class PinFailed(RuntimeError):
    """npm could not resolve the tree, with what it said."""


@dataclass(frozen=True)
class Pin:
    record: BaselinePin
    text: str
    #: Workspace path ("" for the root) to package name to the version resolved for it.
    resolved: dict[str, dict[str, str]]


def resolution_inputs(files: dict[str, str]) -> dict[str, str]:
    """Only what npm reads to resolve: the manifests, and an existing lockfile."""
    return {
        path: content
        for path, content in files.items()
        if (path.endswith("package.json") and "node_modules/" not in path) or path == LOCKFILE
    }


def scrubbed_environment(home: Path, *, cache: Path | None = None) -> dict[str, str]:
    """npm's environment: none of this machine's configuration, and a cache.

    `home` is a scratch directory, so no `.npmrc` of anyone's is read and no
    token reaches the registry. The cache is `cache` when the service keeps one
    between runs, and a scratch one inside `home` otherwise.

    A kept cache is safe to share. It holds the public registry's documents and
    nothing of a project's; npm verifies every entry when it is written and when
    it is read back, and its cache is built for several npm processes at once. It
    changes no result either: npm uses a cached document only while the registry
    says it is fresh, and asks whether a stale one is still current before using
    it. What it saves is the download. A pin resolves some hundreds of documents,
    and from an empty cache every pin fetched all of them again, which on the
    walkthrough's slow network ran past the pin's five minutes. npm never shrinks
    its cache itself: `npm cache verify --cache <dir>` collects what is unused.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "npm_config_cache": str(cache if cache is not None else home / ".npm"),
        "npm_config_ignore_scripts": "true",
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
    }


def npm_version() -> str:
    npm = shutil.which("npm")
    if npm is None:
        return "npm not installed"
    done = subprocess.run([npm, "--version"], capture_output=True, text=True, check=False)
    return f"npm {done.stdout.strip()}"


def resolved_versions(lock_text: str) -> dict[str, dict[str, str]]:
    """Every workspace's direct dependencies and the version each resolved to."""
    lock = json.loads(lock_text)
    packages = lock.get("packages") or {}
    resolved: dict[str, dict[str, str]] = {}
    for workspace, body in packages.items():
        if workspace.startswith("node_modules/") or "/node_modules/" in workspace:
            continue
        names: dict[str, str] = {}
        for section in (
            "dependencies",
            "devDependencies",
            "peerDependencies",
            "optionalDependencies",
        ):
            for name in body.get(section) or {}:
                nested = packages.get(f"{workspace}/node_modules/{name}".lstrip("/"))
                hoisted = packages.get(f"node_modules/{name}")
                entry = nested or hoisted
                if entry and not entry.get("link") and entry.get("version"):
                    names[name] = str(entry["version"])
        resolved[workspace] = names
    return resolved


def pin(files: dict[str, str], *, before: date | None = None, cache: Path | None = None) -> Pin:
    """Resolve the project's tree and record the lockfile npm writes for it.

    `before` resolves the tree as it would have resolved on that day, from the
    releases published by then (npm's `--before`). The product never passes it;
    the study does, to reconstruct a project installed some time ago, so that
    the updates since then include patches and minors and not only majors.

    `cache` is npm's cache to keep between pins (see `scrubbed_environment`).
    """
    npm = shutil.which("npm")
    if npm is None:
        raise PinFailed("npm is not installed, so the dependency tree cannot be resolved")
    with tempfile.TemporaryDirectory(prefix="c4-pin-") as scratch:
        root = Path(scratch) / "project"
        home = Path(scratch) / "home"
        home.mkdir()
        for path, content in resolution_inputs(files).items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        dated = [f"--before={before.isoformat()}"] if before else []
        try:
            done = subprocess.run(
                [
                    npm,
                    "install",
                    "--package-lock-only",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                    *dated,
                ],
                cwd=root,
                env=scrubbed_environment(home, cache=cache),
                capture_output=True,
                text=True,
                timeout=PIN_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as slow:
            # A registry too slow to answer is a reason every npm dependency
            # could not be assessed (FR3), not a stage that crashed.
            raise PinFailed(
                f"npm did not resolve the tree within {PIN_TIMEOUT_SECONDS} s; the registry "
                "may be slow or unreachable from here"
            ) from slow
        lockfile = root / LOCKFILE
        if done.returncode != 0 or not lockfile.exists():
            tail = (done.stderr or done.stdout).strip().splitlines()[-5:]
            raise PinFailed("npm could not resolve the tree: " + " | ".join(tail))
        text = lockfile.read_text()

    lock = json.loads(text)
    packages = lock.get("packages") or {}
    resolved = resolved_versions(text)
    return Pin(
        record=BaselinePin(
            lockfile_path=LOCKFILE,
            lockfile_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            packages=sum(
                1 for key in packages if key.startswith("node_modules/") or "/node_modules/" in key
            ),
            direct=sum(len(names) for names in resolved.values()),
            resolved_by=f"{npm_version()} install --package-lock-only --ignore-scripts"
            + (f" --before={before.isoformat()}" if before else ""),
        ),
        text=text,
        resolved=resolved,
    )


def shifts(before: str, after: str, *, updated: str) -> list[TransitiveShift]:
    """Packages an update moved without being asked to, read from two lockfiles."""

    def versions(text: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for key, body in (json.loads(text).get("packages") or {}).items():
            if "node_modules/" in key and body.get("version") and not body.get("link"):
                found[key.rsplit("node_modules/", 1)[-1]] = str(body["version"])
        return found

    old, new = versions(before), versions(after)
    moved = []
    for name in sorted(set(old) | set(new)):
        if name == updated or old.get(name) == new.get(name):
            continue
        if name not in old:
            change = "added"
        elif name not in new:
            change = "removed"
        else:
            try:
                change = npm_movement(old[name], new[name]).change
            except SameRelease:
                continue
        moved.append(
            TransitiveShift(
                package=name,
                from_version=old.get(name),
                to_version=new.get(name),
                change=change,
            )
        )
    return moved
