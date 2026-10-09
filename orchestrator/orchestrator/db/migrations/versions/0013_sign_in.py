"""Sign-in: a password per account, a session per signed-in browser, and an
owner on every audit entry.

`app.users` has held one development identity since 0003, the owner every
project and setting was written for. Sign-in adds what an account needs to
prove who it is, and nothing that exists changes meaning: the first account
registered adopts that identity, so the projects made before sign-in stay with
the person who made them.

- `app.users.password_hash`: an Argon2 hash, null until the account registers,
  which is how the first registration finds the identity it adopts. Emails are
  unique regardless of case, since a person types theirs both ways.
- `app.sessions`: one row per signed-in browser. The cookie carries a random
  token and only its SHA-256 is stored, so a copy of the table signs nobody in.
- `app.audit_events.owner_id`: whose entry it is. With one identity the audit
  log needed no owner; with several, `/audit` and `/activity` returned every
  owner's events. Entries with a project take its owner, and the few without
  one (settings and connections) were written by the only identity there was.

Revision: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

#: The identity every row before sign-in belongs to (0003).
DEV_USER_ID = "u_local_dev"


def upgrade() -> None:
    op.execute("ALTER TABLE app.users ADD COLUMN password_hash text")
    op.execute("CREATE UNIQUE INDEX users_email_lower_idx ON app.users (lower(email))")
    op.execute("""
        CREATE TABLE app.sessions (
            token_hash text PRIMARY KEY,
            user_id    text NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX sessions_user_idx ON app.sessions (user_id)")

    # Plain text, as `app.settings` and `app.secrets` are keyed: an audit log
    # outlives what it describes, so deleting an account must not erase it.
    op.execute("ALTER TABLE app.audit_events ADD COLUMN owner_id text")
    op.execute("""
        UPDATE app.audit_events AS entry
        SET owner_id = project.owner_id
        FROM app.projects AS project
        WHERE entry.project_id = project.id
    """)
    op.execute(f"UPDATE app.audit_events SET owner_id = '{DEV_USER_ID}' WHERE owner_id IS NULL")
    op.execute("CREATE INDEX audit_events_owner_idx ON app.audit_events (owner_id, at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.audit_events_owner_idx")
    op.execute("ALTER TABLE app.audit_events DROP COLUMN IF EXISTS owner_id")
    op.execute("DROP TABLE IF EXISTS app.sessions")
    op.execute("DROP INDEX IF EXISTS app.users_email_lower_idx")
    op.execute("ALTER TABLE app.users DROP COLUMN IF EXISTS password_hash")
