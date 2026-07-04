"""Term start/end dates — όρια σεναρίου για ICS export (UNTIL) και εμφάνιση.

Καθαρά ADDITIVE: δύο nullable DATE στήλες στο terms. Κανένα υπάρχον
δεδομένο δεν αλλάζει/χάνεται — τα σενάρια χωρίς dates συμπεριφέρονται
όπως πριν (ICS χωρίς UNTIL/EXDATE). Idempotent (IF NOT EXISTS).

Revision ID: b2c3d4e5f6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-04 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE terms ADD COLUMN IF NOT EXISTS start_date DATE")
    op.execute("ALTER TABLE terms ADD COLUMN IF NOT EXISTS end_date DATE")


def downgrade() -> None:
    op.execute("ALTER TABLE terms DROP COLUMN IF EXISTS start_date")
    op.execute("ALTER TABLE terms DROP COLUMN IF EXISTS end_date")
