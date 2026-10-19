"""Signal one, and the baseline: what moved between two version numbers (FR4).

The proposal's rule is positional: a major change is High, a minor one Medium, a
patch Low. `deploy_rules.semver_level` holds that mapping; this module decides
which position changed, per ecosystem, as each ecosystem defines its versions.

**npm is SemVer 2.0.0**, read strictly by python-semver. Prerelease and build
metadata are explicit: a build metadata difference does not change precedence
(SemVer item 10), so it is `build-only`; a change only in the prerelease part is
`prerelease`; and a 0.y.z source is flagged `initial-development`, because
SemVer itself says anything may change there, while the rule still maps by
position as FR4 states it.

**Maven is not SemVer.** Its versions are ordered by Maven's own
ComparableVersion, which univers implements, and that ordering decides whether
the move is an upgrade at all. Which position changed is read from the leading
dotted numbers as written, because univers normalises `1.0` to `1` and would
lose it: a fourth number is `beyond-patch`, a change after the numbers alone is
`qualifier`, and a version that does not begin with a number is `non-semver`.

A change outside FR4's three positions is mapped to patch by the rule and keeps
its own name here, so the study can count how often the rule had to stretch.
"""

import re
from dataclasses import dataclass
from typing import Literal

import semver
from sdlc_contracts import VersionChange, VersionFlag
from univers.versions import MavenVersion

#: Maven qualifiers that mark a release as not yet final, in Maven's own order.
_MAVEN_PRERELEASE = (
    "alpha",
    "a",
    "beta",
    "b",
    "milestone",
    "m",
    "rc",
    "cr",
    "snapshot",
    "ea",
    "preview",
)

_LEADING = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")


@dataclass(frozen=True)
class Movement:
    """Which position changed between two versions, and what else is true of them."""

    change: VersionChange
    flags: tuple[VersionFlag, ...] = ()


class SameRelease(ValueError):
    """The two versions are the same release, so there is no update to classify."""


def npm_movement(old: str, new: str) -> Movement:
    try:
        before = semver.Version.parse(old)
        after = semver.Version.parse(new)
    except ValueError:
        return Movement("unparseable")

    flags: list[VersionFlag] = []
    if before.major == 0:
        flags.append("initial-development")
    if after.prerelease:
        flags.append("prerelease-target")
    if before.build or after.build:
        flags.append("build-metadata")

    order = before.compare(after)
    if order > 0:
        return Movement("downgrade", tuple(flags))
    if order == 0:
        if before.build != after.build:
            return Movement("build-only", tuple(flags))
        raise SameRelease(f"{old} and {new} are the same release")
    if before.major != after.major:
        return Movement("major", tuple(flags))
    if before.minor != after.minor:
        return Movement("minor", tuple(flags))
    if before.patch != after.patch:
        return Movement("patch", tuple(flags))
    return Movement("prerelease", tuple(flags))


def _qualifier(rest: str) -> str:
    return rest.strip(".-_").lower()


def maven_movement(old: str, new: str) -> Movement:
    leading_old = _LEADING.match(old.strip())
    leading_new = _LEADING.match(new.strip())
    if leading_old is None or leading_new is None:
        return Movement("non-semver")
    try:
        before = MavenVersion(old)
        after = MavenVersion(new)
    except Exception:
        return Movement("unparseable")

    numbers_old = [int(part) for part in leading_old.group(1).split(".")]
    numbers_new = [int(part) for part in leading_new.group(1).split(".")]
    qualifier_old = _qualifier(leading_old.group(2))
    qualifier_new = _qualifier(leading_new.group(2))

    flags: list[VersionFlag] = []
    if numbers_old[0] == 0:
        flags.append("initial-development")
    if qualifier_new.startswith(_MAVEN_PRERELEASE):
        flags.append("prerelease-target")
    if qualifier_old or qualifier_new:
        flags.append("qualifier")

    if after < before:
        return Movement("downgrade", tuple(flags))
    if after == before:
        raise SameRelease(f"{old} and {new} are the same release")

    width = max(len(numbers_old), len(numbers_new))
    padded_old = numbers_old + [0] * (width - len(numbers_old))
    padded_new = numbers_new + [0] * (width - len(numbers_new))
    for position, (was, now) in enumerate(zip(padded_old, padded_new, strict=True)):
        if was != now:
            names: tuple[VersionChange, ...] = ("major", "minor", "patch")
            return Movement(names[position] if position < 3 else "beyond-patch", tuple(flags))
    return Movement("qualifier", tuple(flags))


def movement(ecosystem: Literal["npm", "maven"], old: str, new: str) -> Movement:
    """What moved between two versions of one package, in its ecosystem's terms."""
    return npm_movement(old, new) if ecosystem == "npm" else maven_movement(old, new)


def is_upgrade(ecosystem: Literal["npm", "maven"], old: str, new: str) -> bool:
    """Whether `new` is a later release than `old`, by the ecosystem's own ordering."""
    try:
        if ecosystem == "npm":
            return semver.Version.parse(new).compare(old) > 0
        return MavenVersion(new) > MavenVersion(old)
    except Exception:
        return False
