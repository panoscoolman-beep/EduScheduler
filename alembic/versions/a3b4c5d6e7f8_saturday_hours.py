"""Ωράριο Σαββάτου (school_settings.saturday_from / saturday_to)

Additive + idempotent. Το Σάββατο το φροντιστήριο δουλεύει και πρωί, ενώ
Δευτέρα–Παρασκευή μόνο απόγευμα: με ξεχωριστό ωράριο τα πρωινά κελιά των
καθημερινών φαίνονται «κλειστά» χωρίς να κρύβονται τα μαθήματα του Σαββάτου.
Κενό = ίδιο με τις καθημερινές.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE school_settings ADD COLUMN IF NOT EXISTS saturday_from VARCHAR(5)")
    op.execute("ALTER TABLE school_settings ADD COLUMN IF NOT EXISTS saturday_to VARCHAR(5)")


def downgrade() -> None:
    op.execute("ALTER TABLE school_settings DROP COLUMN IF EXISTS saturday_to")
    op.execute("ALTER TABLE school_settings DROP COLUMN IF EXISTS saturday_from")
