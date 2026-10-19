"""Admit a person's correction of a requirement's priority.

Priority came from a rule and nothing could correct it: a requirement's text
could be edited, its priority could not, and the sprint was ranked on it (review
item C1-2).

- `app.design_overlays.kind` may be `requirement_priority`: the priority a
  person set for one requirement, kept beside the artefact like every other edit.

Revision: 0017
Revises: 0016
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

#: Every kind, as the migrations before this one left them and the one this
#: adds: the newest list is the one held against the vocabulary in the code.
OVERLAY_KINDS = (
    # C1
    "requirement_text",
    "requirement_priority",
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

ADDED_OVERLAY_KINDS = ("requirement_priority",)


def _check(kinds: tuple[str, ...]) -> None:
    quoted = ", ".join(f"'{kind}'" for kind in kinds)
    op.execute("ALTER TABLE app.design_overlays DROP CONSTRAINT design_overlays_kind_check")
    op.execute(
        "ALTER TABLE app.design_overlays ADD CONSTRAINT design_overlays_kind_check "
        f"CHECK (kind IN ({quoted}))"
    )


def upgrade() -> None:
    _check(OVERLAY_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM app.design_overlays WHERE kind = 'requirement_priority'")
    _check(tuple(kind for kind in OVERLAY_KINDS if kind not in ADDED_OVERLAY_KINDS))
