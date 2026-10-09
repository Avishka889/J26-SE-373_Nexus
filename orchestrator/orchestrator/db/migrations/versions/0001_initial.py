"""The initial schema.

Three tables carry most of the weight and are worth reading first.

`artefacts` is insert only per version. A node that re-executes (which LangGraph
does on resume, and which the revision loop does deliberately) writes the same
row again rather than a duplicate, so retries are safe and every earlier version
survives for the evaluation.

`design_overlays` holds human edits, applied when the snapshot is read. Editing
the artefact JSONB in place would destroy the record of what the machine
actually produced, and that record is exactly what the ablation measures. It
also makes the human correction rate a metric that costs nothing to collect.

`stage_states` is eight real rows per project rather than something derived from
artefact presence, because presence cannot express `generating` or `failed` and
the display contract has both.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    op.execute("""
        CREATE TABLE app.projects (
            id               text PRIMARY KEY,
            name             text NOT NULL,
            description      text NOT NULL DEFAULT '',
            -- The requirement text going from empty to non empty is what starts
            -- the first run, so it is the input rather than a note about one.
            requirement_text text NOT NULL DEFAULT '',
            files            jsonb NOT NULL DEFAULT '[]'::jsonb,
            -- Proposed and chosen in Code Generation, never in the design phase.
            tech_stack       jsonb NOT NULL DEFAULT '[]'::jsonb,
            color            text NOT NULL DEFAULT '#2563eb',
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now()
        )
    """)
    # status, reqPhase and progress are deliberately absent: they are derived
    # from run and stage state when the project is read. Storing them would let
    # a client PATCH the project into a state the run does not agree with.

    op.execute("""
        CREATE TABLE app.requirement_chat_messages (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            role       text NOT NULL CHECK (role IN ('user','assistant')),
            type       text NOT NULL CHECK (type IN ('source_requirement','chat')),
            content    text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX requirement_chat_by_project "
        "ON app.requirement_chat_messages (project_id, created_at)"
    )

    op.execute("""
        CREATE TABLE app.design_versions (
            project_id text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            version    integer NOT NULL,
            note       text,
            created_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            -- Null means queued: a change note that arrived while a run was in
            -- flight, waiting to be drained at the loop point. Two graphs must
            -- never run on one thread id, so notes wait rather than racing.
            applied_at timestamptz,
            PRIMARY KEY (project_id, version)
        )
    """)

    op.execute("""
        CREATE TABLE app.runs (
            id                   uuid PRIMARY KEY,
            project_id           text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            component            text NOT NULL DEFAULT 'c1',
            requirements_version integer NOT NULL,
            state                text NOT NULL CHECK (state IN
                ('queued','running','awaiting_gate','done','failed','superseded')),
            -- Written before the graph is resumed, so a crash between the HTTP
            -- response and the resume does not lose the decision.
            resume_payload       jsonb,
            heartbeat_at         timestamptz,
            started_at           timestamptz NOT NULL DEFAULT now(),
            finished_at          timestamptz,
            error                text
        )
    """)
    # The run id is also the LangGraph thread id, which is what lets a gate
    # opened before a restart resume on exactly the same thread.
    op.execute("CREATE INDEX runs_by_project ON app.runs (project_id, started_at DESC)")
    op.execute("CREATE INDEX runs_claimable ON app.runs (state, heartbeat_at)")

    op.execute("""
        CREATE TABLE app.artefacts (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id     text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            kind           text NOT NULL CHECK (kind IN (
                'requirements','architecture-graph','architecture-recommendation',
                'uml-diagrams','wireframes','sprint-plan')),
            version        integer NOT NULL,
            run_id         uuid REFERENCES app.runs(id) ON DELETE SET NULL,
            schema_version text NOT NULL DEFAULT '0.1.0',
            body           jsonb NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (project_id, kind, version)
        )
    """)
    # The read path takes the latest of each kind, so this index is what makes
    # composing a snapshot one index scan rather than six queries.
    op.execute("CREATE INDEX artefacts_latest ON app.artefacts (project_id, kind, version DESC)")

    op.execute("""
        CREATE TABLE app.stage_states (
            project_id             text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            stage_id               text NOT NULL,
            status                 text NOT NULL DEFAULT 'pending'
                                   CHECK (status IN ('pending','generating','complete','failed')),
            generated_from_version integer NOT NULL DEFAULT 0,
            generated_at           timestamptz,
            summary                text,
            error                  text,
            PRIMARY KEY (project_id, stage_id)
        )
    """)

    op.execute("""
        CREATE TABLE app.design_overlays (
            project_id text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            version    integer NOT NULL,
            kind       text NOT NULL CHECK (kind IN (
                'requirement_text','assumption_text','assumption_dismissed',
                'question_answer','node_label','flow_refinement','architecture_selection')),
            target_id  text NOT NULL,
            value      jsonb NOT NULL,
            by         text NOT NULL,
            at         timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, version, kind, target_id)
        )
    """)

    op.execute("""
        CREATE TABLE app.gates (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id               uuid NOT NULL REFERENCES app.runs(id) ON DELETE CASCADE,
            project_id           text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            kind                 text NOT NULL DEFAULT 'c1-design-review',
            requirements_version integer NOT NULL,
            state                text NOT NULL DEFAULT 'pending'
                                 CHECK (state IN ('pending','resolved')),
            -- LangGraph keys a resume by interrupt id once more than one is
            -- pending. C1 has a single gate, but C2 to C4 will not, and a
            -- column now is cheaper than a migration later.
            interrupt_id         text,
            payload              jsonb NOT NULL DEFAULT '{}'::jsonb,
            decision             text CHECK (decision IN ('approved','changes')),
            decided_by           text,
            decided_at           timestamptz,
            note                 text,
            created_at           timestamptz NOT NULL DEFAULT now()
        )
    """)
    # At most one gate may be pending per project, which is the invariant that
    # keeps "the pending gate" an unambiguous phrase in the read model.
    op.execute(
        "CREATE UNIQUE INDEX one_pending_gate_per_project "
        "ON app.gates (project_id) WHERE state = 'pending'"
    )

    op.execute("""
        CREATE TABLE app.thread_messages (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id text NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
            seq        bigserial NOT NULL,
            kind       text NOT NULL CHECK (kind IN
                       ('user_note','answer','stage_summary','system')),
            stage_id   text,
            author     text NOT NULL,
            content    text NOT NULL,
            at         timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX thread_by_project ON app.thread_messages (project_id, seq)")

    op.execute("""
        CREATE TABLE app.audit_events (
            id         bigserial PRIMARY KEY,
            project_id text REFERENCES app.projects(id) ON DELETE CASCADE,
            run_id     uuid REFERENCES app.runs(id) ON DELETE SET NULL,
            actor      text NOT NULL,
            action     text NOT NULL,
            target     text NOT NULL,
            category   text NOT NULL DEFAULT 'design',
            detail     text NOT NULL DEFAULT '',
            payload    jsonb NOT NULL DEFAULT '{}'::jsonb,
            at         timestamptz NOT NULL DEFAULT now()
        )
    """)
    # Activity is a view over this, not a fifth phase, so it is read globally as
    # well as per project.
    op.execute("CREATE INDEX audit_by_time ON app.audit_events (at DESC)")
    op.execute("CREATE INDEX audit_by_project ON app.audit_events (project_id, at DESC)")

    op.execute("""
        CREATE TABLE app.settings (
            id   text PRIMARY KEY DEFAULT 'default',
            body jsonb NOT NULL DEFAULT '{}'::jsonb
        )
    """)

    op.execute("""
        CREATE TABLE app.secrets (
            key        text PRIMARY KEY,
            -- Encrypted at rest and never returned in a response body. The
            -- browser sees status, scopes and last used, never a token.
            ciphertext bytea NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    for table in (
        "secrets",
        "settings",
        "audit_events",
        "thread_messages",
        "gates",
        "design_overlays",
        "stage_states",
        "artefacts",
        "runs",
        "design_versions",
        "requirement_chat_messages",
        "projects",
    ):
        op.execute(f"DROP TABLE IF EXISTS app.{table} CASCADE")
