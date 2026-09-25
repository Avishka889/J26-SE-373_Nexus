"""Admit the C3 kinds.

Four artefact kinds and four overlay kinds for Testing and Security, added the
way C2's were: the CHECKs stay CHECKs and widen, because a kind outside the
known set is a bug worth a database error rather than a stored mystery.

`validation-report` keeps the name C4 already reads, since it is the C3 to C4
seam and was stubbed for exactly this. `heal-report` is its own kind rather
than a field on the test report, because the two have different lifetimes: a
test report is replaced by the next run, and a refused repair is evidence that
has to outlive it.

Revision: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
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
)


#: What this migration adds, named rather than derived. The first version of
#: the downgrade filtered by suffix and would have left `target_selection`
#: behind, which is the kind of quiet wrongness a downgrade is least likely to
#: be tested for.
ADDED_ARTEFACT_KINDS = (
    "test-report",
    "heal-report",
    "validation-report",
    "remediation-proposal",
)

ADDED_OVERLAY_KINDS = (
    "target_selection",
    "finding_decision",
    "heal_decision",
    "remediation_decision",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _without(values: tuple[str, ...], removed: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value for value in values if value not in removed)


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


def downgrade() -> None:
    op.execute("ALTER TABLE app.design_overlays DROP CONSTRAINT design_overlays_kind_check")
    op.execute(
        f"ALTER TABLE app.design_overlays ADD CONSTRAINT design_overlays_kind_check "
        f"CHECK (kind IN ({_quoted(_without(OVERLAY_KINDS, ADDED_OVERLAY_KINDS))}))"
    )
    op.execute("ALTER TABLE app.artefacts DROP CONSTRAINT artefacts_kind_check")
    op.execute(
        f"ALTER TABLE app.artefacts ADD CONSTRAINT artefacts_kind_check "
        f"CHECK (kind IN ({_quoted(_without(ARTEFACT_KINDS, ADDED_ARTEFACT_KINDS))}))"
    )
