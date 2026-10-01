"""The seed set's loaders: which updates a client is crossed with, and how each is observed.

The loaders decide what the study looks at, so each decision is pinned here:
which versions become targets, that a package two workspaces share is one
update moving both, that a selection is a fixed order and not a choice, that a
seeded client's files say what its definition says, and that the smoke step
fails when the app does not answer. The observing itself is the container lane,
which `test_container_lane.py` covers.
"""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from c4.eval.cases import CaseClient, CaseUpdate, LabelledCase, Observed, ObservedStep
from c4.eval.loaders import maven_negatives, npm_platform
from c4.eval.loaders.clients import files_sha256, read_client
from c4.eval.loaders.crossings import Releases, targets
from c4.eval.loaders.npm_seeded import SEEDED
from c4.eval.seed import (
    ATTEMPTS,
    PLATFORM_QUOTA,
    WORKED_CASE,
    _observed,
    by_quota,
    select_bump,
    select_platform,
)
from c4.eval.split import held_out
from c4.harness.container import Lane
from c4.harness.reproduce import Reproduction
from c4.harness.steps import SMOKE_SCRIPT, mern_steps, smoke_paths, smoke_script, smoke_step
from c4.intake.lockfile import Pin, pin
from sdlc_contracts import BaselinePin

from .docker import needs_docker

STUDIES = Path(__file__).resolve().parents[1] / "studies"

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")


class TestTargets:
    RELEASES = Releases(
        versions=("2.1.8", "2.1.9", "2.1.10", "2.2.0", "2.3.0-rc.1", "3.0.0-beta.1", "3.2.1"),
        latest="3.2.1",
    )

    def test_the_newest_patch_minor_and_major(self) -> None:
        assert targets("2.1.9", self.RELEASES) == {
            "patch": "2.1.10",
            "minor": "2.2.0",
            "major": "3.2.1",
        }

    def test_a_prerelease_is_never_a_target(self) -> None:
        """2.3.0-rc.1 is newer than 2.2.0 and still not the minor target."""
        assert targets("2.2.0", self.RELEASES) == {"major": "3.2.1"}

    def test_nothing_newer_is_no_crossing(self) -> None:
        assert targets("3.2.1", self.RELEASES) == {}

    def test_a_latest_tag_on_an_older_line_is_not_a_major(self) -> None:
        releases = Releases(versions=("4.0.0", "4.0.1", "5.0.0"), latest="4.0.1")
        assert targets("4.0.0", releases) == {"patch": "4.0.1"}

    def test_an_unreadable_installed_version_has_no_targets(self) -> None:
        assert targets("latest", self.RELEASES) == {}


def _pin(resolved: dict[str, dict[str, str]]) -> Pin:
    return Pin(
        record=BaselinePin(
            lockfile_path="package-lock.json",
            lockfile_sha256="0" * 64,
            packages=10,
            direct=3,
            resolved_by="npm 10.9.9 install --package-lock-only --ignore-scripts",
        ),
        text="{}",
        resolved=resolved,
    )


WORKSPACE_FILES = {
    "package.json": json.dumps({"name": "app", "workspaces": ["apps/*"]}),
    "apps/api/package.json": json.dumps(
        {
            "name": "@app/api",
            "dependencies": {"@app/contract": "*", "express": "^5.1.0"},
            "devDependencies": {"typescript": "^5.7.0"},
        }
    ),
    "apps/web/package.json": json.dumps(
        {"name": "@app/web", "devDependencies": {"typescript": "^5.7.0"}}
    ),
}


class TestPlatformCrossings:
    def test_a_package_two_workspaces_share_is_one_update_moving_both(self) -> None:
        found = npm_platform.crossings(
            WORKSPACE_FILES,
            _pin(
                {
                    "apps/api": {"express": "5.1.0", "typescript": "5.9.3"},
                    "apps/web": {"typescript": "5.9.3"},
                }
            ),
            {
                "typescript": Releases(("5.9.3", "7.0.2"), "7.0.2"),
                "express": Releases(("5.1.0", "5.2.1"), "5.2.1"),
            },
        )
        by_package = {c.package: c for c in found}
        assert set(by_package) == {"express", "typescript"}
        assert by_package["typescript"].workspaces == ("apps/api", "apps/web")
        assert by_package["typescript"].manifest_paths == (
            "apps/api/package.json",
            "apps/web/package.json",
        )
        assert (by_package["express"].kind, by_package["express"].to_version) == ("minor", "5.2.1")

    def test_a_workspace_package_is_never_crossed(self) -> None:
        found = npm_platform.crossings(
            WORKSPACE_FILES,
            _pin({"apps/api": {"express": "5.1.0"}}),
            {"@app/contract": Releases(("0.1.0", "9.0.0"), "9.0.0")},
        )
        assert found == []

    def test_the_case_id_is_readable_and_url_safe(self) -> None:
        crossing = npm_platform.Crossing(
            "@vitejs/plugin-react", "4.7.0", "6.1.1", "major", ("apps/web",), (), "dev"
        )
        assert crossing.case_id == "platform-vitejs-plugin-react-4.7.0-6.1.1"


class TestSelection:
    def test_the_order_is_fixed_whatever_order_the_candidates_arrive_in(self) -> None:
        keys = [f"npm:pkg{i}@1.0.0->{i % 3 + 1}.0.0" for i in range(40)]
        kind = {1: "patch", 2: "minor", 3: "major"}
        quota = {"major": 3, "minor": 3, "patch": 2}

        def take(order: list[str]) -> list[str]:
            return by_quota(order, lambda k: kind[int(k[-5])], lambda k: k, quota)

        assert take(keys) == take(list(reversed(keys)))
        assert len(take(keys)) == 8

    def test_bump_selection_is_the_worked_case_then_the_quota_from_the_dev_split(self) -> None:
        cases = [_bump_case(WORKED_CASE, "2.7.3", "2.7.21", "patch", "org.apache.dubbo:dubbo")]
        cases += [_bump_case(f"bump-{i:012d}", "1.0.0", f"{i + 2}.0.0", "major") for i in range(9)]
        cases += [_bump_case(f"bump-m{i:011d}", "1.0.0", f"1.{i + 1}.0", "minor") for i in range(9)]
        dev = [c for c in cases if c.split == "dev"]
        chosen = select_bump(cases)
        assert chosen[0].case_id == WORKED_CASE
        assert all(case.split == "dev" for case in chosen)
        kinds = [c.source_change for c in chosen[1:]]
        assert kinds.count("major") == min(3, sum(c.source_change == "major" for c in dev))
        assert kinds.count("minor") == min(2, sum(c.source_change == "minor" for c in dev))

    def test_platform_crossings_are_taken_from_the_dev_split_up_to_the_quota(self) -> None:
        every = [
            npm_platform.Crossing(f"pkg-{i}", "1.0.0", target, kind, (), (), "dev")
            for i in range(30)
            for kind, target in (("patch", "1.0.1"), ("minor", "1.1.0"), ("major", "2.0.0"))
        ]
        chosen = select_platform(every)
        assert chosen and not any(
            held_out(f"npm:{c.package}@{c.from_version}->{c.to_version}") for c in chosen
        )
        assert {k: sum(c.kind == k for c in chosen) for k in PLATFORM_QUOTA} == PLATFORM_QUOTA

    def test_bump_selection_refuses_to_go_on_without_the_worked_case(self) -> None:
        with pytest.raises(SystemExit):
            select_bump([_bump_case("bump-000000000001", "1.0.0", "2.0.0", "major")])


def _bump_case(case_id: str, old: str, new: str, change: str, package: str = "") -> LabelledCase:
    return LabelledCase(
        case_id=case_id,
        source="bump",
        client=CaseClient(kind="github"),
        update=CaseUpdate(
            ecosystem="maven",
            package=package or f"org.example:{case_id}",
            from_version=old,
            to_version=new,
        ),
        source_change=change,
        observed=Observed(
            method="bump-recorded",
            captured_at="2026-09-27",
            candidate=[ObservedStep(name="compile", outcome="failed")],
            failure_category="COMPILATION_FAILURE",
        ),
        provenance="written for the test",
    )


class TestTheClients:
    def test_every_seeded_client_declares_its_package_at_the_version_its_case_starts_from(
        self,
    ) -> None:
        """A definition and its files cannot drift apart: the control run
        installs what the definition says, and the manifest must agree."""
        for seeded in SEEDED:
            files = read_client(STUDIES / "clients" / "seeded" / seeded.client)
            manifest = json.loads(files["package.json"])
            declared = {
                **manifest.get("dependencies", {}),
                **manifest.get("devDependencies", {}),
            }
            assert declared == {seeded.package: seeded.from_version}, seeded.client

    def test_the_java_client_sets_its_junit_version_in_one_property(self) -> None:
        files = read_client(STUDIES / "clients" / "java-records")
        installed = maven_negatives.installed_version(files)
        moved = maven_negatives.with_version(files, "6.0.0")
        assert maven_negatives.installed_version(moved) == "6.0.0"
        changed = [path for path in files if files[path] != moved[path]]
        assert changed == ["pom.xml"]
        assert installed != "6.0.0"

    def test_a_pom_without_the_property_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"junit\.version"):
            maven_negatives.with_version({"pom.xml": "<project/>"}, "6.0.0")

    def test_a_client_is_read_without_what_an_install_or_a_build_left_behind(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "node_modules" / "x").mkdir(parents=True)
        (tmp_path / "node_modules" / "x" / "index.js").write_text("junk")
        (tmp_path / "apps" / "web" / "dist").mkdir(parents=True)
        (tmp_path / "apps" / "web" / "dist" / "index.html").write_text("built")
        (tmp_path / "apps" / "web" / "distance.ts").write_text("kept")
        (tmp_path / "package.json").write_text("{}")
        assert set(read_client(tmp_path)) == {"apps/web/distance.ts", "package.json"}

    def test_the_client_hash_is_over_content_not_reading_order(self) -> None:
        one = {"a": "1", "b": "2"}
        assert files_sha256(one) == files_sha256(dict(reversed(one.items())))
        assert files_sha256(one) != files_sha256({"a": "1", "b": "3"})


class TestTheSteps:
    def test_a_generated_project_is_checked_as_staging_checks_it(self) -> None:
        steps = mern_steps(["/tasks"])
        assert [s.name for s in steps] == ["typecheck", "test", "build", "smoke"]
        assert " / /tasks -- " in steps[-1].command

    def test_the_smoke_paths_are_the_contracts_get_endpoints_without_a_parameter(self) -> None:
        """Read from the generated client's `implements` headers: the task tracker
        can list tasks but has no list of task lists, only one by id."""
        files = read_client(STUDIES / "clients" / "task-tracker")
        assert smoke_paths(files) == ["/tasks"]

    def test_a_project_without_the_client_is_smoke_checked_on_its_page_alone(self) -> None:
        assert smoke_paths({"package.json": "{}"}) == []


SERVER = """
import http from "node:http";
const failing = process.env.FAIL_PATH;
if (process.env.CRASH) throw new Error("the app could not start");
http.createServer((req, res) => {
  res.statusCode = req.url === failing ? 500 : 200;
  res.end("ok");
}).listen(Number(process.env.PORT), process.env.HOST);
"""


@pytest.mark.docker
@needs_docker
class TestTheSmokeCheck:
    """The smoke step's outcome is the check's: it passes only when every path answered."""

    def _run(self, env: str) -> tuple[str, str]:
        step = smoke_step(["/", "/items"], f"{env} node server.mjs")
        result = Lane().run({"server.mjs": SERVER, SMOKE_SCRIPT: smoke_script()}, [step])
        return result.steps[0].outcome, result.steps[0].output

    def test_every_path_answering_passes(self) -> None:
        outcome, output = self._run("env")
        assert outcome == "passed", output
        assert "GET /items 200" in output

    def test_a_path_that_fails_fails_the_step(self) -> None:
        outcome, output = self._run("env FAIL_PATH=/items")
        assert outcome == "failed"
        assert "GET /items 500  FAILED" in output

    def test_an_app_that_cannot_start_fails_the_step_and_says_why(self) -> None:
        outcome, output = self._run("env CRASH=1")
        assert outcome == "failed"
        assert "exited" in output and "the app could not start" in output


@pytest.mark.sandbox
@needs_npm
def test_a_tree_can_be_reconstructed_as_installed_on_an_earlier_day() -> None:
    """Express 5.1.0 was published on 2025-03-31 and 5.2.0 later, so a caret
    range resolved as of 2025-06-01 must land on 5.1.0, whatever is newest now."""
    files = {"package.json": json.dumps({"name": "c", "dependencies": {"express": "^5.0.0"}})}
    pinned = pin(files, before=date(2025, 6, 1))
    assert pinned.resolved[""]["express"] == "5.1.0"
    assert "--before=2025-06-01" in pinned.record.resolved_by


def test_the_seed_pins_the_study_client_the_generator_wrote() -> None:
    """The platform client is C2's output as C3 tested it: no lockfile of its own."""
    files = read_client(STUDIES / "clients" / "task-tracker")
    assert "package-lock.json" not in files
    assert json.loads(files["package.json"])["workspaces"] == ["apps/*", "packages/*"]


BUMP_CHECKOUT = Path.home() / ".cache" / "sdlc-c4" / "bump"


@pytest.mark.corpus
@pytest.mark.skipif(
    not (BUMP_CHECKOUT / "data" / "benchmark").is_dir(),
    reason=f"no BUMP checkout at {BUMP_CHECKOUT}",
)
def test_a_bump_checkout_reads_the_same_on_any_day() -> None:
    """Cases carry the checkout's commit date, not the day they were read, so the
    corpus hash of one checkout never changes."""
    from c4.eval.loaders.bump import dataset_version, load_checkout
    from c4.eval.study import corpus_hash

    commit, day = dataset_version(BUMP_CHECKOUT)
    cases = load_checkout(BUMP_CHECKOUT)
    assert {case.observed.captured_at for case in cases} == {day}
    assert all(commit in case.provenance for case in cases)
    assert WORKED_CASE in {case.case_id for case in cases}
    assert corpus_hash(cases) == corpus_hash(load_checkout(BUMP_CHECKOUT))


def _reproduction(install: str) -> Reproduction:
    return Reproduction(
        baseline=[ObservedStep(name="resolution", outcome="passed")],
        candidate=[ObservedStep(name="resolution", outcome=install)],
        warnings=[],
    )


class TestObservingAgain:
    def test_a_run_a_download_cut_short_is_observed_again_and_counted(self) -> None:
        runs = iter([_reproduction("unavailable"), _reproduction("failed")])
        reproduction, attempts = _observed(lambda: next(runs), "case")
        assert attempts == 2
        assert reproduction.candidate[0].outcome == "failed"

    def test_a_real_failure_is_never_observed_again(self) -> None:
        """Only the network's failures are retried; the update's stand at once."""
        calls = []

        def observe() -> Reproduction:
            calls.append(1)
            return _reproduction("failed")

        _, attempts = _observed(observe, "case")
        assert (attempts, len(calls)) == (1, 1)

    def test_a_case_that_never_gets_a_clean_run_is_kept_for_the_rubric_to_exclude(self) -> None:
        reproduction, attempts = _observed(lambda: _reproduction("unavailable"), "case")
        assert attempts == ATTEMPTS
        assert reproduction.candidate[0].outcome == "unavailable"


SEED = STUDIES / "cases" / "seed"


def test_every_seed_case_matches_the_client_and_the_pin_it_names() -> None:
    """A client edited, or a pin re-resolved, without observing again would leave
    cases that describe files nobody can run any more. The hashes say so here."""
    from c4.eval.__main__ import load_cases
    from c4.eval.loaders.clients import text_sha256

    root = STUDIES.parent
    cases = load_cases(SEED)
    assert cases, "the seed set is empty"
    for case in cases:
        if case.client.snapshot:
            files = read_client(root / case.client.snapshot)
            assert files_sha256(files) == case.client.snapshot_sha256, case.case_id
        for path, digest in case.frozen_inputs.items():
            assert text_sha256((root / path).read_text()) == digest, (case.case_id, path)


class TestVotesClients:
    """What the votes runner reads for each case, before any signal runs."""

    def test_a_platform_case_reads_its_frozen_client_and_the_lockfile_it_recorded(
        self,
    ) -> None:
        from c4.eval.__main__ import load_cases
        from c4.eval.votes import client_for, update_for

        case = next(c for c in load_cases(SEED) if c.case_id.startswith("platform-supertest"))
        client = client_for(case, STUDIES)
        assert "package-lock.json" in client.files and "apps/api/src/app.ts" in client.files
        update = update_for(case, client.files)
        assert update.key == case.update.key
        assert update.manifest_path == "apps/api/package.json"
        assert (update.change, update.from_version) == ("minor", case.update.from_version)
