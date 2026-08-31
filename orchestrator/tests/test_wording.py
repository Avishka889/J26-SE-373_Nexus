"""What the platform writes for people says it in their words.

Activity and each phase's conversation showed "Generated uml-diagrams",
"Component c3 on ...", "Connected github", "digest: None" and "The stage failed
with ReadError and no message": a stage id, a component code, a provider key, a
Python value and a library's class name.
"""

import re
from pathlib import Path
from typing import get_args

import httpx
import pytest
from orchestrator.errors import readable_failure
from orchestrator.wording import STAGE_LABELS, VERDICT_WORDS, readable_notes, stage_label
from sdlc_contracts.ids import CodeStageId, DeployStageId, DesignStageId, TestStageId

FRONTEND = Path(__file__).resolve().parents[2] / "ai-sdlc-platform-frontend" / "src" / "features"
PHASE_STAGES = {
    "requirements": DesignStageId,
    "code-generation": CodeStageId,
    "testing": TestStageId,
    "deployment": DeployStageId,
}


def _page_labels(feature: str) -> dict[str, str]:
    """Each stage's label as the phase's `model/stages.ts` writes it."""
    text = (FRONTEND / feature / "model" / "stages.ts").read_text()
    return {
        stage: label
        for stage, label in re.findall(r'^  "?([a-z-]+)"?: \{\n    label: "([^"]+)"', text, re.M)
    }


class TestStageNames:
    @pytest.mark.parametrize("feature", sorted(PHASE_STAGES))
    def test_every_stage_has_the_name_its_page_gives_it(self, feature: str) -> None:
        stages = get_args(PHASE_STAGES[feature])
        page = _page_labels(feature)
        assert set(page) == set(stages), "the page and the contract list the same stages"
        assert {stage: STAGE_LABELS.get(stage) for stage in stages} == page

    def test_an_unknown_stage_reads_as_words_not_a_key(self) -> None:
        assert stage_label("some-new-stage") == "some new stage"


class TestConnectionVerdicts:
    def test_each_verdict_reads_as_the_settings_page_says_it(self) -> None:
        page = (FRONTEND / "settings" / "model" / "connection.ts").read_text()
        said = dict(re.findall(r'^  (SUITABLE|WORKABLE|UNUSABLE): "([^"]+)",', page, re.M))

        assert said == VERDICT_WORDS


class TestNotes:
    def test_python_values_are_written_as_words(self) -> None:
        notes = {"digest": None, "applied": [], "refused": {}, "kept": True}

        assert readable_notes(notes) == "digest: none, applied: none, refused: none, kept: yes"

    def test_a_list_is_its_items_and_a_number_stays_a_number(self) -> None:
        assert readable_notes({"files": ["a.ts", "b.ts"], "attempts": 2, "rate": 0.5}) == (
            "files: a.ts, b.ts, attempts: 2, rate: 0.5"
        )


class TestStageFailures:
    def test_a_failure_with_no_message_is_a_sentence_not_a_class_name(self) -> None:
        said = readable_failure(httpx.ReadError(""))

        assert "ReadError" not in said
        assert "lost its connection" in said

    def test_a_path_on_the_server_is_cut_to_its_last_name(self) -> None:
        error = FileNotFoundError(
            2,
            "No such file or directory",
            "/home/someone/projects/research/workspaces/p1/package.json",
        )

        said = readable_failure(error)

        assert "/home/" not in said and "someone" not in said
        assert "package.json" in said

    def test_a_web_address_is_left_whole(self) -> None:
        said = readable_failure(RuntimeError("GET https://api.github.com/repos/a/b answered 404"))

        assert "https://api.github.com/repos/a/b" in said
