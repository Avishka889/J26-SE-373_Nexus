"""The deploy snapshot's promises to the browser.

The client indexes every stage without a null guard and renders what the
computed fields say without re-deriving them, so these are the checks that keep
a missing stage, a silent failure or a silent skip out of the payload.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError
from sdlc_contracts import DEPLOY_STAGE_IDS, DeploySnapshot, update_id_for

WHEN = datetime(2026, 9, 27, 12, 0)
UID = update_id_for("npm:express@4.21.2->5.1.0")


def _snapshot(**overrides) -> dict:
    body = {
        "projectId": "p",
        "deployVersion": 2,
        "testVersion": 1,
        "approvedTestVersion": 1,
        "codeVersion": 3,
        "deployedCodeVersion": 3,
        "stages": {stage: {"id": stage} for stage in DEPLOY_STAGE_IDS},
        "gate": {},
    }
    body.update(overrides)
    return body


def test_a_snapshot_with_every_stage_is_accepted() -> None:
    snapshot = DeploySnapshot.model_validate(_snapshot())
    assert not snapshot.code_moved_on
    assert snapshot.live_state == "unknown"
    assert not snapshot.rollback_pending


def test_a_missing_stage_is_refused() -> None:
    stages = {stage: {"id": stage} for stage in DEPLOY_STAGE_IDS if stage != "release"}
    with pytest.raises(ValidationError, match="missing stages: release"):
        DeploySnapshot.model_validate(_snapshot(stages=stages))


def test_a_failed_stage_says_why() -> None:
    stages = {stage: {"id": stage} for stage in DEPLOY_STAGE_IDS}
    stages["staging-verification"] = {"id": "staging-verification", "status": "failed"}
    with pytest.raises(ValidationError, match="failed without saying why"):
        DeploySnapshot.model_validate(_snapshot(stages=stages))


def test_a_skipped_stage_says_why_too() -> None:
    stages = {stage: {"id": stage} for stage in DEPLOY_STAGE_IDS}
    stages["staging-verification"] = {"id": "staging-verification", "status": "skipped"}
    with pytest.raises(ValidationError, match="skipped without saying why"):
        DeploySnapshot.model_validate(_snapshot(stages=stages))


def test_newer_code_makes_the_artefacts_stale_once_its_tests_are_approved() -> None:
    snapshot = DeploySnapshot.model_validate(_snapshot(codeVersion=4, approvedTestedCodeVersion=4))
    assert snapshot.code_moved_on


def test_newer_code_waiting_for_its_tests_leaves_them_standing() -> None:
    """They describe the code that may ship: the next sprint's code holds nothing back."""
    snapshot = DeploySnapshot.model_validate(_snapshot(codeVersion=4, approvedTestedCodeVersion=3))
    assert not snapshot.code_moved_on


def test_owed_decisions_and_a_pending_rollback_are_counted_for_the_reader() -> None:
    snapshot = DeploySnapshot.model_validate(
        _snapshot(
            decisions=[
                {"updateId": UID, "needsDecision": True, "needsReviewNote": True},
            ],
            deployments=[
                {
                    "id": "d2",
                    "kind": "release",
                    "target": "local",
                    "state": "awaiting-rollback-approval",
                    "candidateHash": "a" * 64,
                    "deployVersion": 2,
                    "requestedBy": "you",
                    "createdAt": WHEN,
                    "cause": "the smoke check answered 500 after the switch",
                }
            ],
        )
    )
    assert snapshot.awaiting_decision == 1
    assert snapshot.rollback_pending
