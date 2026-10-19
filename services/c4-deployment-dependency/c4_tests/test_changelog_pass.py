"""The live pass's bookkeeping, with the network and the model scripted.

An update's release notes belong to the dependency, so two cases that share an
update are one model call: the model is asked once, both cases get its vote,
and the record says which case the second one shared it with, so the spend is
counted once.
"""

from datetime import UTC, datetime

from c4.eval import changelog_pass
from c4.intake.releases import Notes
from sdlc_contracts import ChangelogReport

from .test_eval import _case, _observed
from .test_usage_signal import _update


def test_cases_that_share_an_update_share_one_call(monkeypatch, tmp_path) -> None:
    first = _case("first", "1.0.0", "2.0.0", _observed("passed"))
    second = first.model_copy(update={"case_id": "second"})
    other = _case("other", "1.0.0", "1.1.0", _observed("passed"))
    updates = {
        "first": _update("pkg-first"),
        "second": _update("pkg-first"),
        "other": _update("pkg-other", new="1.1.0"),
    }
    asked: list[list[str]] = []

    monkeypatch.setattr(
        changelog_pass, "client_for", lambda case, studies: type("C", (), {"files": {}})()
    )
    monkeypatch.setattr(changelog_pass, "update_for", lambda case, files: updates[case.case_id])

    async def notes_for(update, fetcher):
        return Notes()

    monkeypatch.setattr(changelog_pass, "notes_for", notes_for)

    async def scripted(dependency_updates, texts, *, model, version):
        asked.append([update.package for update in dependency_updates.updates])
        return ChangelogReport.model_validate(
            {
                "version": 1,
                "generatedAt": datetime.now(UTC).isoformat(),
                "modelId": model,
                "promptId": "changelog-extract/1",
                "promptSha256": "0" * 64,
                "perUpdate": [
                    {
                        "updateId": update.id,
                        "notesFound": False,
                        "claims": [],
                        "refused": [],
                        "vote": {
                            "signal": "changelog",
                            "level": None,
                            "abstainedReason": "no release notes were found",
                            "ruleId": "changelog-rule/1",
                            "rationale": "The changelog signal abstains: no release notes.",
                        },
                    }
                    for update in dependency_updates.updates
                ],
            }
        )

    monkeypatch.setattr(changelog_pass, "analyse", scripted)
    votes = {case: {"semver": "high", "usage": {}} for case in ("first", "second", "other")}

    import asyncio

    result, finished = asyncio.run(
        changelog_pass.run(
            [first, second, other],
            votes,
            tmp_path,
            cache=tmp_path / "cache",
            texts_dir=tmp_path / "texts",
            log=lambda *a, **k: None,
        )
    )

    assert finished
    assert asked == [["pkg-first", "pkg-other"]]
    recorded = result["votes"]
    assert recorded["second"]["changelog"]["sharedWith"] == "first"
    assert "sharedWith" not in recorded["first"]["changelog"]
    assert recorded["first"]["changelog"]["level"] == recorded["second"]["changelog"]["level"]
    assert result["changelog"]["updatesAnalysed"] == 2
    assert result["changelog"]["casesSharingAnUpdate"] == {"first": ["second"]}
