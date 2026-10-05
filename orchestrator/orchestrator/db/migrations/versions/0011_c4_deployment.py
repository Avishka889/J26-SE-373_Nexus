"""Admit the C4 kinds, and give releases somewhere to be recorded.

Ten artefact kinds and six overlay kinds for Deployment, added the way C2's and
C3's were: the CHECKs stay CHECKs and widen, because a kind outside the known set
is a bug worth a database error rather than a stored mystery.

Four tables, because execution is the orchestrator's job (architecture decisions
2 and 3) and a job needs a record that outlives the run that asked for it:

- `deploy_files`: what C4 generated to deploy with, kept apart from
  `code_files`. C2 replaces the whole repository tree on every push, so these
  are committed on top of C2's commit at release time rather than stored among
  C2's files, where a regeneration of the code would delete them.
- `deployments`: one row per attempt to release or roll back, including every
  failure and its cause (FR16). The idempotency key is unique, so asking for
  the same release twice finds the first rather than starting a second, and at
  most one deployment per project is pending or running at a time.
- `deploy_steps`: the thin saga's step table. Each step carries its own key, so
  a crashed step can be found and adopted rather than repeated, and says whether
  it moved production traffic, which is where automatic compensation stops.
- `health_samples`: every probe of a live release, kept so a monitoring report's
  states can be traced back to what was actually observed.

Revision: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

ARTEFACT_KINDS = (
    # C1
    "requirements",
    "architecture-graph",
    "architecture-recommendation",
    "uml-diagrams",
    "wireframes",
    "sprint-plan",
    # C2
    "sprint-scope",
    "tech-stack",
    "api-contract",
    "contract-agreement",
    "code-repository",
    # C3
    "test-report",
    "heal-report",
    "validation-report",
    "remediation-proposal",
    # C4
    "dependency-updates",
    "changelog-report",
    "impact-report",
    "risk-report",
    "pipeline-config",
    "deploy-plan",
    "release-candidate",
    "rollback-plan",
    "monitoring-report",
    "feedback",
)

OVERLAY_KINDS = (
    # C1
    "requirement_text",
    "assumption_text",
    "assumption_dismissed",
    "question_answer",
    "node_label",
    "flow_refinement",
    "architecture_selection",
    # C2
    "story_scope",
    "stack_selection",
    "contract_arm_choice",
    "contract_item_decision",
    # C3
    "target_selection",
    "finding_decision",
    "heal_decision",
    "remediation_decision",
    "remediation_reverification",
    # C4
    "update_decision",
    "update_scope",
    "release_target",
    "release_policy",
    "rollback_decision",
    "feedback_decision",
)

#: What this migration adds, named rather than derived, so the downgrade removes
#: exactly these and nothing a later migration relies on.
ADDED_ARTEFACT_KINDS = ARTEFACT_KINDS[ARTEFACT_KINDS.index("dependency-updates") :]
ADDED_OVERLAY_KINDS = OVERLAY_KINDS[OVERLAY_KINDS.index("update_decision") :]


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _without(values: tuple[str, ...], removed: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value for value in values if value not in removed)


def _set_checks(artefacts: tuple[str, ...], overlays: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE app.artefacts DROP CONSTRAINT artefacts_kind_check")
    op.execute(
        f"ALTER TABLE app.artefacts ADD CONSTRAINT artefacts_kind_check "
        f"CHECK (kind IN ({_quoted(artefacts)}))"
    )
    op.execute("ALTER TABLE app.design_overlays DROP CONSTRAINT design_overlays_kind_check")
    op.execute(
        f"ALTER TABLE app.design_overlays ADD CONSTRAINT design_overlays_kind_check "
        f"CHECK (kind IN ({_quoted(overlays)}))"
    )


def upgrade() -> None:
    _set_checks(ARTEFACT_KINDS, OVERLAY_KINDS)

    op.execute("""
        CREATE TABLE app.deploy_files (
            project_id text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            -- The deploy axis version, not the code one.
            version    integer NOT NULL,
            path       text NOT NULL,
            content    text NOT NULL,
            sha256     text NOT NULL,
            -- Which stage wrote it, so a stage retried replaces exactly its own
            -- files: release notes, the lockfile, the deployment layer.
            stage_id   text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, version, path)
        )
    """)

    op.execute("""
        CREATE TABLE app.deployments (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id      text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            deploy_version  integer NOT NULL,
            kind            text NOT NULL CHECK (kind IN ('release','rollback')),
            target          text NOT NULL CHECK (target IN ('local','cloud')),
            plan_id         text NOT NULL,
            candidate_hash  text NOT NULL,
            idempotency_key text NOT NULL UNIQUE,
            state           text NOT NULL CHECK (state IN (
                'pending','running','succeeded','compensated','failed',
                'awaiting-rollback-approval','rolled-back')),
            -- What authorised it: the gate decision, the standing policy, or a
            -- person's rollback decision, with who and when.
            authorised      jsonb NOT NULL,
            requested_by    text NOT NULL,
            gate_id         uuid REFERENCES app.gates(id) ON DELETE SET NULL,
            -- For a rollback, the release it returned to.
            restores        uuid REFERENCES app.deployments(id) ON DELETE SET NULL,
            verified        boolean NOT NULL DEFAULT false,
            verified_at     timestamptz,
            -- What the release served when it was checked, per target.
            fingerprint     jsonb,
            url             text,
            -- Why it failed, in the provider's words where it gave any (FR16).
            cause           text,
            -- The controlled failure scenario injected into it, when one was, so
            -- a metric never mixes injected failures with organic ones.
            fault_injected  text,
            heartbeat_at    timestamptz,
            created_at      timestamptz NOT NULL DEFAULT now(),
            finished_at     timestamptz
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX one_active_deployment_per_project
            ON app.deployments (project_id) WHERE state IN ('pending','running')
    """)
    op.execute(
        "CREATE INDEX deployments_by_project ON app.deployments (project_id, created_at DESC)"
    )

    op.execute("""
        CREATE TABLE app.deploy_steps (
            deployment_id   uuid NOT NULL REFERENCES app.deployments(id) ON DELETE CASCADE,
            seq             integer NOT NULL,
            step_id         text NOT NULL,
            provider        text,
            idempotency_key text NOT NULL UNIQUE,
            attempt         integer NOT NULL DEFAULT 0,
            state           text NOT NULL CHECK (state IN (
                'pending','running','succeeded','failed','compensated','skipped')),
            moves_traffic   boolean NOT NULL DEFAULT false,
            -- What the step created or found, so compensation and adoption know
            -- what to act on.
            resource        jsonb,
            command         text,
            log_tail        text NOT NULL DEFAULT '',
            error           text,
            started_at      timestamptz,
            finished_at     timestamptz,
            PRIMARY KEY (deployment_id, seq)
        )
    """)

    op.execute("""
        CREATE TABLE app.health_samples (
            id                   bigserial PRIMARY KEY,
            deployment_id        uuid NOT NULL REFERENCES app.deployments(id) ON DELETE CASCADE,
            project_id           text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            at                   timestamptz NOT NULL DEFAULT now(),
            probe                text NOT NULL,
            status_code          integer,
            latency_ms           double precision,
            ok                   boolean NOT NULL,
            observed_fingerprint text,
            error                text
        )
    """)
    op.execute(
        "CREATE INDEX health_samples_by_deployment ON app.health_samples (deployment_id, at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE app.health_samples")
    op.execute("DROP TABLE app.deploy_steps")
    op.execute("DROP TABLE app.deployments")
    op.execute("DROP TABLE app.deploy_files")
    op.execute(f"DELETE FROM app.artefacts WHERE kind IN ({_quoted(ADDED_ARTEFACT_KINDS)})")
    op.execute(f"DELETE FROM app.design_overlays WHERE kind IN ({_quoted(ADDED_OVERLAY_KINDS)})")
    _set_checks(
        _without(ARTEFACT_KINDS, ADDED_ARTEFACT_KINDS),
        _without(OVERLAY_KINDS, ADDED_OVERLAY_KINDS),
    )
