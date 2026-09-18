"""Ωράριο λειτουργίας (school_settings.visible_from / visible_to)

Additive + idempotent: δύο nullable στήλες «HH:MM». Κενές = όλες οι ώρες
εμφανίζονται (η συμπεριφορά μέχρι σήμερα). Αφορούν μόνο την εμφάνιση.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE school_settings ADD COLUMN IF NOT EXISTS visible_from VARCHAR(5)")
    op.execute("ALTER TABLE school_settings ADD COLUMN IF NOT EXISTS visible_to VARCHAR(5)")


def downgrade() -> None:
    op.execute("ALTER TABLE school_settings DROP COLUMN IF EXISTS visible_to")
    op.execute("ALTER TABLE school_settings DROP COLUMN IF EXISTS visible_from")
