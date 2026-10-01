"""BUMP's projects as clients: which dependencies are crossed, and how their POM is moved.

A two module project is written here in BUMP's shape: a root POM with a
property shared by two artifacts, a literal version in a module, the project's
own module, an imported BOM, a `${project.version}` and the dependency BUMP's
record updates. Only the first two are crossed, each moved in the text so
nothing else in the file changes.
"""

import pytest
from c4.eval.loaders.bump_crossings import Crossing, candidates, crossings, declared, edited
from c4.eval.loaders.crossings import Releases

ROOT = """<project>
  <groupId>io.example</groupId>
  <artifactId>parent</artifactId>
  <properties>
    <slf4j.version>1.7.25</slf4j.version>
    <dubbo.version>2.7.3</dubbo.version>
    <byte-buddy.version>1.12.8</byte-buddy.version>
  </properties>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.slf4j</groupId>
        <artifactId>slf4j-api</artifactId>
        <version>${slf4j.version}</version>
      </dependency>
      <dependency>
        <groupId>org.slf4j</groupId>
        <artifactId>slf4j-simple</artifactId>
        <version>${slf4j.version}</version>
      </dependency>
      <dependency>
        <groupId>net.bytebuddy</groupId>
        <artifactId>byte-buddy</artifactId>
        <version>${byte-buddy.version}</version>
      </dependency>
      <dependency>
        <groupId>org.apache.dubbo</groupId>
        <artifactId>dubbo</artifactId>
        <version>${dubbo.version}</version>
      </dependency>
      <dependency>
        <groupId>org.junit</groupId>
        <artifactId>junit-bom</artifactId>
        <version>5.8.2</version>
        <scope>import</scope>
      </dependency>
      <dependency>
        <groupId>io.example</groupId>
        <artifactId>core</artifactId>
        <version>${project.version}</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>
"""

MODULE = """<project>
  <artifactId>core</artifactId>
  <dependencies>
    <dependency>
      <groupId>net.bytebuddy</groupId>
      <artifactId>byte-buddy</artifactId>
      <version>1.12.8</version>
    </dependency>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
    </dependency>
  </dependencies>
</project>
"""

POMS = {"pom.xml": ROOT, "core/pom.xml": MODULE}
RECORD = {
    "breakingCommit": "d" * 40,
    "project": "p",
    "projectOrganisation": "o",
    "preCommitReproductionCommand": "docker run ghcr.io/x:" + "d" * 40 + "-pre",
}


def _found():
    return declared(POMS, breaking="org.apache.dubbo:dubbo")


class TestWhatIsCrossed:
    def test_the_bumped_dependency_the_projects_own_boms_and_managed_versions_are_left_out(
        self,
    ) -> None:
        coordinates = sorted(f"{d.group}:{d.artifact}@{d.pom}" for d in _found())
        assert coordinates == [
            "net.bytebuddy:byte-buddy@core/pom.xml",
            "net.bytebuddy:byte-buddy@pom.xml",
            "org.slf4j:slf4j-api@pom.xml",
            "org.slf4j:slf4j-simple@pom.xml",
        ]

    def test_a_shared_property_is_one_update_named_for_its_first_artifact(self) -> None:
        by_package = {c.package: c for c in candidates(_found())}
        assert set(by_package) == {"net.bytebuddy:byte-buddy", "org.slf4j:slf4j-api"}
        slf4j = by_package["org.slf4j:slf4j-api"]
        assert (slf4j.version, slf4j.edits) == ("1.7.25", (("pom.xml", "slf4j.version", ""),))


class TestMovingIt:
    def test_a_property_is_moved_and_nothing_else_in_the_file(self) -> None:
        slf4j = next(c for c in candidates(_found()) if c.package == "org.slf4j:slf4j-api")
        changed = edited(POMS, slf4j, "1.7.36")
        assert list(changed) == ["pom.xml"]
        assert changed["pom.xml"] == ROOT.replace(
            "<slf4j.version>1.7.25</slf4j.version>", "<slf4j.version>1.7.36</slf4j.version>"
        )

    def test_a_version_written_twice_is_one_update_that_moves_both_places(self) -> None:
        [buddy] = [c for c in candidates(_found()) if c.package == "net.bytebuddy:byte-buddy"]
        assert buddy.edits == (
            ("core/pom.xml", None, "net.bytebuddy:byte-buddy"),
            ("pom.xml", "byte-buddy.version", ""),
        )
        changed = edited(POMS, buddy, "1.17.7")
        assert changed["core/pom.xml"] == MODULE.replace(
            "<version>1.12.8</version>", "<version>1.17.7</version>"
        )
        assert "<byte-buddy.version>1.17.7</byte-buddy.version>" in changed["pom.xml"]

    def test_a_version_that_is_not_there_is_refused(self) -> None:
        buddy = next(c for c in candidates(_found()) if c.package == "net.bytebuddy:byte-buddy")
        with pytest.raises(ValueError, match=r"has no 1\.12\.8 to move"):
            edited({"pom.xml": ROOT, "core/pom.xml": MODULE.replace("1.12.8", "9.9.9")}, buddy, "2")


class TestTheCrossings:
    def test_each_target_is_a_case_named_for_its_project_and_update(self) -> None:
        found = candidates(_found())
        releases = {
            "net.bytebuddy:byte-buddy": Releases(("1.12.8", "1.12.23", "1.17.7"), "1.17.7"),
            "org.slf4j:slf4j-api": Releases(("1.7.25", "1.7.36", "2.0.17"), "2.0.17"),
        }

        every = crossings(RECORD, found, releases)

        kinds = {(c.candidate.package, c.kind): c.to_version for c in every}
        assert kinds == {
            ("net.bytebuddy:byte-buddy", "patch"): "1.12.23",
            ("net.bytebuddy:byte-buddy", "minor"): "1.17.7",
            ("org.slf4j:slf4j-api", "patch"): "1.7.36",
            ("org.slf4j:slf4j-api", "major"): "2.0.17",
        }
        buddy = next(c for c in every if c.to_version == "1.17.7")
        assert isinstance(buddy, Crossing)
        assert buddy.case_id == "bumpx-dddddddddddd-byte-buddy-1.12.8-1.17.7"
        assert buddy.key == "maven:net.bytebuddy:byte-buddy@1.12.8->1.17.7"


class _Run:
    def __init__(self, *outcomes: str) -> None:
        from c4.harness.container import StepRun

        self.steps = [
            StepRun(name, "mvn", 0 if outcome == "passed" else 1, outcome, 1.0, "")
            for name, outcome in zip(("compile", "test"), outcomes, strict=True)
        ]


def _record(commit: str, project: str) -> dict:
    return {
        "breakingCommit": commit,
        "project": project,
        "projectOrganisation": "o",
        "preCommitReproductionCommand": f"docker run ghcr.io/x:{commit}-pre",
        "updatedDependency": {
            "dependencyGroupID": "org.apache.dubbo",
            "dependencyArtifactID": "dubbo",
        },
    }


class TestTheBuild:
    def _build(self, tmp_path, records, *, control, quota=40, calls=None):
        from c4.eval.loaders.bump_crossings import build
        from c4.harness.reproduce import Reproduction, observed

        calls = calls if calls is not None else []

        def run_control(image, workdir):
            calls.append(("control", image))
            return control(image)

        def observe(image, workdir, poms, crossing, before):
            calls.append(("observe", crossing.case_id))
            after = _Run("passed", "passed")
            return Reproduction(
                baseline=[observed(run) for run in before.steps],
                candidate=[observed(run) for run in after.steps],
                warnings=[],
            )

        held = build(
            records,
            tmp_path,
            tmp_path.parent / "skips.json",
            releases_for=lambda names: {
                "net.bytebuddy:byte-buddy": Releases(("1.12.8", "1.12.23", "1.17.7"), "1.17.7"),
                "org.slf4j:slf4j-api": Releases(("1.7.25", "1.7.36", "2.0.17"), "2.0.17"),
            },
            captured_at="2026-09-28",
            dataset_commit="c" * 40,
            quota=quota,
            log=lambda *a, **k: None,
            read=lambda image: ("/p", POMS),
            run_control=run_control,
            observe=observe,
            parent_of=lambda url, commit: "e" * 40,
            toolchain=lambda image: "maven",
            remove=lambda image: calls.append(("remove", image)),
        )
        return held, calls

    def test_a_project_whose_control_fails_is_skipped_saying_why(self, tmp_path) -> None:
        out = tmp_path / "corpus"
        out.mkdir()
        failing = _record("a" * 40, "broken")
        working = _record("b" * 40, "fine")

        held, calls = self._build(
            out,
            [failing, working],
            control=lambda image: (
                _Run("passed", "failed") if "aaaa" in image else _Run("passed", "passed")
            ),
        )

        assert held == 2
        import json

        [skip] = json.loads((tmp_path / "skips.json").read_text())
        assert (
            skip["project"] == "o/broken"
            and "the control run fails here, at test" in skip["reason"]
        )
        written = sorted(path.name for path in out.glob("*.json"))
        assert len(written) == 2 and all(name.startswith("bumpx-bbbbbbbbbbbb-") for name in written)
        # Every image is removed, the failing project's too.
        assert [c for c in calls if c[0] == "remove"] == [
            ("remove", f"ghcr.io/x:{'a' * 40}-pre"),
            ("remove", f"ghcr.io/x:{'b' * 40}-pre"),
        ]

    def test_the_quota_holds_and_a_second_run_observes_nothing_again(self, tmp_path) -> None:
        out = tmp_path / "corpus"
        out.mkdir()
        records = [_record(f"{digit}" * 40, f"p{digit}") for digit in "123"]

        first, _ = self._build(
            out, records, control=lambda image: _Run("passed", "passed"), quota=3
        )
        # Room for more: the projects already observed are skipped, and only the third is run.
        again, calls = self._build(
            out, records, control=lambda image: _Run("passed", "passed"), quota=6, calls=[]
        )

        assert first == 3 and again == 5
        assert [c for c in calls if c[0] == "control"] == [("control", f"ghcr.io/x:{'3' * 40}-pre")]

    def test_a_failure_that_is_not_the_projects_is_tried_again(self, tmp_path) -> None:
        from c4.eval.loaders.bump_crossings import build

        out = tmp_path / "corpus"
        out.mkdir()

        def unreadable(image):
            raise RuntimeError("docker image failed: No such image")

        held = build(
            [_record("a" * 40, "unreachable")],
            out,
            tmp_path / "skips.json",
            releases_for=lambda names: {},
            captured_at="2026-09-28",
            dataset_commit="c" * 40,
            log=lambda *a, **k: None,
            read=unreadable,
            remove=lambda image: None,
        )

        assert held == 0
        assert not (tmp_path / "skips.json").exists()

    def test_a_download_that_failed_is_neither_a_skip_nor_a_case(self, tmp_path) -> None:
        out = tmp_path / "corpus"
        out.mkdir()
        controls = [_record("a" * 40, "offline-control")]

        held, _ = self._build(out, controls, control=lambda image: _Run("unavailable", "not-run"))

        assert held == 0 and not list(out.glob("*.json"))
        assert not (tmp_path / "skips.json").exists()

    def test_a_project_the_owner_dropped_is_recorded_and_never_pulled(self, tmp_path) -> None:
        import json

        out = tmp_path / "corpus"
        out.mkdir()
        dropped = _record("f" * 40, "google-cloud-java")
        dropped["projectOrganisation"] = "googleapis"
        calls: list = []

        held, calls = self._build(
            out, [dropped], control=lambda image: _Run("passed", "passed"), calls=calls
        )

        assert held == 0 and calls == []
        [skip] = json.loads((tmp_path / "skips.json").read_text())
        assert skip["project"] == "googleapis/google-cloud-java"
        assert "dropped by the owner" in skip["reason"]
