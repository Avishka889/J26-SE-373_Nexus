"""One pending gate per project per phase, not per project.

The original index allowed one pending gate per project, whatever its kind,
which was true and unambiguous while only the design phase existed. Two phases
later it is neither: a code review parked at its gate made the design phase
unable to open one at all, and the two axes are supposed to be independent.
The code already says so in three places. `submit_change` reads only this
component's runs, on the grounds that "a code run paused at its own gate is not
the design phase being busy"; the code snapshot reports the design version it
generated from precisely so a design that moves on can say so; and every
`pending_gate` caller already asks by kind.

Found live. A design change was submitted on a project whose code review was
still pending: the run walked all eight nodes, wrote every artefact, and then
could not open its gate, which surfaced as an AssertionError with no message
after six model calls.

The invariant that matters is kept: one pending decision per phase, so "the
pending design gate" is still an unambiguous phrase.

Revision: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.one_pending_gate_per_project")
    op.execute(
        "CREATE UNIQUE INDEX one_pending_gate_per_project_kind "
        "ON app.gates (project_id, kind) WHERE state = 'pending'"
    )


def downgrade() -> None:
    # Only reversible while no project holds two pending gates at once, which
    # is the state this migration exists to allow. Said plainly rather than
    # failing with a duplicate key error from the index build.
    op.execute("DROP INDEX IF EXISTS app.one_pending_gate_per_project_kind")
    op.execute(
        "CREATE UNIQUE INDEX one_pending_gate_per_project "
        "ON app.gates (project_id) WHERE state = 'pending'"
    )
