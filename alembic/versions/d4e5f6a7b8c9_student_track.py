"""Student.track — κατεύθυνση (ΓΕΛ) ή τομέας (ΕΠΑΛ) του μαθητή.

Additive + idempotent, όπως και το `students.grade` (c3d4e5f6a7b8). Ελεύθερο
VARCHAR ώστε αλλαγή του καταλόγου (backend/services/grade_catalog.py) να μη
χρειάζεται migration ούτε να ακυρώνει παλιές τιμές.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-09 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS track VARCHAR(120)")


def downgrade() -> None:
    op.execute("ALTER TABLE students DROP COLUMN IF EXISTS track")
