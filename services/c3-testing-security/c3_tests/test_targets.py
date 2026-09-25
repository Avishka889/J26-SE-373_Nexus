"""What a stage is allowed to point at, and what it refuses.

The refusals are the point of this file. Every lane installs packages, writes
reports and runs a mutation pass, so a target that resolved to the wrong
directory would not be a wrong number: it would be an afternoon spent working
out why this repository suddenly has a `node_modules` in it.
"""

from dataclasses import dataclass

import pytest
from c3.harness import UnusableTarget, resolve, sample_root, stage_copy
from c3.harness.targets import detect


@dataclass
class Ref:
    """The orchestrator's `TargetRef`, as the seam describes it."""

    kind: str
    code_version: int | None = None
    path: str = ""


class TestFindingTheStack:
    def test_a_workspace_root_is_not_where_the_tests_are(self, tmp_path) -> None:
        """Running vitest at the root of an npm workspace finds nothing.

        The generated project's package.json is a workspace declaration with no
        tests under it, so a lane that ran there would report a green suite of
        zero tests, which is the exact shape of lie this component exists to
        prevent.
        """
        (tmp_path / "package.json").write_text('{"workspaces": ["apps/*"]}')
        (tmp_path / "apps" / "web").mkdir(parents=True)
        (tmp_path / "apps" / "web" / "package.json").write_text("{}")

        stack, apps, why = detect(tmp_path)

        assert (stack, apps) == ("node", ("apps/web",))
        assert "apps/web" in why

    def test_a_single_app_is_found_at_the_root(self, tmp_path) -> None:
        (tmp_path / "package.json").write_text("{}")
        assert detect(tmp_path)[:2] == ("node", (".",))

    def test_a_pom_makes_it_java(self, tmp_path) -> None:
        (tmp_path / "pom.xml").write_text("<project/>")
        assert detect(tmp_path)[:2] == ("java", (".",))

    def test_nothing_recognisable_is_said_rather_than_guessed(self, tmp_path) -> None:
        (tmp_path / "README.md").write_text("a repository of prose")

        with pytest.raises(UnusableTarget, match="no stack this component can run"):
            resolve(Ref(kind="benchmark", path=str(tmp_path)))


class TestTheRefusals:
    def test_a_generated_target_without_a_workspace_says_who_should_have_made_one(self) -> None:
        with pytest.raises(UnusableTarget, match="materialises from the file store"):
            resolve(Ref(kind="generated", code_version=3))

    def test_a_sample_is_a_name_and_never_a_path(self) -> None:
        """`fixtures/../../..` would be this repository, and the lane would
        install packages and run mutation in it."""
        for attempt in ("../../..", "/etc", "a/b", ".hidden"):
            with pytest.raises(UnusableTarget, match="is not a sample name"):
                sample_root(attempt)

    def test_an_unknown_kind_lists_the_ones_that_exist(self) -> None:
        with pytest.raises(UnusableTarget, match="generated, sample, benchmark"):
            resolve(Ref(kind="whatever"))

    def test_a_benchmark_needs_its_checkout(self) -> None:
        with pytest.raises(UnusableTarget, match="needs the path of its checkout"):
            resolve(Ref(kind="benchmark"))


class TestTheCheckedInSample:
    def test_a_target_that_names_no_sample_gets_the_java_one(self) -> None:
        """The default is a real directory. It was not: the constant still said
        `spring-sample` after the fixture was renamed, so every `kind="sample"`
        target that did not name one refused with a file-not-found."""
        assert resolve(Ref(kind="sample")).root.name == "java-sample"

    def test_the_node_sample_resolves_to_its_app(self) -> None:
        repo = resolve(Ref(kind="sample", path="node-sample"))

        assert repo.stack == "node"
        assert repo.apps == ("apps/web",)
        assert (repo.root / "apps/web/src/total.ts").is_file()

    def test_a_repository_path_is_named_from_the_root(self) -> None:
        """A report that named `src/total.ts` would send a reader to a file
        that is not there: the repository calls it `apps/web/src/total.ts`."""
        repo = resolve(Ref(kind="sample", path="node-sample"))

        assert repo.relative("src/total.ts") == "apps/web/src/total.ts"
        assert repo.relative(repo.root / "apps/web/src/total.ts") == "apps/web/src/total.ts"


class TestTheWorkspaceCopy:
    def test_the_checked_in_tree_is_not_what_gets_measured(self, tmp_path) -> None:
        source = resolve(Ref(kind="sample", path="node-sample"))

        copy = stage_copy(source, tmp_path / "ws")

        assert copy.root != source.root
        assert copy.apps == source.apps
        assert (copy.root / "apps/web/src/total.ts").read_text() == (
            source.root / "apps/web/src/total.ts"
        ).read_text()

    def test_an_install_survives_a_second_copy(self, tmp_path) -> None:
        """Otherwise every stage of every run pays for a cold install."""
        source = resolve(Ref(kind="sample", path="node-sample"))
        workspace = tmp_path / "ws"
        stage_copy(source, workspace)
        (workspace / "node_modules").mkdir()
        (workspace / "node_modules" / "marker").write_text("expensive")

        stage_copy(source, workspace)

        assert (workspace / "node_modules" / "marker").read_text() == "expensive"

    def test_a_file_the_source_no_longer_has_is_cleared_out(self, tmp_path) -> None:
        """A test deleted upstream that stayed in the workspace would run, pass
        and be counted, which is a green number for a test that does not
        exist."""
        source = resolve(Ref(kind="sample", path="node-sample"))
        workspace = tmp_path / "ws"
        stage_copy(source, workspace)
        stale = workspace / "apps/web/src/__tests__/gone.test.ts"
        stale.write_text("// deleted upstream")

        stage_copy(source, workspace)

        assert not stale.exists()


class TestAMonorepoHasMoreThanOneRunner:
    def test_both_apps_are_found_and_kept(self, tmp_path) -> None:
        """A project with a web app and an API has two suites, two configs and
        one report. A lane that ran in only one of them would report the
        other's tests as not existing, which is how a filled test in `apps/api`
        was once refused because the collector had been started in `apps/web`.
        """
        (tmp_path / "package.json").write_text('{"workspaces": ["apps/*"]}')
        for app in ("apps/web", "apps/api"):
            (tmp_path / app).mkdir(parents=True)
            (tmp_path / app / "package.json").write_text("{}")

        stack, apps, why = detect(tmp_path)

        assert stack == "node"
        assert set(apps) == {"apps/web", "apps/api"}
        assert "apps/api" in why and "apps/web" in why

    def test_a_path_is_matched_to_the_app_that_owns_it(self, tmp_path) -> None:
        from c3.harness.targets import TargetRepo

        repo = TargetRepo(
            root=tmp_path, kind="generated", stack="node", apps=("apps/api", "apps/web")
        )

        assert repo.app_for("apps/web/src/total.ts") == "apps/web"
        assert repo.app_for("apps/api/src/app.ts") == "apps/api"
        assert repo.app_for("README.md") == "apps/api"


class TestResolvingForReadingRatherThanRunning:
    """A test lane needs a runner. A security scan needs only files."""

    def test_a_directory_with_no_build_is_refused_for_a_test_lane(self, tmp_path) -> None:
        (tmp_path / "a.java").write_text("class A {}\n")

        with pytest.raises(UnusableTarget) as raised:
            resolve(Ref(kind="benchmark", path=str(tmp_path)))

        assert "nothing was measured" in str(raised.value)

    def test_the_same_directory_is_fine_for_a_scan(self, tmp_path) -> None:
        """Declining to read a repository because it has no pom would be the
        security stage refusing its own job over a build system it does not
        use."""
        (tmp_path / "a.java").write_text("class A {}\n")

        repo = resolve(Ref(kind="benchmark", path=str(tmp_path)), must_run=False)

        assert repo.stack == "unknown"
        assert repo.detected_by, "and it says why it could not tell"
