"""The baseline pin: the exact dependency set an analysis starts from.

Reading a lockfile is tested on a lockfile written out here, in npm's own v3
shape. Taking a pin is tested for real, once, against the npm registry, because
what is claimed is that npm itself resolved the tree; that test is marked
`sandbox` and skips without npm.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from c4.intake.lockfile import pin, resolved_versions, shifts

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")


def _lock(packages: dict) -> str:
    return json.dumps({"name": "generated-app", "lockfileVersion": 3, "packages": packages})


BEFORE = _lock(
    {
        "": {"name": "generated-app", "workspaces": ["apps/*", "packages/*"]},
        "apps/api": {
            "name": "@app/api",
            "dependencies": {"@app/contract": "*", "express": "^4.21.2"},
        },
        "node_modules/@app/contract": {"resolved": "packages/contract", "link": True},
        "node_modules/express": {"version": "4.21.2"},
        "node_modules/body-parser": {"version": "1.20.3"},
        "node_modules/qs": {"version": "6.13.0"},
        "node_modules/array-flatten": {"version": "1.1.1"},
    }
)

AFTER = _lock(
    {
        "": {"name": "generated-app", "workspaces": ["apps/*", "packages/*"]},
        "apps/api": {
            "name": "@app/api",
            "dependencies": {"@app/contract": "*", "express": "^5.1.0"},
        },
        "node_modules/@app/contract": {"resolved": "packages/contract", "link": True},
        "node_modules/express": {"version": "5.1.0"},
        "node_modules/body-parser": {"version": "2.2.0"},
        "node_modules/qs": {"version": "6.14.0"},
        "node_modules/router": {"version": "2.2.0"},
    }
)


def test_each_workspace_knows_what_its_direct_dependencies_resolved_to() -> None:
    """The version the update starts from is the resolved one, not the range."""
    assert resolved_versions(BEFORE)["apps/api"] == {"express": "4.21.2"}


def test_a_workspace_link_is_not_a_resolved_version() -> None:
    assert "@app/contract" not in resolved_versions(BEFORE)["apps/api"]


def test_an_update_names_every_package_it_moved_besides_itself() -> None:
    moved = {shift.package: shift for shift in shifts(BEFORE, AFTER, updated="express")}
    assert set(moved) == {"body-parser", "qs", "router", "array-flatten"}
    assert moved["body-parser"].change == "major"
    assert moved["qs"].change == "minor"
    assert (moved["router"].change, moved["router"].from_version) == ("added", None)
    assert (moved["array-flatten"].change, moved["array-flatten"].to_version) == ("removed", None)


@pytest.mark.sandbox
@needs_npm
def test_a_real_pin_records_exactly_the_lockfile_npm_wrote() -> None:
    files = {
        "package.json": json.dumps(
            {"name": "pinned", "private": True, "dependencies": {"is-number": "7.0.0"}}
        )
    }

    pinned = pin(files)

    assert pinned.record.lockfile_sha256 == hashlib.sha256(pinned.text.encode()).hexdigest()
    assert pinned.resolved[""] == {"is-number": "7.0.0"}
    assert pinned.record.direct == 1
    assert pinned.record.resolved_by.startswith("npm ")


def test_a_registry_too_slow_to_answer_is_a_reason_and_not_a_crash(monkeypatch) -> None:
    """The live walkthrough's second project timed out pinning on a slow network,
    and the timeout escaped as an exception that failed the whole run. Detection
    turns a pin that fails into a rejection of every npm dependency with the
    reason (FR3), so a timeout has to arrive as that failure."""
    import subprocess

    from c4.intake import lockfile
    from c4.intake.lockfile import PinFailed

    monkeypatch.setattr(lockfile.shutil, "which", lambda name: "/usr/bin/npm")

    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(lockfile.subprocess, "run", slow)
    with pytest.raises(PinFailed, match="did not resolve the tree within 300 s"):
        pin({"package.json": json.dumps({"name": "app", "dependencies": {"express": "^5.1.0"}})})


def test_a_pin_keeps_npm_s_cache_where_it_is_given(monkeypatch, tmp_path) -> None:
    """Every pin used to start from an empty npm cache and download each registry
    document again, which ran past the pin's five minutes on the walkthrough's slow
    network. Given a cache, every pin keeps it there, and each still runs in a
    scratch home, so nothing of this machine's npm configuration is read."""
    import subprocess

    from c4.intake import lockfile

    seen: list[dict[str, str]] = []

    def npm(argv, **kwargs):
        if "--version" in argv:
            return subprocess.CompletedProcess(argv, 0, "10.9.2\n", "")
        seen.append(kwargs["env"])
        (Path(kwargs["cwd"]) / "package-lock.json").write_text(_lock({"": {"name": "app"}}))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(lockfile.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(lockfile.subprocess, "run", npm)
    files = {"package.json": json.dumps({"name": "app"})}

    pin(files, cache=tmp_path / "npm")
    pin(files, cache=tmp_path / "npm")
    pin(files)

    kept, again, alone = seen
    assert kept["npm_config_cache"] == again["npm_config_cache"] == str(tmp_path / "npm")
    assert "c4-pin-" in kept["HOME"] and "c4-pin-" in again["HOME"]
    assert alone["npm_config_cache"] == str(Path(alone["HOME"]) / ".npm")
