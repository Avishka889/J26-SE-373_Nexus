"""Admit the C2 kinds, and record which design version a run read.

The artefacts and design_overlays CHECK constraints were written when C1's six
kinds and seven overlay kinds were all that existed. C2 stores four artefact
kinds of its own and four overlay kinds for its human choices, so both CHECKs
widen; they stay CHECKs, because a kind outside the known set is a bug worth a
database error rather than a stored mystery.

`runs.source_version` is which version of the upstream axis this run read: a
C2 run generates from a design version, and "generated from design v1, the
design is now v2" is a fact the code snapshot must be able to state. Nullable,
because C1 runs read no upstream axis.

Revision: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
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
    "tech-stack",
    "api-contract",
    "contract-agreement",
    "code-repository",
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
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute("ALTER TABLE app.artefacts DROP CONSTRAINT artefacts_kind_check")
    op.execute(
        f"ALTER TABLE app.artefacts ADD CONSTRAINT artefacts_kind_check "
        f"CHECK (kind IN ({_quoted(ARTEFACT_KINDS)}))"
    )
    op.execute("ALTER TABLE app.design_overlays DROP CONSTRAINT design_overlays_kind_check")
    op.execute(
        f"ALTER TABLE app.design_overlays ADD CONSTRAINT design_overlays_kind_check "
        f"CHECK (kind IN ({_quoted(OVERLAY_KINDS)}))"
    )
    op.execute("ALTER TABLE app.runs ADD COLUMN source_version integer")
    op.execute(
        "COMMENT ON COLUMN app.runs.source_version IS "
        "'The upstream axis version this run read: a C2 run records the design "
        "version it generated from. Null for runs with no upstream axis.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app.runs DROP COLUMN source_version")
    op.execute("ALTER TABLE app.design_overlays DROP CONSTRAINT design_overlays_kind_check")
    op.execute(
        "ALTER TABLE app.design_overlays ADD CONSTRAINT design_overlays_kind_check "
        "CHECK (kind IN ('requirement_text','assumption_text','assumption_dismissed',"
        "'question_answer','node_label','flow_refinement','architecture_selection'))"
    )
    op.execute("ALTER TABLE app.artefacts DROP CONSTRAINT artefacts_kind_check")
    op.execute(
        "ALTER TABLE app.artefacts ADD CONSTRAINT artefacts_kind_check "
        "CHECK (kind IN ('requirements','architecture-graph','architecture-recommendation',"
        "'uml-diagrams','wireframes','sprint-plan'))"
    )
