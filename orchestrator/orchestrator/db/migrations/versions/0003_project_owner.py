"""Give every project an owner.

Projects belong to somebody. Nothing said so, so every project was visible to
every caller, and the day a second person uses this the fix is a backfill across
live data rather than a column.

The column lands now and the login lands later, deliberately. Adding `owner_id`
to an empty-ish table is a migration; adding it once designs exist means deciding
retrospectively who owns work nobody claimed. Scoping the queries now also means
the scoping is written and reviewed while there is one user to get it wrong for,
rather than under the pressure of shipping sign-in.

`app.users` holds the one development identity until sign-in exists. A real row
rather than a bare text column, because a foreign key is what stops a typo in a
session becoming a project nobody can see and nobody can delete.

Three steps, in this order, because the column cannot be NOT NULL before the
rows it points at exist: create the table and its first row, add the column
nullable and backfill, then tighten it.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None

#: The single identity every existing project is assigned to, and the one the
#: orchestrator acts as until sign-in exists. A fixed id rather than a generated
#: one, so the application can name it without reading it back first.
DEV_USER_ID = "u_local_dev"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.users (
            id         text PRIMARY KEY,
            email      text NOT NULL UNIQUE,
            name       text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(f"""
        INSERT INTO app.users (id, email, name)
        VALUES ('{DEV_USER_ID}', 'dev@localhost', 'Local development')
        ON CONFLICT (id) DO NOTHING
    """)

    op.execute("ALTER TABLE app.projects ADD COLUMN owner_id text")
    op.execute(f"UPDATE app.projects SET owner_id = '{DEV_USER_ID}' WHERE owner_id IS NULL")
    op.execute("""
        ALTER TABLE app.projects
        ALTER COLUMN owner_id SET NOT NULL,
        ADD CONSTRAINT projects_owner_fk
            FOREIGN KEY (owner_id) REFERENCES app.users(id) ON DELETE RESTRICT
    """)
    # Every project query filters on it, so it is worth an index from the start
    # rather than after the first slow list.
    op.execute("CREATE INDEX projects_owner_idx ON app.projects (owner_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.projects_owner_idx")
    op.execute("ALTER TABLE app.projects DROP CONSTRAINT IF EXISTS projects_owner_fk")
    op.execute("ALTER TABLE app.projects DROP COLUMN IF EXISTS owner_id")
    op.execute("DROP TABLE IF EXISTS app.users")
