"""What a run ran on: the model, and what it asked that model about thinking.

A run wrote its model once, into the free text of its "Run started" audit
entry, and nowhere else. The runs table had no column for it; a regeneration
after "changes" resumes the same run and wrote no model at all, and neither did
a single stage retry. With one model per component, fixed for the life of the
process, that was barely enough. Once a person can choose, two runs of the
same phase can differ, and a version that cannot be traced to the settings
that made it then can never be traced.

- `app.runs.model`: the model the component's client names when the run
  starts, for example `deepseek:deepseek-flash`. In HTTP mode the client names
  the address of the service that chose it, because the orchestrator cannot
  know that service's model.
- `app.runs.thinking`: what the component asked the provider about thinking.
  `disabled` where the request body turns it off, as every component does for
  DeepSeek, whose thinking mode refuses the forced tool calls structured
  answers depend on; `default` where nothing was sent and the provider decides.

Both nullable: null is "not recorded", which is every run before this one, and
a run whose client cannot say.

Revision: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.runs ADD COLUMN model text")
    op.execute("ALTER TABLE app.runs ADD COLUMN thinking text")
    op.execute("""
        COMMENT ON COLUMN app.runs.model IS
        'The model the component client named when the run started. Null: not recorded.'
    """)
    op.execute("""
        COMMENT ON COLUMN app.runs.thinking IS
        'What the component asked about thinking: disabled, or default when it sent '
        'nothing and the provider decided. Null: not recorded.'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE app.runs DROP COLUMN IF EXISTS thinking")
    op.execute("ALTER TABLE app.runs DROP COLUMN IF EXISTS model")
