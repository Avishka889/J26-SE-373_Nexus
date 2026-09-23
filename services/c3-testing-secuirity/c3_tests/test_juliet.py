"""Reading Juliet, and the split that stops the model cheating.

The dataset's own documentation warns that its paired good and bad cases leak.
This file is where that warning is turned into a checked property: no family
straddles a split, every class the study scores has test rows, and the naive
split that would leak is available and labelled as such so the leakage can be
measured rather than assumed.

Most tests run against a small hand written fixture in `golden/juliet`, shaped
exactly like the corpus. The one marked `corpus` runs against the real 46,793
files and skips when they are not unpacked, which is where the parser's claims
about braces and coverage are actually checked.
"""

from pathlib import Path

import pytest
from c3.ml.export import export
from c3.ml.juliet import (
    MIN_FAMILIES,
    Example,
    assign_splits,
    cwe_of,
    evaluable,
    examples_in,
    family_of,
    flow_variant_of,
    methods_in,
    read_corpus,
    role_of,
)

FIXTURE = Path(__file__).parent / "golden" / "juliet"
CORPUS = Path.home() / "datasets" / "juliet-java-1.3"

needs_corpus = pytest.mark.skipif(
    not (CORPUS / "Java" / "src" / "testcases").is_dir(),
    reason="needs the Juliet archive unpacked at ~/datasets/juliet-java-1.3",
)


def _fixture() -> list[Example]:
    found: list[Example] = []
    for path in sorted(FIXTURE.glob("*.java")):
        found.extend(examples_in(path.name, path.read_text()))
    return found


class TestReadingOneTestCase:
    def test_the_bad_method_and_the_good_ones_are_labelled_apart(self) -> None:
        name = "CWE89_SQL_Injection__console_readLine_executeUpdate_06.java"

        found = {e.method: e.label for e in examples_in(name, (FIXTURE / name).read_text())}

        assert found == {"bad": 1, "goodG2B1": 0, "goodB2G1": 0}

    def test_the_dispatcher_is_not_an_example(self) -> None:
        """`good()` only calls the others. Labelling it safe would teach the
        model that a method calling two methods is safe, which is true of
        nothing."""
        name = "CWE89_SQL_Injection__console_readLine_executeUpdate_06.java"

        found = [e.method for e in examples_in(name, (FIXTURE / name).read_text())]

        assert "good" not in found

    def test_a_brace_inside_a_string_does_not_end_a_method(self) -> None:
        """It would hand the model a truncated example, which is worse than no
        example: it is a wrong one."""
        name = "CWE89_SQL_Injection__console_readLine_executeUpdate_06.java"
        source = (FIXTURE / name).read_text()

        [(_, code)] = [(n, c) for n, c in methods_in(source) if n == "goodB2G1"]

        assert code.count("{") == code.count("}")
        assert "prepareStatement" in code, "the method did not end at the brace in the literal"

    def test_the_class_comes_from_the_name_juliet_filed_it_under(self) -> None:
        assert cwe_of("CWE89_SQL_Injection__console_readLine_executeUpdate_06.java") == "CWE-89"
        assert cwe_of("Main.java") == ""


class TestTheVariantThatLabelsByFilename:
    """Variant 81 splits one test case over four files and puts the flow in an
    abstract method, so the label is on the filename. Six percent of the
    corpus, and dropping it would drop the whole abstract method flow."""

    def test_the_bad_implementation_is_vulnerable(self) -> None:
        name = "CWE470_Unsafe_Reflection__getCookies_Servlet_81_bad.java"

        [example] = examples_in(name, (FIXTURE / name).read_text())

        assert (example.method, example.label) == ("action", 1)

    def test_the_good_implementation_is_not(self) -> None:
        name = "CWE470_Unsafe_Reflection__getCookies_Servlet_81_goodG2B.java"

        [example] = examples_in(name, (FIXTURE / name).read_text())

        assert example.label == 0

    def test_the_abstract_parent_is_not_an_example_at_all(self) -> None:
        """It declares the method and implements nothing. There is no flow in
        it to label."""
        name = "CWE470_Unsafe_Reflection__getCookies_Servlet_81_base.java"

        assert examples_in(name, (FIXTURE / name).read_text()) == []
        assert role_of(name) == "base"


class TestTheSplitKey:
    def test_every_flow_variant_of_one_source_and_sink_shares_a_family(self) -> None:
        """The leakage the dataset warns about. Seventy control flow wrappers
        around the same two lines are seventy near duplicates, and a split that
        separated them would be scoring memorisation."""
        assert family_of(
            "CWE89_SQL_Injection__console_readLine_executeUpdate_06.java"
        ) == family_of("CWE89_SQL_Injection__console_readLine_executeUpdate_11.java")

    def test_the_multi_file_variant_joins_its_own_family(self) -> None:
        assert family_of("CWE470_Unsafe_Reflection__getCookies_Servlet_81_bad.java") == family_of(
            "CWE470_Unsafe_Reflection__getCookies_Servlet_01.java"
        )

    def test_two_different_source_and_sink_pairs_are_different_families(self) -> None:
        assert family_of("CWE89_SQL_Injection__database_executeBatch_68a.java") != family_of(
            "CWE89_SQL_Injection__console_readLine_executeUpdate_06.java"
        )

    def test_the_flow_variant_is_kept_for_the_reader(self) -> None:
        assert (
            flow_variant_of("CWE89_SQL_Injection__console_readLine_executeUpdate_06.java") == "06"
        )
        assert flow_variant_of("CWE89_SQL_Injection__database_executeBatch_68a.java") == "68a"
        assert flow_variant_of("CWE470_Unsafe_Reflection__getCookies_Servlet_81_bad.java") == (
            "81_bad"
        )


class TestAssigningSplits:
    def _many(self, families: int, cwe: str = "CWE-89") -> list[Example]:
        return [
            Example(
                cwe=cwe,
                vulnerable=index % 2 == 0,
                method="bad",
                code="x",
                family=f"{cwe}__variant{index}",
                path=f"{cwe}__variant{index}_01.java",
                flow_variant="01",
            )
            for index in range(families)
        ]

    def test_no_family_lands_on_two_sides(self) -> None:
        """The property the whole split exists for, checked rather than
        trusted."""
        examples = self._many(40)

        assigned = assign_splits(examples)

        for example in examples:
            assert isinstance(assigned[example.family], str)
        assert len({assigned[e.family] for e in examples}) == 3

    def test_a_class_is_split_within_itself_so_it_has_test_rows(self) -> None:
        """A plain hash over every family leaves most of Juliet's classes with
        no test rows at all, which is fatal for a per class table."""
        examples = self._many(20, "CWE-89") + self._many(20, "CWE-78")

        assigned = assign_splits(examples)
        per_cwe = {}
        for example in examples:
            per_cwe.setdefault(example.cwe, set()).add(assigned[example.family])

        assert per_cwe["CWE-89"] == {"train", "validation", "test"}
        assert per_cwe["CWE-78"] == {"train", "validation", "test"}

    def test_a_class_too_small_to_score_trains_and_is_not_scored(self) -> None:
        """A precision computed over four test examples is a number that will
        be read as though it meant something."""
        examples = self._many(MIN_FAMILIES - 1, "CWE-999")

        assigned = assign_splits(examples)

        assert {assigned[e.family] for e in examples} == {"train"}
        assert "CWE-999" not in evaluable(examples)

    def test_the_assignment_is_the_same_on_any_machine(self) -> None:
        """Deterministic and order independent, so no assignment file has to be
        kept in step with the data."""
        examples = self._many(30)

        first = assign_splits(examples)
        second = assign_splits(list(reversed(examples)))

        assert first == second

    def test_a_different_seed_is_a_different_epoch(self) -> None:
        examples = self._many(30)

        assert assign_splits(examples) != assign_splits(examples, seed="other")

    def test_the_naive_split_is_available_and_named(self) -> None:
        """Kept so the leakage can be measured: train both ways, and the gap
        between the two scores is the number Juliet's documentation warns
        about without quantifying."""
        examples = [
            Example(
                cwe="CWE-89",
                vulnerable=index % 2 == 0,
                method="bad",
                code="x",
                family="CWE-89__one",
                path=f"CWE-89__one_{index:02d}.java",
                flow_variant=f"{index:02d}",
            )
            for index in range(30)
        ]

        by_family = {assign_splits(examples, by="family")[e.family] for e in examples}
        by_file = {assign_splits(examples, by="file")[e.path] for e in examples}

        assert by_family == {"train"}, "one family cannot be divided, and is not"
        assert by_file == {"train", "validation", "test"}, "the naive rule divides it, and leaks"


class TestTheExportedManifest:
    def test_it_records_what_a_reader_needs_to_repeat_the_run(self, tmp_path) -> None:
        manifest = export(FIXTURE, tmp_path / "out")

        assert manifest["splitRule"]["by"] == "family"
        assert manifest["splitRule"]["seed"]
        assert manifest["licence"].startswith("CC0")
        assert manifest["counts"]
        assert manifest["classes"]["CWE-89"]

    def test_the_rows_carry_their_family_so_a_split_can_be_audited(self, tmp_path) -> None:
        import json

        export(FIXTURE, tmp_path / "out")
        rows = [
            json.loads(line)
            for name in ("train", "validation", "test")
            for line in (tmp_path / "out" / f"{name}.jsonl").read_text().splitlines()
        ]

        assert rows
        assert all(row["family"] and row["cwe"] and row["split"] for row in rows)
        assert {row["label"] for row in rows} <= {0, 1}


@pytest.mark.corpus
@needs_corpus
class TestAgainstTheRealCorpus:
    def test_every_extracted_method_is_a_whole_method(self) -> None:
        """A truncated example is worse than a missing one, so this is checked
        across all 46,793 files rather than on a fixture."""
        examples = read_corpus(CORPUS)

        assert len(examples) > 100_000
        broken = [e for e in examples if e.code.count("{") != e.code.count("}")]
        assert broken == []

    def test_the_classes_the_study_scores_all_have_test_rows(self) -> None:
        examples = read_corpus(CORPUS)
        assigned = assign_splits(examples)
        scorable = evaluable(examples)

        with_test = {e.cwe for e in examples if assigned[e.family] == "test"}
        print(f"\n{len(examples)} examples, {len(scorable)} classes with a per class score")
        assert scorable <= with_test
        assert len(scorable) >= 30


class TestTheLabelSpaceBothSidesUse:
    """The training script runs on Colab and imports nothing from here, so
    nothing but a test stops the two definitions of class index seven from
    drifting apart. A model whose index seven means something different from
    the code's index seven produces confident nonsense, and nothing about it
    looks wrong."""

    def test_the_colab_script_and_the_service_agree(self, tmp_path) -> None:
        from c3.ml.labels import LabelSpace
        from c3.ml.train import label_space

        manifest = export(FIXTURE, tmp_path / "out")

        assert tuple(label_space(manifest)) == LabelSpace.over(manifest["evaluableClasses"]).classes

    def test_an_unknown_class_falls_to_the_catch_all_rather_than_crashing(self) -> None:
        from c3.ml.labels import OTHER, LabelSpace

        space = LabelSpace.over(["CWE-89", "CWE-78"])

        assert space.cwe_at(space.index_of("CWE-99999")) == OTHER
        assert space.cwe_at(space.index_of("CWE-89")) == "CWE-89"

    def test_it_survives_the_round_trip_the_weights_travel_with(self, tmp_path) -> None:
        from c3.ml.labels import LabelSpace

        space = LabelSpace.over(["CWE-89", "CWE-190", "CWE-78"])
        space.write(tmp_path / "labels.json")

        assert LabelSpace.read(tmp_path / "labels.json") == space
        assert space.classes[0] == "CWE-78", "sorted by number, so a human can read the file"
