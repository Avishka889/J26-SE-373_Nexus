"""A release kept after a declined rollback, unverified, as a state of its own.

Declining the rollback of a release that failed after its traffic moved marked
it `failed`. Everywhere else `failed` means the traffic never moved, so the
platform took the release before it as the one serving (review item C4-5).

- `app.deployments.state` may be `kept-unverified`: a person declined to roll it
  back, it serves, and nothing verified it.

Revision: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_BEFORE = (
    "'pending','running','succeeded','compensated','failed',"
    "'awaiting-rollback-approval','rolled-back'"
)


def _check(states: str) -> None:
    op.execute("ALTER TABLE app.deployments DROP CONSTRAINT deployments_state_check")
    op.execute(
        f"ALTER TABLE app.deployments ADD CONSTRAINT deployments_state_check "
        f"CHECK (state IN ({states}))"
    )


def upgrade() -> None:
    _check(_BEFORE + ",'kept-unverified'")


def downgrade() -> None:
    op.execute("UPDATE app.deployments SET state = 'failed' WHERE state = 'kept-unverified'")
    _check(_BEFORE)
