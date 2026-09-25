"""Reading ground truth somebody else labelled.

The seeded sample can only say the arms run: five weaknesses this repository
wrote are five weaknesses it knew how to write. These tests cover the part that
turns a public corpus into scoreable truth, and the licence discipline that
keeps the corpus out of this repository.
"""

from pathlib import Path

import pytest
from c3.eval import Span, decoys_hit, owasp
from c3.eval.benchmarks import OWASP_LABELS, OWASP_TESTCASES, commit_of

REAL_CHECKOUT = Path.home() / "datasets" / "owasp-benchmark"

needs_checkout = pytest.mark.skipif(
    not (REAL_CHECKOUT / OWASP_LABELS).is_file(),
    reason="needs OWASP Benchmark cloned at ~/datasets/owasp-benchmark",
)


@pytest.fixture
def checkout(tmp_path):
    """A four case benchmark, shaped like the real one."""
    cases = tmp_path / OWASP_TESTCASES
    cases.mkdir(parents=True)
    for name in ("BenchmarkTest00001", "BenchmarkTest00002", "BenchmarkTest00003"):
        (cases / f"{name}.java").write_text(f"public class {name} {{}}\n")
    (tmp_path / OWASP_LABELS).write_text(
        "# test name, category, real vulnerability, cwe, Benchmark version: 1.2\n"
        "BenchmarkTest00001,pathtraver,true,22\n"
        "BenchmarkTest00002,pathtraver,false,22\n"
        "BenchmarkTest00003,sqli,true,89\n"
        "BenchmarkTest09999,sqli,true,89\n"
    )
    return tmp_path


class TestReadingTheLabels:
    def test_the_real_ones_are_truth_and_the_rest_are_decoys(self, checkout) -> None:
        """1,415 real against 1,325 built to look exactly like them is what
        stops recall being bought by reporting every file."""
        benchmark = owasp(checkout)

        assert [span.cwe for span in benchmark.truth] == ["CWE-22", "CWE-89"]
        assert [span.cwe for span in benchmark.decoys] == ["CWE-22"]

    def test_a_label_with_no_file_behind_it_is_skipped(self, checkout) -> None:
        """A checkout whose labels and sources disagree would otherwise put a
        weakness nobody can open into the denominator of every recall."""
        benchmark = owasp(checkout)

        assert all("09999" not in span.path for span in benchmark.truth)
        assert len(benchmark.files) == 3

    def test_truth_is_located_at_the_file_the_benchmark_labelled(self, checkout) -> None:
        """Claiming a line the benchmark never specified would be inventing
        precision on the ground truth's behalf."""
        benchmark = owasp(checkout)

        assert all(span.start_line == 0 for span in benchmark.truth)
        assert benchmark.truth[0].path.endswith("BenchmarkTest00001.java")

    def test_a_missing_checkout_says_how_to_get_one_and_why_it_is_not_here(self, tmp_path) -> None:
        """GPL-2.0. Copying it in would put this repository's licence in
        question, so the error teaches rather than just failing."""
        with pytest.raises(FileNotFoundError) as raised:
            owasp(tmp_path)

        assert "GPL-2.0" in str(raised.value)
        assert "git clone" in str(raised.value)

    def test_the_epoch_note_says_what_was_measured(self, checkout) -> None:
        note = owasp(checkout).epoch_note

        assert "2 real weaknesses" in note and "1 decoys" in note
        assert "GPL-2.0" in note


class TestCountingTheTraps:
    def test_a_finding_on_a_decoy_is_counted_as_one(self) -> None:
        """A separate count from precision, because these are not findings in
        the wrong place: they are findings in a place built to look exactly
        like the right one."""
        decoys = [Span("CWE-22", "a.java"), Span("CWE-89", "b.java")]

        assert decoys_hit([Span("CWE-22", "a.java", 4, 4)], decoys) == 1
        assert decoys_hit([Span("CWE-89", "c.java", 4, 4)], decoys) == 0

    def test_a_child_class_still_walks_into_the_trap(self) -> None:
        assert decoys_hit([Span("CWE-36", "a.java", 1, 1)], [Span("CWE-22", "a.java")]) == 1


class TestAgainstTheRealCheckout:
    @needs_checkout
    def test_it_reads_the_whole_benchmark_and_records_its_commit(self) -> None:
        benchmark = owasp(REAL_CHECKOUT)

        assert len(benchmark.files) == 2740
        assert len(benchmark.truth) == 1415
        assert len(benchmark.decoys) == 1325
        assert len(benchmark.commit) == 40, "the epoch names the exact checkout"

    def test_a_directory_that_is_not_a_clone_reports_no_commit(self, tmp_path) -> None:
        assert commit_of(tmp_path) == ""
