"""Which updates a client is crossed with, from the version it has installed.

A crossing is chosen by position, from what the registry lists at capture:

- **patch**: the newest release of the installed minor line;
- **minor**: the newest release of the installed major line, on a later minor;
- **major**: the registry's latest, when it is a later major.

Prereleases are never targets. The kind records how a crossing was chosen,
which is not a vote: the SemVer rule reads the two versions for itself, and the
study compares the two.
"""

import hashlib
from dataclasses import dataclass
from typing import Literal

import semver

CrossingKind = Literal["patch", "minor", "major"]


@dataclass(frozen=True)
class Releases:
    """What a registry lists for one package: every version, and its latest release."""

    versions: tuple[str, ...]
    latest: str | None


def _stable(version: str) -> semver.Version | None:
    try:
        parsed = semver.Version.parse(version)
    except ValueError:
        return None
    return None if parsed.prerelease else parsed


def targets(installed: str, releases: Releases) -> dict[CrossingKind, str]:
    """The patch, minor and major targets from one installed version, where each exists."""
    base = _stable(installed)
    if base is None:
        return {}
    newer = [v for v in (_stable(r) for r in releases.versions) if v is not None and v > base]
    found: dict[CrossingKind, str] = {}
    patches = [v for v in newer if (v.major, v.minor) == (base.major, base.minor)]
    if patches:
        found["patch"] = str(max(patches))
    minors = [v for v in newer if v.major == base.major and v.minor > base.minor]
    if minors:
        found["minor"] = str(max(minors))
    latest = _stable(releases.latest or "")
    if latest is not None and latest.major > base.major:
        found["major"] = str(latest)
    return found


#: The seed that orders candidates when a study takes some and not all of them.
SELECTION_SEED = "c4-seed-2026-09-27"


def selection_order(key: str) -> str:
    """A fixed, arbitrary order: a hash of the update's key, so nobody picks by hand."""
    return hashlib.sha256(f"{SELECTION_SEED}:{key}".encode()).hexdigest()
