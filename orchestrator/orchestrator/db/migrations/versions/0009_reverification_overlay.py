"""Admit the re-verification overlay.

One kind, and it is the only overlay a machine writes. A re-verification is
C3's arithmetic over two passes, and it concerns a proposal that lives in an
artefact sealed by the run that produced it, so it cannot be written back into
that artefact without editing what the machine said at the time. It is not a
human correction either, which is what the rest of this table holds. The row
shape fits and the honesty rule survives: the artefact stays as produced, and
the overlay says what happened to it afterwards.

The list is spelled out rather than imported from 0008: alembic loads a version
file by path, so a module whose name starts with a digit is not importable, and
a migration that silently dropped a kind on downgrade is worse than a repeated
tuple.

Revision: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

PREVIOUS = (
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

ADDED = ("remediation_reverification",)

#: Named exactly as 0008 names it, because a test reads the newest migration
#: that defines this and compares it against the contract's vocabulary. A
#: migration that widened the CHECK under a different name would leave that
#: test checking a list two revisions old and passing while the database
#: disagreed.
OVERLAY_KINDS = PREVIOUS + ADDED


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _set_check(values: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE app.design_overlays DROP CONSTRAINT design_overlays_kind_check")
    op.execute(
        f"ALTER TABLE app.design_overlays ADD CONSTRAINT design_overlays_kind_check "
        f"CHECK (kind IN ({_quoted(values)}))"
    )


def upgrade() -> None:
    _set_check(OVERLAY_KINDS)


def downgrade() -> None:
    # Rows of the removed kind would violate the narrower CHECK, so they go
    # first. Losing a re-verification on a downgrade is correct: the version
    # being downgraded to has nothing that can read one.
    op.execute(f"DELETE FROM app.design_overlays WHERE kind IN ({_quoted(ADDED)})")
    _set_check(PREVIOUS)
