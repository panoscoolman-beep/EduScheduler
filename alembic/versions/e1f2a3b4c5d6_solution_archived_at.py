"""Αρχειοθέτηση προγράμματος (timetable_solutions.archived_at)

Additive + idempotent: μία nullable στήλη. Ένα αρχειοθετημένο πρόγραμμα μένει
ακέραιο (slots, ιστορικό) αλλά βγαίνει από τη λίστα και από τον parking-lot
sync, ώστε να μη «κρατά» ώρες στην Παλέτα. Αναστρέψιμο από το UI.

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE timetable_solutions ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE timetable_solutions DROP COLUMN IF EXISTS archived_at")
