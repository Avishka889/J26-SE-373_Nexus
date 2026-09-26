"""The C4 delivery contracts, held to what they claim to enforce.

The rollback plan's promises carry the weight here: approval cannot be anything
but required (FR20), a plan that cannot restore says why, and a plan that can
restore checks the served fingerprint, because "restored" has to mean the
verified release is back rather than that a redeploy finished.
"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from sdlc_contracts import (
    DeployPlan,
    DeployStep,
    FeedbackItem,
    FileValidation,
    MonitoringReport,
    PipelineConfig,
    PipelineFile,
    ReleaseCandidate,
    RollbackPlan,
    UpdateRollback,
    update_id_for,
)

WHEN = datetime(2026, 9, 27, 12, 0)
HASH_A = "a" * 64
HASH_B = "b" * 64
UID = update_id_for("npm:express@4.21.2->5.1.0")


class TestADeployPlan:
    def _plan(self, **overrides) -> dict:
        body = {
            "planId": "p1",
            "projectId": "proj",
            "generatedBy": "c4",
            "generatedAt": WHEN,
            "deployVersion": 1,
            "stack": "mern",
            "target": "local",
            "candidateHash": HASH_A,
            "targets": [{"role": "app", "provider": "local-docker", "resource": "container"}],
            "steps": [
                {"id": "image", "label": "Load the verified image", "provider": "local-docker"},
                {
                    "id": "switch",
                    "label": "Point production at the candidate",
                    "provider": "local-docker",
                    "dependsOn": "image",
                    "compensation": "point production back at the previous verified container",
                    "movesTraffic": True,
                },
            ],
            "rollback": {"note": "application only; data is in memory"},
            "environmentProtection": {"github": "not-applicable"},
        }
        body.update(overrides)
        return body

    def test_a_plan_on_the_local_target_is_accepted(self) -> None:
        assert DeployPlan.model_validate(self._plan()).environment_protection.mechanism == (
            "platform-gate"
        )

    def test_the_stack_is_named_as_c2_names_it(self) -> None:
        with pytest.raises(ValidationError):
            DeployPlan.model_validate(self._plan(stack="spring-boot"))

    def test_a_step_that_moves_traffic_says_how_to_move_it_back(self) -> None:
        with pytest.raises(ValidationError, match="moves traffic"):
            DeployStep.model_validate(
                {"id": "switch", "label": "Switch", "movesTraffic": True, "provider": "vercel"}
            )

    def test_a_step_cannot_appear_twice(self) -> None:
        body = self._plan()
        body["steps"].append({"id": "image", "label": "again", "dependsOn": "switch"})
        with pytest.raises(ValidationError, match="appears twice"):
            DeployPlan.model_validate(body)


def _validation(outcome: str, **extra) -> dict:
    return {"validator": "json-schema", "tool": "render.json", "outcome": outcome, **extra}


def _file(*validations: dict) -> dict:
    return {
        "path": "render.yaml",
        "purpose": "hosting",
        "sha256": HASH_A,
        "bytes": 120,
        "templateId": "mern/render.yaml@1",
        "validations": list(validations),
    }


class TestPipelineConfigValidity:
    def _config(self, *, supported: bool = True, files: list[dict] | None = None) -> dict:
        return {
            "version": 1,
            "generatedAt": WHEN,
            "codeVersion": 1,
            "candidateHash": HASH_A,
            "stack": {
                "stackId": "mern" if supported else "react-spring-postgres",
                "supported": supported,
                "reason": "" if supported else "no validated templates for this stack",
                "layout": (
                    {
                        "kind": "one-process",
                        "frontendDir": "apps/web",
                        "backendDir": "apps/api",
                        "servesFrontendFromBackend": True,
                        "evidence": ["apps/api/src/server.ts serves ../../web/dist"],
                    }
                    if supported
                    else None
                ),
            },
            "files": files if files is not None else [_file(_validation("passed"))],
            "kubernetes": "skipped",
            "kubernetesReason": "optional, and no cluster exists on this machine",
        }

    def test_every_file_checked_and_passed_is_valid(self) -> None:
        assert PipelineConfig.model_validate(self._config()).valid

    def test_a_file_no_validator_ran_on_is_unverified_not_valid(self) -> None:
        unchecked = _file(_validation("not-run", reason="docker is not running"))
        assert not PipelineFile.model_validate(unchecked).valid
        assert not PipelineConfig.model_validate(self._config(files=[unchecked])).valid

    def test_a_check_that_could_not_run_leaves_the_file_unverified(self) -> None:
        """A Dockerfile whose linter had no Docker to run in is not valid on the
        strength of its secret scan alone."""
        partial = _file(_validation("passed"), _validation("not-run", reason="no Docker daemon"))
        assert not PipelineFile.model_validate(partial).valid

    def test_one_failure_makes_the_generation_invalid(self) -> None:
        failed = _file(_validation("passed"), _validation("failed", findings=["bad key"]))
        assert not PipelineConfig.model_validate(self._config(files=[failed])).valid

    def test_an_unsupported_stack_is_reported_and_given_no_files(self) -> None:
        """FR14: report the stack rather than offer an unverified configuration."""
        with pytest.raises(ValidationError, match="unsupported stack"):
            PipelineConfig.model_validate(self._config(supported=False))
        reported = PipelineConfig.model_validate(self._config(supported=False, files=[]))
        assert not reported.valid

    def test_a_failure_says_what_it_found(self) -> None:
        with pytest.raises(ValidationError, match="without saying"):
            FileValidation.model_validate(_validation("failed"))

    def test_a_validator_that_did_not_run_says_why(self) -> None:
        with pytest.raises(ValidationError, match="did not say why"):
            FileValidation.model_validate(_validation("not-run"))


class TestAReleaseCandidateIsVerifiedOnlyByEvidence:
    def _candidate(self, **overrides) -> dict:
        body = {
            "version": 1,
            "generatedAt": WHEN,
            "codeVersion": 1,
            "candidateHash": HASH_A,
            "included": [UID],
            "imageDigest": "sha256:" + "c" * 64,
            "toolchain": "node 22.17.0 / npm 10.9.2",
            "isolation": "a container with no host mounts",
            "steps": [
                {"name": "install", "command": "npm ci", "outcome": "passed", "durationSeconds": 9}
            ],
            "smoke": [{"path": "/orders", "statusCode": 200, "ok": True}],
            "fingerprint": HASH_A,
        }
        body.update(overrides)
        return body

    def test_everything_passed_and_the_fingerprint_matches(self) -> None:
        assert ReleaseCandidate.model_validate(self._candidate()).verified

    @pytest.mark.parametrize(
        "overrides",
        [
            {"fingerprint": HASH_B},
            {"fingerprint": None},
            {"imageDigest": None},
            {"smoke": []},
            {"smoke": [{"path": "/orders", "statusCode": 500, "ok": False}]},
            {"steps": [{"name": "test", "command": "npm test", "outcome": "failed"}]},
        ],
    )
    def test_any_missing_proof_is_not_verified(self, overrides) -> None:
        assert not ReleaseCandidate.model_validate(self._candidate(**overrides)).verified

    def test_an_update_is_in_or_out(self) -> None:
        with pytest.raises(ValidationError, match="both included and excluded"):
            ReleaseCandidate.model_validate(
                self._candidate(excluded=[{"updateId": UID, "reason": "rejected", "detail": "x"}])
            )


class TestARollbackPlan:
    def _plan(self, **overrides) -> dict:
        body = {
            "version": 2,
            "generatedAt": WHEN,
            "candidateHash": HASH_B,
            "restoreTarget": {
                "deploymentId": "d1",
                "deployVersion": 1,
                "candidateHash": HASH_A,
                "target": "local",
                "imageDigest": "sha256:" + "d" * 64,
                "verifiedAt": WHEN,
            },
            "restorable": True,
            "steps": [
                {
                    "id": "start",
                    "label": "Start the verified image",
                    "provider": "local-docker",
                    "action": "run the image by digest",
                    "movesTraffic": True,
                }
            ],
            "checks": [{"id": "fp", "kind": "fingerprint", "role": "app", "expect": HASH_A}],
            "updates": [{"updateId": UID, "level": "high", "status": "prepared"}],
        }
        body.update(overrides)
        return body

    def test_a_prepared_plan_is_accepted_and_blocks_nothing(self) -> None:
        plan = RollbackPlan.model_validate(self._plan())
        assert plan.approval == "required"
        assert plan.blocks == []

    def test_approval_cannot_be_anything_but_required(self) -> None:
        """FR20 as a type: there is no value that would make a rollback automatic."""
        with pytest.raises(ValidationError):
            RollbackPlan.model_validate(self._plan(approval="automatic"))

    def test_restored_has_to_be_checkable(self) -> None:
        with pytest.raises(ValidationError, match="fingerprint"):
            RollbackPlan.model_validate(
                self._plan(checks=[{"id": "h", "kind": "health", "role": "app", "expect": "200"}])
            )

    def test_a_plan_cannot_restore_the_candidate_it_rolls_back_from(self) -> None:
        with pytest.raises(ValidationError, match="cannot restore the candidate"):
            RollbackPlan.model_validate(self._plan(candidateHash=HASH_A))

    def test_nowhere_to_go_is_said_and_blocks_a_high_update(self) -> None:
        plan = RollbackPlan.model_validate(
            self._plan(
                restoreTarget=None,
                restorable=False,
                unrestorableReason="this is the project's first release",
                steps=[],
                checks=[],
                updates=[
                    {
                        "updateId": UID,
                        "level": "high",
                        "status": "unavailable",
                        "reason": "no verified release to return to",
                    }
                ],
            )
        )
        assert plan.blocks == [UID]

    def test_nowhere_to_go_without_a_reason_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must say why"):
            RollbackPlan.model_validate(
                self._plan(restoreTarget=None, restorable=False, steps=[], checks=[], updates=[])
            )

    def test_a_high_update_always_needs_a_rollback(self) -> None:
        with pytest.raises(ValidationError, match="FR17"):
            UpdateRollback.model_validate(
                {"updateId": UID, "level": "high", "status": "not-required"}
            )


class TestAMonitoringReport:
    def _report(self, **overrides) -> dict:
        start = WHEN
        body = {
            "version": 1,
            "generatedAt": WHEN + timedelta(minutes=10),
            "deploymentId": "d1",
            "target": "local",
            "urls": ["http://127.0.0.1:4100"],
            "source": "orchestrator HTTP probes every 30 s from this host",
            "windowStart": start,
            "windowEnd": start + timedelta(minutes=10),
            "probeIntervalSeconds": 30,
            "states": [
                {
                    "state": "healthy",
                    "start": start,
                    "end": start + timedelta(minutes=6),
                    "samples": 12,
                    "evidence": "12 of 12 answered under 2 s",
                },
                {
                    "state": "down",
                    "start": start + timedelta(minutes=6),
                    "end": start + timedelta(minutes=10),
                    "samples": 8,
                    "evidence": "connection refused 8 times",
                },
            ],
            "currentState": "down",
            "expectedCandidateHash": HASH_A,
        }
        body.update(overrides)
        return body

    def test_a_report_with_its_source_and_window_is_accepted(self) -> None:
        assert MonitoringReport.model_validate(self._report()).current_state == "down"

    def test_a_number_without_a_source_does_not_ship(self) -> None:
        with pytest.raises(ValidationError):
            MonitoringReport.model_validate(self._report(source=""))

    def test_the_current_state_is_the_last_one_seen(self) -> None:
        with pytest.raises(ValidationError, match="last interval"):
            MonitoringReport.model_validate(self._report(currentState="healthy"))

    def test_intervals_stay_inside_the_window(self) -> None:
        body = self._report()
        body["states"][1]["end"] = WHEN + timedelta(minutes=20)
        with pytest.raises(ValidationError, match="leave the window"):
            MonitoringReport.model_validate(body)

    def test_nothing_seen_is_unknown(self) -> None:
        report = MonitoringReport.model_validate(self._report(states=[], currentState="unknown"))
        assert report.current_state == "unknown"

    def test_an_idle_time_says_where_it_was_measured_from(self) -> None:
        report = MonitoringReport.model_validate(
            self._report(idleSeconds=1200.0, idleFrom="last-sample")
        )
        assert report.idle_seconds == 1200.0
        with pytest.raises(ValidationError, match="where it was measured from"):
            MonitoringReport.model_validate(self._report(idleSeconds=1200.0))
        with pytest.raises(ValidationError, match="where it was measured from"):
            MonitoringReport.model_validate(self._report(idleFrom="released"))


class TestFeedbackNamesWhereItCameFrom:
    def test_an_item_names_its_source_report(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackItem.model_validate(
                {
                    "id": "f1",
                    "kind": "runtime",
                    "summary": "the release went down",
                    "evidence": "connection refused 8 times",
                    "suggestedRequirement": "The service shall recover from a restart.",
                }
            )
