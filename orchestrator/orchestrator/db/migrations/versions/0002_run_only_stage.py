"""Let a run regenerate exactly one stage.

Retrying a stage used to create an ordinary run, which walks the whole graph.
With one node standing in for the component that regenerated two artefacts; with
one node per stage it regenerates six, so pressing "retry" on the wireframes
silently rewrote the requirements, the graph, the diagrams and the sprint plan
the reader had just read and accepted. It also cost six model calls to fix one
artefact.

A column rather than a value squeezed into `resume_payload`, which belongs to the
gate decision, or into `component`, which names which component is running.
Nullable, so every existing run keeps meaning what it meant: a full pass through
the graph ending at the gate.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.runs
        ADD COLUMN only_stage text
    """)
    op.execute("""
        COMMENT ON COLUMN app.runs.only_stage IS
        'When set, this run regenerates that one stage and never reaches a gate. '
        'Null means a full pass through the graph.'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE app.runs DROP COLUMN only_stage")
