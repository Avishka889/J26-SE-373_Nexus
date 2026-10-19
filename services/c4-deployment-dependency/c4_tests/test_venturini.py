"""Venturini et al.'s npm breaks, read as cases the study can hold, and nothing else.

The records below are copied from the replication package, doi:10.5281/zenodo.5558085,
by Venturini, Cogo, Wiese, Polato and Gerosa, licensed CC BY 4.0. Three kinds:
a direct, non-major break the study can read, a transitive one it cannot, and
one with two providers it cannot. The registry is a mapping written here.
"""

import json
from pathlib import Path

from c4.eval.loaders.venturini import CITATION, load, previous_release, usable
from c4.eval.rubric import level

DIRECT = {
    "client_name": "assetgraph-builder",
    "provider_name": "assetgraph",
    "category": "wrong-code",
    "documentation": "--",
    "fixed_by": "provider",
    "client_version_introduced": "assetgraph-builder@4.12.0",
    "provider_version_introduced": "assetgraph@2.15.0",
    "impacted_by": "explicit",
    "semver_introduce": "minor",
}
TRANSITIVE = {
    **DIRECT,
    "provider_name": "jsdom",
    "provider_version_introduced": "jsdom@0.0.1",
    "impacted_by": "implicit",
    "semver_introduce": "patch",
}
TWO_PROVIDERS = {**DIRECT, "provider_name": "assetgraph;jsdom"}
SCOPED = {
    "client_name": "env-cmd",
    "provider_name": "@typescript-eslint/parser",
    "category": "incompatible-providers-versions",
    "documentation": "issue",
    "fixed_by": "client",
    "client_version_introduced": "env-cmd@9.0.1",
    "provider_version_introduced": "@typescript-eslint/parser@1.6.0",
    "impacted_by": "explicit",
    "semver_introduce": "minor",
}
RELEASES = {
    "assetgraph": ["2.14.0", "2.14.3", "2.15.0-beta.1", "2.15.0", "3.0.0"],
    "@typescript-eslint/parser": ["1.4.2", "1.5.0", "1.6.0", "2.0.0"],
}


def _dataset(tmp_path: Path, **clients: list[dict]) -> Path:
    path = tmp_path / "breaking-changes-cases.json"
    path.write_text(json.dumps(clients))
    return path


class TestTheReleaseBefore:
    def test_it_is_the_newest_stable_release_below_in_the_same_major(self) -> None:
        assert previous_release("2.15.0", RELEASES["assetgraph"]) == "2.14.3"

    def test_a_first_release_of_its_line_has_none(self) -> None:
        assert previous_release("3.0.0", ["2.9.0", "3.0.0"]) is None


class TestWhatIsRead:
    def test_only_a_direct_single_provider_non_major_break_is_read(self) -> None:
        assert usable(DIRECT) is None
        assert "transitive" in (usable(TRANSITIVE) or "")
        assert "more than one provider" in (usable(TWO_PROVIDERS) or "")
        assert "major" in (usable({**DIRECT, "semver_introduce": "major"}) or "")

    def test_a_usable_record_becomes_a_recorded_break(self, tmp_path) -> None:
        dataset = _dataset(tmp_path, **{"assetgraph-builder": [DIRECT, TRANSITIVE, TWO_PROVIDERS]})

        cases, skipped = load(dataset, None, RELEASES)

        [case] = cases
        assert case.case_id == "venturini-assetgraph-builder-assetgraph-2.15.0"
        assert (case.update.package, case.update.from_version, case.update.to_version) == (
            "assetgraph",
            "2.14.3",
            "2.15.0",
        )
        assert case.client.kind == "npm-package"
        assert case.client.package_spec == "assetgraph-builder@4.12.0"
        assert case.observed.method == "venturini-recorded"
        assert level(case.observed) == "high"
        assert case.source_change == "minor"
        assert CITATION in case.provenance
        assert [item.reason.split(":")[0] for item in skipped] == [
            "transitive",
            "more than one provider",
        ]

    def test_a_scoped_provider_keeps_its_scope(self, tmp_path) -> None:
        cases, _ = load(_dataset(tmp_path, **{"env-cmd": [SCOPED]}), None, RELEASES)
        [case] = cases
        assert case.update.package == "@typescript-eslint/parser"
        assert case.update.from_version == "1.5.0"
        assert case.case_id == "venturini-env-cmd-typescript-eslint-parser-1.6.0"

    def test_a_provider_the_registry_did_not_answer_for_is_skipped_saying_so(
        self, tmp_path
    ) -> None:
        cases, skipped = load(_dataset(tmp_path, **{"assetgraph-builder": [DIRECT]}), None, {})
        assert cases == [] and skipped[0].reason == "the registry was not read"

    def test_the_dataset_file_is_pinned_by_its_hash(self, tmp_path) -> None:
        dataset = _dataset(tmp_path, **{"assetgraph-builder": [DIRECT]})
        [case], _ = load(dataset, None, RELEASES)
        [(name, sha)] = case.frozen_inputs.items()
        assert name.endswith("breaking-changes-cases.json") and len(sha) == 64
