"""Table 6, part one: the counts are the verdicts, and a check that did not run is not a pass.

Two of the study's real projects are generated under every variant with the
linters kept out, and then with one planted failure, and the counts, the
validity of each generation and the table are checked against both.
"""

from datetime import UTC, datetime
from pathlib import Path

from c4.eval.pipeline_study import VARIANTS, render_table, run
from c4.pipeline.validate import validate
from sdlc_contracts import FileValidation

CLIENTS = Path(__file__).parents[1] / "studies" / "clients"
PROJECTS = [CLIENTS / "task-tracker", CLIENTS / "c2-rule" / "calculator"]
NOW = datetime(2026, 9, 28, tzinfo=UTC)


def _no_linters(files):
    return validate(files, docker_reason="not run in this test")


def _everything_passes(files):
    """Every check a file would get, each passing, as a Docker machine would report."""
    verdicts = _no_linters(files)
    return {
        path: [
            check
            if check.outcome != "not-run"
            else FileValidation(validator=check.validator, tool=check.tool, outcome="passed")
            for check in checks
        ]
        for path, checks in verdicts.items()
    }


class TestTheCounts:
    def test_a_check_that_did_not_run_is_counted_as_such_and_valid_is_never_claimed(self) -> None:
        record = run(PROJECTS, commit="abc1234", validator=_no_linters, now=NOW)
        assert len(record["generations"]) == len(PROJECTS) * len(VARIANTS) == 6
        linters = {name: record["byValidator"][name] for name in ("actionlint", "hadolint")}
        assert all(counts["notRun"] == counts["checked"] > 0 for counts in linters.values())
        assert record["byValidator"]["kubeconform"]["notRun"] == 2 * len(PROJECTS)
        assert record["overall"]["valid"] == 0
        assert record["byValidator"]["secret-scan"]["passed"] == record["overall"]["files"]

    def test_with_every_check_passing_every_generation_is_valid(self) -> None:
        record = run(PROJECTS, commit="abc1234", validator=_everything_passes, now=NOW)
        assert record["overall"]["valid"] == record["overall"]["generations"] == 6
        # 7 files for each project under private and public, 9 with Kubernetes.
        assert record["overall"]["files"] == len(PROJECTS) * (7 + 7 + 9)

    def test_a_planted_failure_invalidates_that_projects_generations_only(self) -> None:
        def planted(files):
            verdicts = _everything_passes(files)
            if "calculator" in files.get("render.yaml", ("", ""))[1]:
                verdicts["render.yaml"] = [
                    FileValidation(
                        validator="json-schema",
                        tool="planted",
                        outcome="failed",
                        findings=["services/0/plan: planted"],
                    )
                ]
            return verdicts

        record = run(PROJECTS, commit="abc1234", validator=planted, now=NOW)
        assert record["byProject"]["calculator"]["valid"] == 0
        assert record["byProject"]["task-tracker"]["valid"] == 3
        assert record["byValidator"]["json-schema"]["failed"] == 3
        table = render_table(record)
        assert "| calculator | 0 of 3 | 20 of 23 |" in table
        assert "Overall: 3 of 6 generations valid on their first generation" in table


class TestTheHeader:
    def test_it_names_every_template_schema_tool_and_project_hash(self) -> None:
        study = run(PROJECTS, commit="abc1234", validator=_no_linters, now=NOW)["study"]
        assert study["commit"] == "abc1234" and study["date"] == "2026-09-28"
        assert "mern/Dockerfile@2" in study["templates"]
        assert "mern/verify-release.yml@2" in study["templates"]
        assert "render.yaml.json" in study["schemas"]
        assert set(study["projects"]) == {"task-tracker", "calculator"}
        assert any(tool.startswith("c4 secret scan") for tool in study["tools"])
