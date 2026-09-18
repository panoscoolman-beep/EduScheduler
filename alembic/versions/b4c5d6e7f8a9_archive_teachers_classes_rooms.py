"""Αρχειοθέτηση καθηγητών, τμημάτων, αιθουσών (archived_at)

Additive + idempotent. Αρχειοθετημένη οντότητα: κρυφή από τις λίστες, δεν
προτείνεται σε νέες τοποθετήσεις/solver· τα παλιά προγράμματα μένουν ακέραια.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("teachers", "classes", "classrooms")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS archived_at")
