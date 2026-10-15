"""Store the generated source, and admit the sprint scope as an artefact.

Two things a code run needs that a design run never did.

`code_files` holds the generated monorepo. It is a table rather than a column
on the code-repository artefact because three separate nodes write it and a
fourth reads it back: the frontend and backend stages each add their files, the
agreement stage parses all of them, and the build stage runs them. An artefact
body is one JSONB document read whole, which would mean loading every source
file to serve one, and the browser polls the snapshot every 1.2 seconds. The
manifest on the artefact stays the record of what exists; this is where the
bytes live.

`sprint-scope` joins the artefact kinds because the scope is stored rather than
recomputed: deriving it lives in C2, the orchestrator must not import a
component it may be reaching over HTTP, and a scope recomputed from the sprint
plan would discard the human's in and out decisions.

Revision: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ARTEFACT_KINDS = (
    # C1
    "requirements",
    "architecture-graph",
    "architecture-recommendation",
    "uml-diagrams",
    "wireframes",
    "sprint-plan",
    # C2
    "sprint-scope",
    "tech-stack",
    "api-contract",
    "contract-agreement",
    "code-repository",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute("ALTER TABLE app.artefacts DROP CONSTRAINT artefacts_kind_check")
    op.execute(
        f"ALTER TABLE app.artefacts ADD CONSTRAINT artefacts_kind_check "
        f"CHECK (kind IN ({_quoted(ARTEFACT_KINDS)}))"
    )
    op.execute("""
        CREATE TABLE app.code_files (
            project_id text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            -- The code axis version, not the design one.
            version    integer NOT NULL,
            path       text NOT NULL,
            content    text NOT NULL,
            -- Which stage wrote it, so a regeneration of one stage replaces
            -- exactly its own files instead of leaving orphans the manifest
            -- does not list.
            stage_id   text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, version, path)
        )
    """)
    op.execute("CREATE INDEX code_files_by_stage ON app.code_files (project_id, version, stage_id)")


def downgrade() -> None:
    op.execute("DROP TABLE app.code_files")
    op.execute("ALTER TABLE app.artefacts DROP CONSTRAINT artefacts_kind_check")
    op.execute(
        f"ALTER TABLE app.artefacts ADD CONSTRAINT artefacts_kind_check "
        f"CHECK (kind IN ({_quoted(tuple(k for k in ARTEFACT_KINDS if k != 'sprint-scope'))}))"
    )
