"""The deploy axis's vocabulary, held to the rules the tables it lands in rely on.

Stage rows from every phase share one table keyed by project and stage id, and
artefacts share one keyed by kind and version, so a deploy name that repeated
another phase's would read or overwrite that phase's row. These are the checks
that make a collision a red test rather than a quiet cross-phase write.
"""

from sdlc_contracts import (
    ARTEFACT_KINDS,
    CODE_ARTEFACT_KINDS,
    CODE_OVERLAY_KINDS,
    CODE_STAGE_IDS,
    DEPLOY_ARTEFACT_KINDS,
    DEPLOY_ARTEFACT_STAGE_IDS,
    DEPLOY_GATED_ARTEFACT_KINDS,
    DEPLOY_GENERATING_STAGE_IDS,
    DEPLOY_OVERLAY_KINDS,
    DEPLOY_PROJECTED_STAGE_IDS,
    DEPLOY_RUNNER_STAGE_IDS,
    DEPLOY_STAGE_IDS,
    DESIGN_STAGE_IDS,
    TEST_ARTEFACT_KINDS,
    TEST_OVERLAY_KINDS,
    TEST_STAGE_IDS,
)


def test_the_stages_run_in_the_order_their_inputs_exist() -> None:
    """Notes before the code search, both before the risk, the risk before
    anything is built, the gate before what it authorises."""
    assert DEPLOY_STAGE_IDS == (
        "dependency-updates",
        "changelog-analysis",
        "impact-analysis",
        "risk-assessment",
        "pipeline-generation",
        "staging-verification",
        "rollback-planning",
        "deployment-review",
        "release",
        "monitoring",
    )


def test_every_stage_is_produced_by_exactly_one_kind_of_thing() -> None:
    """A graph node, the gate, or the orchestrator's runner, never two."""
    produced = set(DEPLOY_ARTEFACT_STAGE_IDS)
    gate = set(DEPLOY_PROJECTED_STAGE_IDS)
    runner = set(DEPLOY_RUNNER_STAGE_IDS)
    assert not produced & gate
    assert not produced & runner
    assert not gate & runner
    assert produced | gate | runner == set(DEPLOY_STAGE_IDS)
    assert DEPLOY_GENERATING_STAGE_IDS == DEPLOY_ARTEFACT_STAGE_IDS


def test_no_deploy_stage_shares_a_name_with_another_phase() -> None:
    others = set(DESIGN_STAGE_IDS) | set(CODE_STAGE_IDS) | set(TEST_STAGE_IDS)
    assert not set(DEPLOY_STAGE_IDS) & others


def test_no_deploy_kind_shares_a_name_with_another_phase() -> None:
    others = set(ARTEFACT_KINDS) | set(CODE_ARTEFACT_KINDS) | set(TEST_ARTEFACT_KINDS)
    assert not set(DEPLOY_ARTEFACT_KINDS) & others
    assert not set(DEPLOY_OVERLAY_KINDS) & (set(CODE_OVERLAY_KINDS) | set(TEST_OVERLAY_KINDS))


def test_the_gate_freezes_everything_but_what_is_written_after_it() -> None:
    """Monitoring happens after an approval by definition, and so does the
    feedback derived from it; freezing them would forbid the record."""
    assert set(DEPLOY_ARTEFACT_KINDS) - set(DEPLOY_GATED_ARTEFACT_KINDS) == {
        "monitoring-report",
        "feedback",
    }
