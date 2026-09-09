"""Student.grade — η τάξη του μαθητή (Α΄ Λυκείου, Β΄ Γυμνασίου, ...).

Καθαρά ADDITIVE: μία nullable VARCHAR στήλη στο students. Το EduScheduler
δεν είχε πουθενά την τάξη — τα `classes` είναι ΤΜΗΜΑΤΑ (ονομασμένα με τα
ονόματα των παιδιών) και το `classes.grade_level` είναι NULL σε όλα.
Ελεύθερο κείμενο (όχι enum) ώστε να χωρά ΕΠΑΛ/ειδικότητες χωρίς migration.
Idempotent (IF NOT EXISTS).

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-09 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS grade VARCHAR(60)")


def downgrade() -> None:
    op.execute("ALTER TABLE students DROP COLUMN IF EXISTS grade")
