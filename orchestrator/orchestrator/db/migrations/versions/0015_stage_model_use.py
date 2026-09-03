"""What answered a stage, kept on the stage beside its status.

A stage's notes reached the audit log as one line of words, and nowhere a page
could read them. The model each response named and what it used are now
reported by every stage that asks a model (`model_use` in its notes), and
this keeps them with the stage's current version.

- `app.stage_states.model_use`: the models the responses named, the requests
  answered, and the tokens in, out and reasoning, as `StageModelUse` writes
  them. Written whenever a stage completes, and null when it completed
  without asking a model, so a value from an earlier version never stays
  behind on one made without it.

Nullable, so every existing stage keeps meaning what it meant: not recorded.

Revision: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.stage_states ADD COLUMN model_use jsonb")
    op.execute("""
        COMMENT ON COLUMN app.stage_states.model_use IS
        'What answered the current version, where it asked a model. Null: none asked, '
        'or not recorded.'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE app.stage_states DROP COLUMN IF EXISTS model_use")
