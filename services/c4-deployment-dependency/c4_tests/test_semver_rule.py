"""The SemVer rule's reading of two version numbers, case by case (FR4).

Every row is a pair a registry can really hand over. The npm rows are SemVer
2.0.0 as npm publishes it; the Maven rows include the shapes that make Maven
not SemVer: four numbers, flavour qualifiers, release candidates, a version
that is not numbers at all. The last class checks that the order the rule
relies on is the order each ecosystem's own library gives.
"""

import pytest
import semver
from c4.risk.semver_rule import SameRelease, is_upgrade, maven_movement, npm_movement
from sdlc_contracts import semver_level
from univers.versions import MavenVersion

NPM = [
    ("1.2.3", "2.0.0", "major", ()),
    ("1.2.3", "1.3.0", "minor", ()),
    ("1.2.3", "1.2.4", "patch", ()),
    ("1.2.3", "1.2.4-rc.1", "patch", ("prerelease-target",)),
    ("2.0.0-rc.1", "2.0.0-rc.2", "prerelease", ("prerelease-target",)),
    ("2.0.0-rc.2", "2.0.0", "prerelease", ()),
    ("1.2.3+ci.1", "1.2.3+ci.2", "build-only", ("build-metadata",)),
    ("0.2.3", "0.3.0", "minor", ("initial-development",)),
    ("0.0.3", "0.0.4", "patch", ("initial-development",)),
    ("2.0.0", "1.9.9", "downgrade", ()),
    ("1.2", "1.3", "unparseable", ()),
    ("v1.2.3", "v1.2.4", "unparseable", ()),
]

MAVEN = [
    ("2.7.3", "2.7.21", "patch", ()),
    ("5.3.30", "6.0.0", "major", ()),
    ("33.4.0-jre", "33.6.0-jre", "minor", ("qualifier",)),
    ("2.13.4", "2.13.4.2", "beyond-patch", ()),
    ("1.0-RC1", "1.0", "qualifier", ("qualifier",)),
    ("1.0", "1.1-beta-1", "minor", ("prerelease-target", "qualifier")),
    ("0.9.1", "0.10.0", "minor", ("initial-development",)),
    ("6.0.0", "5.3.30", "downgrade", ()),
    ("r09", "r10", "non-semver", ()),
]


@pytest.mark.parametrize(("old", "new", "change", "flags"), NPM)
def test_npm(old, new, change, flags) -> None:
    moved = npm_movement(old, new)
    assert (moved.change, moved.flags) == (change, flags)


@pytest.mark.parametrize(("old", "new", "change", "flags"), MAVEN)
def test_maven(old, new, change, flags) -> None:
    moved = maven_movement(old, new)
    assert (moved.change, moved.flags) == (change, flags)


class TestWhatTheRuleMakesOfIt:
    def test_a_major_is_high_a_minor_medium_a_patch_low(self) -> None:
        assert [
            semver_level(npm_movement("1.0.0", v).change) for v in ("2.0.0", "1.1.0", "1.0.1")
        ] == [
            "high",
            "medium",
            "low",
        ]

    def test_initial_development_still_maps_by_position(self) -> None:
        """SemVer says anything may change in 0.y.z. FR4 maps by position, so
        the rule does too, and the flag carries what SemVer says."""
        moved = npm_movement("0.2.3", "0.3.0")
        assert semver_level(moved.change) == "medium"
        assert "initial-development" in moved.flags

    def test_a_number_that_cannot_be_ordered_is_not_guessed(self) -> None:
        assert semver_level(maven_movement("r09", "r10").change) is None
        assert semver_level(npm_movement("1.2", "1.3").change) is None

    def test_the_same_release_is_not_an_update(self) -> None:
        with pytest.raises(SameRelease):
            npm_movement("1.2.3", "1.2.3")
        with pytest.raises(SameRelease):
            maven_movement("1.0", "1.0.0")


class TestTheOrderIsTheEcosystemsOwn:
    @pytest.mark.parametrize(
        ("old", "new", "change", "_"), [row for row in NPM if row[2] != "unparseable"]
    )
    def test_npm_agrees_with_python_semver(self, old, new, change, _) -> None:
        upgrade = semver.Version.parse(new).compare(old) > 0
        assert is_upgrade("npm", old, new) == upgrade
        assert (change == "downgrade") == (semver.Version.parse(new).compare(old) < 0)

    @pytest.mark.parametrize(
        ("old", "new", "change", "_"), [row for row in MAVEN if row[2] != "non-semver"]
    )
    def test_maven_agrees_with_comparable_version(self, old, new, change, _) -> None:
        assert is_upgrade("maven", old, new) == (MavenVersion(new) > MavenVersion(old))
        assert (change == "downgrade") == (MavenVersion(new) < MavenVersion(old))
