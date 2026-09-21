"""The catalogue: what is wrong with the tests, whoever wrote them.

A pass rate says the suite is green. These say whether green means anything.
Most are read out of the source with the same detectors the model fill is held
to, so what this component refuses to write it also refuses to stay quiet
about; one is observed, because a test whose result depends on what ran before
it cannot be found by reading.
"""

import shutil

import pytest
from c3 import quality
from c3.harness import Sandbox, TargetRepo, resolve, stage_copy

from .test_targets import Ref

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")


def _repo(tmp_path, files: dict[str, str]) -> TargetRepo:
    root = tmp_path / "ws"
    (root / "apps" / "web" / "src" / "__tests__").mkdir(parents=True)
    (root / "package.json").write_text('{"workspaces": ["apps/*"]}')
    (root / "apps" / "web" / "package.json").write_text("{}")
    for name, content in files.items():
        (root / "apps" / "web" / "src" / "__tests__" / name).write_text(content)
    return TargetRepo(root=root, kind="benchmark", stack="node", apps=("apps/web",))


def _suite(*bodies: str) -> str:
    lines = ['import { describe, expect, it } from "vitest";', "", 'describe("a suite", () => {']
    for index, body in enumerate(bodies):
        lines.append(f'  it("case {index}", () => {{')
        lines.append(f"    {body}")
        lines.append("  });")
    lines.append("});")
    return "\n".join(lines) + "\n"


class TestWhatCanBeRead:
    def test_a_test_that_asserts_nothing(self, tmp_path) -> None:
        repo = _repo(tmp_path, {"a.test.ts": _suite("const answer = 1 + 1;")})

        found = quality.read_findings(repo)

        assert [finding.rule for finding in found] == ["no-assertion"]
        assert found[0].path == "apps/web/src/__tests__/a.test.ts"
        assert found[0].test == "case 0"
        assert not found[0].observed

    def test_an_assertion_that_holds_for_every_program(self, tmp_path) -> None:
        repo = _repo(tmp_path, {"a.test.ts": _suite("expect(true).toBe(true);")})

        assert [finding.rule for finding in quality.read_findings(repo)] == ["vacuous-assertion"]

    def test_a_focused_file_disables_everything_else_in_it(self, tmp_path) -> None:
        """A green suite that ran one test. The finding is against the file
        rather than a test, because that is what is wrong."""
        source = _suite("expect(1 + 1).toBe(2);").replace('  it("case 0"', '  it.only("case 0"')
        repo = _repo(tmp_path, {"a.test.ts": source})

        found = quality.read_findings(repo)

        assert "focused" in {finding.rule for finding in found}
        assert next(f for f in found if f.rule == "focused").test == ""

    @pytest.mark.parametrize(
        ("body", "rule"),
        [
            ("expect(Math.random()).toBeLessThan(1);", "unseeded-randomness"),
            ("await new Promise(r => setTimeout(r, 5)); expect(1).toBe(1);", "sleep"),
            ("await fetch('http://example.com'); expect(2 + 2).toBe(4);", "network"),
            ("expect(Date.now()).toBeGreaterThan(0);", "wall-clock"),
        ],
    )
    def test_the_habits_that_make_a_suite_unrepeatable(self, tmp_path, body, rule) -> None:
        repo = _repo(tmp_path, {"a.test.ts": _suite(body)})

        assert rule in {finding.rule for finding in quality.read_findings(repo)}

    def test_a_test_that_is_fine_produces_nothing(self, tmp_path) -> None:
        repo = _repo(tmp_path, {"a.test.ts": _suite("expect(2 + 2).toBe(4);")})

        assert quality.read_findings(repo) == []

    def test_it_reads_tests_this_component_did_not_write(self, tmp_path) -> None:
        """A finding against the code generator's own test is as useful as one
        against the model's, and excluding it would make the list flattering."""
        repo = _repo(
            tmp_path,
            {
                "generated.contract.test.ts": _suite("const x = 1;"),
                "ours.oracle.test.ts": _suite("expect(1).toBe(2);"),
            },
        )

        found = quality.read_findings(repo)

        assert [finding.path for finding in found] == [
            "apps/web/src/__tests__/generated.contract.test.ts"
        ]

    def test_a_declared_and_unwritten_test_is_counted_and_not_a_finding(self, tmp_path) -> None:
        """It is an honest state: the report counts it as a skip. Counted so a
        summary can say it, because ten tests of which six are declarations
        reads very differently from ten that are written."""
        repo = _repo(
            tmp_path,
            {"a.test.ts": 'import { it } from "vitest";\nit.todo("not written yet");\n'},
        )

        assert quality.read_findings(repo) == []
        assert quality.unwritten(repo) == 1


@pytest.mark.sandbox
@needs_npm
class TestWhatHasToBeObserved:
    def test_a_test_that_only_passes_when_it_runs_first(self, tmp_path) -> None:
        """The finding no amount of reading could produce.

        Four tests share a module level flag. Whichever runs first passes and
        the rest fail, which is the shape of every order dependent suite. Four
        rather than two because the shuffle is seeded and deterministic: with
        two, this particular seed happens to leave the order alone, and a test
        that depended on that would be exactly the coin flip it is meant to
        detect.
        """
        repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), tmp_path / "ws")
        repo.write(
            "apps/web/src/__tests__/order.test.ts",
            "\n".join(
                [
                    'import { expect, it } from "vitest";',
                    "",
                    "let claimed = false;",
                    "",
                    *[
                        line
                        for letter in ("a", "b", "c", "d")
                        for line in (
                            f'it("{letter} claims the flag", () => {{',
                            "  expect(claimed).toBe(false);",
                            "  claimed = true;",
                            "});",
                            "",
                        )
                    ],
                ]
            ),
        )
        from c3.harness import node_lane as lane

        lane.declare_measurement_tools(repo)
        sandbox = Sandbox(repo.root)
        assert lane.install(repo, sandbox).passed
        first = lane.run_tests(repo, sandbox)

        found, check = quality.order_findings(repo, sandbox, first.suites)

        assert check.ran
        assert {finding.rule for finding in found} == {"order-dependent"}
        # One test passed in the written order and a different one passed
        # shuffled, so both moved.
        assert len(found) >= 2
        assert all(finding.observed for finding in found)
        assert "shuffled" in found[0].detail
        assert all(finding.path.endswith("order.test.ts") for finding in found)
        # The stable suite beside it is not accused of anything.
        assert not any("total.test.ts" in finding.path for finding in found)

    def test_a_suite_that_never_ran_is_not_a_suite_without_order_dependence(self, tmp_path) -> None:
        """The two look identical in a list of findings, so the report says
        which one it is."""
        repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), tmp_path / "ws")

        found, check = quality.order_findings(repo, Sandbox(repo.root), [])

        assert found == []
        assert not check.ran
        assert "no tests" in check.reason
