"""Admit a stage that did not apply.

The testing phase can be pointed at more than one kind of repository, and test
generation writes TypeScript from the API contract, so on a Java target there
is nothing for it to write. Recording that as a failure stopped the run, which
meant a Java repository could never reach the security stage at all; recording
it as complete would claim work nobody did.

The CHECK widens rather than goes, for the reason every other one here does: a
status outside the known set is a bug worth a database error rather than a
stored mystery.

Revision: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

PREVIOUS = ("pending", "generating", "complete", "failed")
ADDED = ("skipped",)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _set_check(values: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE app.stage_states DROP CONSTRAINT stage_states_status_check")
    op.execute(
        f"ALTER TABLE app.stage_states ADD CONSTRAINT stage_states_status_check "
        f"CHECK (status IN ({_quoted(values)}))"
    )


def upgrade() -> None:
    _set_check(PREVIOUS + ADDED)


def downgrade() -> None:
    # A skipped stage has no equivalent in the narrower set. Pending is the
    # closest honest answer: it says the stage did not run, which is true, and
    # it does not claim the work was done.
    op.execute("UPDATE app.stage_states SET status = 'pending' WHERE status = 'skipped'")
    _set_check(PREVIOUS)
