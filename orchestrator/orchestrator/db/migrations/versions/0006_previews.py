"""Remember the preview processes this orchestrator started.

A preview is a real operating system process serving generated code on a real
port, and it outlives the request that started it. If the orchestrator is
killed hard, that process keeps running and keeps the port: nothing left in
memory can find it again, and the next start collides or leaks. One row per
project is what makes a restarting orchestrator able to reap what the previous
one left behind.

One per project by construction, because the primary key says so: a preview is
of a project's current code version, and two of them would be two answers to
one question.

Revision: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.previews (
            project_id   text PRIMARY KEY REFERENCES app.projects(id) ON DELETE CASCADE,
            code_version integer NOT NULL,
            port         integer NOT NULL,
            -- The process group leader. Killing the group is what stops the
            -- server rather than only the wrapper that spawned it.
            pid          integer NOT NULL,
            -- The tree being served. The preview owns it and deletes it when
            -- it stops, which is how the build directories stopped leaking.
            workdir      text NOT NULL,
            status       text NOT NULL
                         CHECK (status IN ('starting','running','failed','stopped')),
            -- Why it is not running, in words, when it is not running.
            error        text,
            started_at   timestamptz NOT NULL DEFAULT now(),
            -- Bumped whenever somebody reads it, so an idle preview can be
            -- reclaimed without guessing whether anyone is still looking.
            last_seen_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.previews")
