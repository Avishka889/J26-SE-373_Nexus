"""Deployment files are keyed by the stage that wrote them.

0011 keyed `app.deploy_files` by project, version and path, while its own
comment says each stage owns its files. Two stages write the same path at one
deploy version: detection keeps the baseline `package-lock.json` it pinned, and
pipeline generation writes the candidate's `package-lock.json`, the baseline
with the included updates applied. Under 0011's key the second write did not
fail: its upsert took the first stage's row over, so the baseline would have
been replaced by the candidate's lockfile and relabelled as the pipeline
stage's. The key now includes the stage, every read names the stage it wants,
and a release commits the pipeline stage's files only.

Revision: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.deploy_files DROP CONSTRAINT deploy_files_pkey")
    op.execute("ALTER TABLE app.deploy_files ADD PRIMARY KEY (project_id, version, stage_id, path)")


def downgrade() -> None:
    # One row per path again: where two stages hold a path, the pipeline stage's
    # copy is the one that goes, since the analysis read the other.
    op.execute(
        """
        DELETE FROM app.deploy_files AS later USING app.deploy_files AS earlier
        WHERE later.project_id = earlier.project_id
          AND later.version = earlier.version
          AND later.path = earlier.path
          AND later.stage_id = 'pipeline-generation'
          AND earlier.stage_id <> 'pipeline-generation'
        """
    )
    op.execute("ALTER TABLE app.deploy_files DROP CONSTRAINT deploy_files_pkey")
    op.execute("ALTER TABLE app.deploy_files ADD PRIMARY KEY (project_id, version, path)")
