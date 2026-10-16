"""Does this test notice when the code under it is wrong?

The question the honesty guard is built on, and the one a weakened assertion
cannot answer. The cases below are the two halves of the contribution stated as
tests: a real test that asserts a value catches a deliberate fault, and the
`toBeDefined()` version of the same test, which passes just as green, does not.

The mutant generator is checked without a runner, because it is text. The check
itself runs the real one, because whether a test goes red is not a thing that
can be reasoned about from a source file.
"""

import shutil

import pytest
from c3.harness import Sandbox, resolve, stage_copy
from c3.harness import node_lane as lane
from c3.heal import candidates, inject, kills_a_mutant

from . import jdk
from .test_targets import Ref

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")

SOURCE = """\
export function discount(pence: number, percent: number): number {
  if (percent < 0 || percent > 100) {
    throw new RangeError("a percentage is between 0 and 100");
  }
  return Math.round(pence * (100 - percent)) / 100;
}
"""


class TestChoosingAFault:
    def test_the_safest_faults_come_first(self) -> None:
        """A mutant that does not compile costs a run to discover, so the ones
        that cannot fail to compile lead."""
        found = candidates(SOURCE, path="a.ts")

        assert found[0].operator == "numeric-literal"
        assert [m.operator for m in found].index("arithmetic") > 0

    def test_a_comment_holds_no_behaviour_to_break(self) -> None:
        source = "// the limit is 100\nconst limit = 100;\n"

        found = candidates(source, path="a.ts")

        assert {m.line for m in found} == {2}

    def test_a_region_narrows_it_to_what_the_test_watches(self) -> None:
        """For a repaired test that is the code that changed between the two
        versions, because that is what made it fail."""
        found = candidates(SOURCE, path="a.ts", lines=range(5, 6))

        assert found and {m.line for m in found} == {5}

    def test_an_arrow_is_not_a_comparison(self) -> None:
        """`=>` and `->` contain the characters a boundary mutant looks for,
        and rewriting one produces a file that does not parse."""
        found = candidates("const f = (a: number) => a;\n", path="a.ts")

        assert not any(m.operator == "boundary" for m in found)

    def test_the_injected_file_differs_by_exactly_one_line(self) -> None:
        mutant = candidates(SOURCE, path="a.ts")[0]

        mutated = inject(SOURCE, mutant)

        before = SOURCE.splitlines()
        after = mutated.splitlines()
        assert len(before) == len(after)
        assert sum(1 for a, b in zip(before, after, strict=True) if a != b) == 1
        assert after[mutant.line - 1] == mutant.mutated_line


@pytest.mark.sandbox
@needs_npm
class TestAskingTheTest:
    """The contribution, run against a real runner.

    Two tests over the same function, both green, and only one of them is
    watching anything. That difference is invisible to a pass rate, invisible
    to the source catalogue, and is the whole reason the guard exists.
    """

    @staticmethod
    def _prepared(tmp_path):
        repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), tmp_path / "ws")
        lane.declare_measurement_tools(repo)
        sandbox = Sandbox(repo.root)
        assert lane.install(repo, sandbox).passed
        return repo, sandbox

    def test_a_test_that_asserts_a_value_notices(self, tmp_path) -> None:
        repo, sandbox = self._prepared(tmp_path)
        repo.write(
            "apps/web/src/__tests__/watching.test.ts",
            "\n".join(
                [
                    'import { expect, it } from "vitest";',
                    'import { total } from "../total";',
                    "",
                    'it("adds the line up", () => {',
                    "  expect(total([{ price: 250, quantity: 2 }])).toBe(500);",
                    "});",
                ]
            ),
        )

        check = kills_a_mutant(
            repo,
            sandbox,
            suite_path="apps/web/src/__tests__/watching.test.ts",
            test_name="adds the line up",
            source_path="apps/web/src/total.ts",
        )

        assert check.killed, check.detail
        assert check.mutant is not None
        assert "noticed" in check.detail
        # And the file is exactly as it was, deliberate fault removed.
        assert "export function total" in (repo.read("apps/web/src/total.ts") or "")

    def test_a_test_that_asserts_nothing_useful_does_not(self, tmp_path) -> None:
        """`toBeDefined()` where the criterion asked for a value. It passes,
        it looks like a test, and every fault in the code walks past it."""
        repo, sandbox = self._prepared(tmp_path)
        repo.write(
            "apps/web/src/__tests__/watching.test.ts",
            "\n".join(
                [
                    'import { expect, it } from "vitest";',
                    'import { total } from "../total";',
                    "",
                    'it("adds the line up", () => {',
                    "  expect(total([{ price: 250, quantity: 2 }])).toBeDefined();",
                    "});",
                ]
            ),
        )

        check = kills_a_mutant(
            repo,
            sandbox,
            suite_path="apps/web/src/__tests__/watching.test.ts",
            test_name="adds the line up",
            source_path="apps/web/src/total.ts",
        )

        assert not check.killed
        assert check.survived, check.detail
        assert "watching nothing" in check.detail

    def test_a_test_that_was_already_red_is_not_asked(self, tmp_path) -> None:
        """It cannot demonstrate that it notices a fault, and saying so is
        different from saying it noticed nothing."""
        repo, sandbox = self._prepared(tmp_path)
        repo.write(
            "apps/web/src/__tests__/watching.test.ts",
            "\n".join(
                [
                    'import { expect, it } from "vitest";',
                    'import { total } from "../total";',
                    "",
                    'it("expects the wrong answer", () => {',
                    "  expect(total([{ price: 250, quantity: 2 }])).toBe(9999);",
                    "});",
                ]
            ),
        )

        check = kills_a_mutant(
            repo,
            sandbox,
            suite_path="apps/web/src/__tests__/watching.test.ts",
            test_name="expects the wrong answer",
            source_path="apps/web/src/total.ts",
        )

        assert not check.killed
        assert "before anything was broken" in check.detail
        assert check.tried == 0, "nothing should have been injected"

    def test_the_file_comes_back_even_when_the_run_throws(self, tmp_path) -> None:
        """A guard that left a deliberate fault in the repository would be
        worse than no guard."""
        repo, sandbox = self._prepared(tmp_path)
        before = repo.read("apps/web/src/total.ts")
        repo.write(
            "apps/web/src/__tests__/watching.test.ts",
            "\n".join(
                [
                    'import { expect, it } from "vitest";',
                    'import { total } from "../total";',
                    "",
                    'it("adds the line up", () => {',
                    "  expect(total([{ price: 250, quantity: 2 }])).toBe(500);",
                    "});",
                ]
            ),
        )

        class Exploding:
            def __init__(self, real):
                self._real = real
                self.calls = 0

            def run(self, step):
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("the runner fell over mid check")
                return self._real.run(step)

            def read(self, path):
                return self._real.read(path)

            @property
            def root(self):
                return self._real.root

        with pytest.raises(RuntimeError, match="fell over"):
            kills_a_mutant(
                repo,
                Exploding(sandbox),  # type: ignore[arg-type]
                suite_path="apps/web/src/__tests__/watching.test.ts",
                test_name="adds the line up",
                source_path="apps/web/src/total.ts",
            )

        assert repo.read("apps/web/src/total.ts") == before


class TestFindingTheCodeATestExercises:
    def test_a_typescript_test_names_it_by_importing_it(self, tmp_path) -> None:
        from c3.heal.kill_check import sources_under

        repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), tmp_path / "ws")

        assert sources_under(repo, "apps/web/src/__tests__/total.test.ts") == [
            "apps/web/src/total.ts"
        ]

    def test_a_java_test_names_it_by_maven_convention(self, tmp_path) -> None:
        """`TotalsTest` tests `Totals`, which is the only thing available: a
        Java test imports nothing that says what it is testing."""
        from c3.heal.kill_check import sources_under

        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")

        assert sources_under(repo, "src/test/java/com/example/records/TotalsTest.java") == [
            "src/main/java/com/example/records/Totals.java"
        ]

    def test_a_test_that_loads_its_app_afresh_reaches_the_app_and_what_it_mounts(
        self, tmp_path
    ) -> None:
        """Every generated acceptance test loads its app with a dynamic import
        before each case, so a guard that read static imports only found no
        code under any of them, and refused every repair as a caught cheat."""
        from c3.generate.criteria import fresh_app_block
        from c3.harness.targets import TargetRepo
        from c3.heal.kill_check import sources_under

        files = {
            "apps/api/src/__tests__/things.criteria.test.ts": (
                'import { beforeEach, expect, it, vi } from "vitest";\n'
                'import { seed } from "./seed";\n'
                + fresh_app_block(["app"], "../app.ts")
                + 'it("lists the things", () => { expect(app).toBeTruthy(); });\n'
            ),
            "apps/api/src/__tests__/seed.ts": "export const seed = 1;\n",
            "apps/api/src/app.ts": (
                'import { thingsRouter } from "./routes/things.ts";\n'
                'export { storage } from "./storage.ts";\n'
                "export const app = thingsRouter();\n"
            ),
            "apps/api/src/routes/things.ts": (
                'import type { Thing } from "../models/Thing.ts";\n'
                'import { memory } from "../repositories/memory.ts";\n'
                "export function thingsRouter(): Thing[] { return memory; }\n"
            ),
            "apps/api/src/models/Thing.ts": "export interface Thing { id: string }\n",
            "apps/api/src/repositories/memory.ts": "export const memory = [];\n",
            "apps/api/src/storage.ts": 'export const storage = "memory";\n',
        }
        for path, content in files.items():
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text(content)
        repo = TargetRepo(root=tmp_path, kind="generated", stack="node")

        assert sources_under(repo, "apps/api/src/__tests__/things.criteria.test.ts") == [
            "apps/api/src/app.ts",
            "apps/api/src/routes/things.ts",
            "apps/api/src/storage.ts",
            "apps/api/src/models/Thing.ts",
            "apps/api/src/repositories/memory.ts",
        ], "nearest first, the app's own imports followed, and a test helper is not the code"

    def test_a_class_that_breaks_the_convention_yields_nothing(self, tmp_path) -> None:
        """Better than breaking a file at random: the guard then says the code
        this test watches could not be found."""
        from c3.heal.kill_check import sources_under

        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")

        assert sources_under(repo, "src/test/java/com/example/records/Helper.java") == []


@pytest.mark.sandbox
class TestTheJavaLaneAnswersTheSameQuestion:
    """The guard is lane agnostic; only the runner is not.

    Slower than the node case (a JVM per run), so one test rather than four,
    and it is the one that matters: a real Java test, a real injected fault,
    and the check saying whether it noticed.
    """

    needs_jdk = jdk.needs_jdk

    @needs_jdk
    def test_a_java_test_that_asserts_a_value_notices(self, tmp_path) -> None:
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")
        sandbox = Sandbox(repo.root)

        check = kills_a_mutant(
            repo,
            sandbox,
            suite_path="src/test/java/com/example/records/TotalsTest.java",
            test_name="TotalsTest.adds_price_times_quantity_across_the_lines",
            source_path="src/main/java/com/example/records/Totals.java",
        )

        assert check.killed, check.detail
        assert check.mutant is not None
        # And the file is exactly as it was.
        assert "public static long total" in (
            repo.read("src/main/java/com/example/records/Totals.java") or ""
        )


class TestWhereTheGuardBreaksTheCode:
    """The code that changed, in what the test reaches, before anything else."""

    REACHED = ("apps/api/src/app.ts", "apps/api/src/routes/things.ts", "apps/api/src/models/T.ts")

    def test_the_changed_code_the_test_reaches_comes_first_at_its_changed_lines(self) -> None:
        from c3.heal.guard import aims

        changed = {
            "apps/api/src/routes/things.ts": frozenset({4, 5}),
            "apps/web/src/pages/Unreached.tsx": frozenset({1}),
        }

        assert aims(list(self.REACHED), changed) == [
            ("apps/api/src/routes/things.ts", frozenset({4, 5}))
        ], "a fault in a file the test never loads proves nothing either way"

    def test_with_nothing_it_reaches_changed_it_breaks_what_it_reaches(self) -> None:
        from c3.heal.guard import aims

        assert aims(list(self.REACHED), {"apps/web/src/other.ts": frozenset({1})}) == [
            (path, None) for path in self.REACHED
        ]

    def test_it_asks_in_a_few_files_at_most(self) -> None:
        from c3.heal.guard import FILES_ASKED, aims

        reached = [f"apps/api/src/m{index}.ts" for index in range(10)]

        assert len(aims(reached, {})) == FILES_ASKED
