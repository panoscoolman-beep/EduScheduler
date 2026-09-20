"""👥 Μαθητές ανά κάρτα μαθήματος (lesson_student_overrides)

Additive: νέος πίνακας. Χωρίς εγγραφές, η συμπεριφορά μένει ακριβώς ίδια
(τη λίστα τη δίνει το τμήμα).

Revision ID: a7b3e2d9c4f1
Revises: f3a9c1d7e5b2
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a7b3e2d9c4f1"
down_revision: Union[str, None] = "f3a9c1d7e5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS lesson_student_overrides (
            id SERIAL PRIMARY KEY,
            lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            mode VARCHAR(10) NOT NULL,
            CONSTRAINT uq_lesson_student_override UNIQUE (lesson_id, student_id),
            CONSTRAINT ck_override_mode CHECK (mode IN ('add', 'remove'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_lesson_student_overrides_lesson_id "
               "ON lesson_student_overrides (lesson_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_lesson_student_overrides_student_id "
               "ON lesson_student_overrides (student_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lesson_student_overrides")
