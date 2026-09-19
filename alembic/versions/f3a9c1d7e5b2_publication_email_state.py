"""📢 Δημοσίευση: κατάσταση αποστολής email (solution_publications.email_state)

Additive + idempotent.

Revision ID: f3a9c1d7e5b2
Revises: e1f5a7c3b9d2
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f3a9c1d7e5b2"
down_revision: Union[str, None] = "e1f5a7c3b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE solution_publications ADD COLUMN IF NOT EXISTS email_state VARCHAR(20)")


def downgrade() -> None:
    op.execute("ALTER TABLE solution_publications DROP COLUMN IF EXISTS email_state")
