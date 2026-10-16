"""CWE-Bench-Java: real CVEs in real projects, and what that costs to score.

This corpus measures something OWASP Benchmark cannot. OWASP is generated: every
weakness is reachable, every file is small, every case was written to be found.
Here the vulnerable method is somewhere inside a real codebase and nothing was
arranged for a scanner's benefit. An arm that does well on the first and badly
on the second has learned the shape of a benchmark.

Most of these run against a hand made checkout shaped like the real seed data.
The ones marked `corpus` read the clone, and one fetches a project, which is the
only way to check that the recorded line spans actually land on the recorded
source.
"""

from pathlib import Path

import pytest
from c3.eval.cwe_bench import (
    FIX_INFO,
    PROJECT_INFO,
    fetch_project,
    fixes,
    project,
    project_slugs,
    seeds,
    spans_for,
)

CHECKOUT = Path.home() / "datasets" / "cwe-bench-java"
SOURCES = Path.home() / "datasets" / "cwe-bench-sources"

needs_checkout = pytest.mark.skipif(
    not (CHECKOUT / PROJECT_INFO).is_file(),
    reason="needs CWE-Bench-Java cloned at ~/datasets/cwe-bench-java",
)

PROJECTS = (
    "id,project_slug,cve_id,cwe_id,cwe_name,github_username,github_repository_name,"
    "github_tag,github_url,advisory_id,buggy_commit_id,fix_commit_ids\n"
    "1,acme__widget_CVE-2020-1_1.0,CVE-2020-1,CWE-022,Path Traversal,acme,widget,1.0,"
    "https://github.com/acme/widget,GHSA-x,abc123,def456\n"
    "2,acme__gadget_CVE-2021-2_2.0,CVE-2021-2,CWE-078,OS Command Injection,acme,gadget,2.0,"
    "https://github.com/acme/gadget,GHSA-y,bbb222,ccc333\n"
)

FIXES = (
    "project_slug,cve_id,github_username,github_repository_name,commit,file,class,"
    "class_start,class_end,method,method_start,method_end,signature\n"
    "acme__widget_CVE-2020-1_1.0,CVE-2020-1,acme,widget,abc123,src/main/java/Reader.java,"
    "Reader,10,90,read,40,52,read(String)\n"
    "acme__widget_CVE-2020-1_1.0,CVE-2020-1,acme,widget,abc123,src/main/java/Holder.java,"
    "Holder,5,60,,,,\n"
    "acme__widget_CVE-2020-1_1.0,CVE-2020-1,acme,widget,abc123,docs/README.md,,,,,,,\n"
    "somebody__else_CVE-1999-9_9.9,CVE-1999-9,somebody,else,zzz,src/main/java/Other.java,"
    "Other,1,20,run,3,9,run()\n"
)


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / PROJECT_INFO).write_text(PROJECTS)
    (tmp_path / FIX_INFO).write_text(FIXES)
    return tmp_path


class TestReadingTheSeedData:
    def test_the_projects_come_from_the_project_table(self, checkout) -> None:
        assert [row["project_slug"] for row in seeds(checkout)] == [
            "acme__widget_CVE-2020-1_1.0",
            "acme__gadget_CVE-2021-2_2.0",
        ]

    def test_fix_rows_for_projects_this_dataset_does_not_have_are_dropped(self, checkout) -> None:
        """The fix table carries 31 slugs from a larger collection. Keeping
        them would put weaknesses into a denominator no arm was ever shown."""
        grouped = fixes(checkout)

        assert set(grouped) == {"acme__widget_CVE-2020-1_1.0"}

    def test_a_fix_to_something_that_is_not_java_is_not_a_weakness_location(self, checkout) -> None:
        rows = fixes(checkout)["acme__widget_CVE-2020-1_1.0"]

        assert all(row["file"].endswith(".java") for row in rows)

    def test_a_missing_checkout_says_how_to_get_one(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError) as raised:
            seeds(tmp_path)

        assert "git clone" in str(raised.value)
        assert "MIT" in str(raised.value)


class TestTurningFixesIntoSpans:
    def test_a_method_fix_becomes_the_method_span(self, checkout) -> None:
        rows = fixes(checkout)["acme__widget_CVE-2020-1_1.0"]

        spans = spans_for(rows, "CWE-22")

        assert (spans[0].start_line, spans[0].end_line) == (40, 52)
        assert spans[0].cwe == "CWE-22"

    def test_a_fix_to_a_class_variable_falls_back_to_the_class(self, checkout) -> None:
        """Fifteen real weaknesses in the corpus have no method span. Dropping
        them would take them out of the denominator; a class span is wide, and
        a wide truth span is a generous match rather than a wrong one."""
        rows = fixes(checkout)["acme__widget_CVE-2020-1_1.0"]

        spans = spans_for(rows, "CWE-22")

        holder = next(span for span in spans if span.path.endswith("Holder.java"))
        assert (holder.start_line, holder.end_line) == (5, 60)

    def test_the_zero_padded_class_is_the_same_class_the_scanners_report(self) -> None:
        """`CWE-022` parses, looks like a weakness class, and matched nothing.
        Every path traversal in this corpus would have been graded against a
        class no arm reports, and nothing would have looked wrong."""
        from c3.detect.severity import normalise

        assert normalise("CWE-022") == "CWE-22"
        assert normalise("CWE-078") == "CWE-78"
        assert normalise("CWE-094") == "CWE-94"

    def test_code_injection_has_a_severity_rather_than_a_shrug(self) -> None:
        """One of this corpus's four classes, and it was not in the table."""
        from c3.detect.severity import factors_for
        from sdlc_contracts.validation_report import cvss_base_score

        factors, why = factors_for("CWE-094")

        assert cvss_base_score(factors) == 9.8
        assert "no rule for this weakness class" not in why


class TestChoosingProjects:
    def test_one_weakness_class_at_a_time(self, checkout) -> None:
        assert project_slugs(checkout, cwe="CWE-22") == ["acme__widget_CVE-2020-1_1.0"]
        assert project_slugs(checkout, cwe="CWE-78") == ["acme__gadget_CVE-2021-2_2.0"]

    def test_the_padded_spelling_selects_the_same_projects(self, checkout) -> None:
        assert project_slugs(checkout, cwe="CWE-022") == project_slugs(checkout, cwe="CWE-22")

    def test_a_subset_is_the_normal_case(self, checkout) -> None:
        """Each project is a real repository, and fetching all 120 is tens of
        gigabytes for a study that can say something useful from twenty."""
        assert len(project_slugs(checkout, limit=1)) == 1


class TestOneProjectAsABenchmark:
    def test_truth_is_dropped_when_the_file_is_not_in_the_fetched_tree(
        self, checkout, tmp_path
    ) -> None:
        """A weakness a reader cannot open is not evidence, and a repository
        fetched at a different commit will not have every fixed file."""
        sources = tmp_path / "sources"
        (sources / "acme__widget_CVE-2020-1_1.0" / "src" / "main" / "java").mkdir(parents=True)
        (
            sources / "acme__widget_CVE-2020-1_1.0" / "src" / "main" / "java" / "Reader.java"
        ).write_text("class Reader {}\n")

        benchmark = project(checkout, "acme__widget_CVE-2020-1_1.0", sources)

        assert [span.path for span in benchmark.truth] == ["src/main/java/Reader.java"]
        assert benchmark.files == ["src/main/java/Reader.java"]

    def test_this_corpus_has_no_decoys_and_says_so(self, checkout, tmp_path) -> None:
        """Precision here is measured against the rest of a real codebase,
        which is a harder question than a decoy and a less answerable one."""
        sources = tmp_path / "sources"
        (sources / "acme__widget_CVE-2020-1_1.0").mkdir(parents=True)

        benchmark = project(checkout, "acme__widget_CVE-2020-1_1.0", sources)

        assert benchmark.decoys == []
        assert "MIT" in benchmark.licence

    def test_the_epoch_names_the_commit_the_cve_reproduces_on(self, checkout, tmp_path) -> None:
        sources = tmp_path / "sources"
        (sources / "acme__widget_CVE-2020-1_1.0").mkdir(parents=True)

        benchmark = project(checkout, "acme__widget_CVE-2020-1_1.0", sources)

        assert benchmark.commit == "abc123"

    def test_a_project_this_dataset_does_not_have_is_refused(self, checkout, tmp_path) -> None:
        with pytest.raises(KeyError):
            project(checkout, "nobody__nothing_CVE-0000-0_0", tmp_path)


@pytest.mark.corpus
@needs_checkout
class TestAgainstTheRealSeedData:
    def test_it_reads_all_one_hundred_and_twenty_projects(self) -> None:
        rows = seeds(CHECKOUT)

        assert len(rows) == 120
        classes = {row["cwe_id"] for row in rows}
        assert classes == {"CWE-022", "CWE-078", "CWE-079", "CWE-094"}

    def test_seven_projects_have_no_fix_rows_and_are_visibly_unscoreable(self) -> None:
        """Not an error and not silently fine: a project with no ground truth
        contributes no weaknesses to the denominator, and a reader should know
        that 113 of 120 is what a full run measures."""
        grouped = fixes(CHECKOUT)

        assert len(grouped) == 113
        assert sum(len(rows) for rows in grouped.values()) == 984

    @pytest.mark.skipif(
        not (SOURCES / "alibaba__one-java-agent_CVE-2022-25842_0.0.1").is_dir(),
        reason="needs one project fetched",
    )
    def test_a_recorded_span_lands_on_the_recorded_source(self) -> None:
        """The only check that the line numbers mean anything: they were
        recorded against a commit, and this fetches that commit."""
        slug = "alibaba__one-java-agent_CVE-2022-25842_0.0.1"

        benchmark = project(CHECKOUT, slug, SOURCES)

        assert benchmark.truth
        for span in benchmark.truth:
            lines = (benchmark.root / span.path).read_text(errors="replace").splitlines()
            assert 1 <= span.start_line <= len(lines)
            assert span.end_line <= len(lines)

    def test_fetching_a_project_twice_does_not_fetch_it_twice(self, tmp_path) -> None:
        slug = "alibaba__one-java-agent_CVE-2022-25842_0.0.1"
        if not (SOURCES / slug / ".git").is_dir():
            pytest.skip("needs that project fetched")

        assert fetch_project(CHECKOUT, slug, SOURCES) == SOURCES / slug
