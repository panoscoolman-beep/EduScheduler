"""FK indexes on hot query paths

Postgres does not auto-index foreign keys. The hottest filters in the app
run on un-indexed FKs — most notably solver_status (polled every 3s during
a multi-minute solve) counts over timetable_slots.solution_id, and every
undo/redo/summary filters timetable_slot_history.solution_id. Add btree
indexes so those become index scans instead of sequential scans.

Idempotent (IF NOT EXISTS) so it's safe on the live DB.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-06-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = [
    ("ix_slots_solution_id", "timetable_slots", "solution_id"),
    ("ix_slots_lesson_id", "timetable_slots", "lesson_id"),
    ("ix_slots_classroom_id", "timetable_slots", "classroom_id"),
    ("ix_slots_period_id", "timetable_slots", "period_id"),
    ("ix_slot_history_slot_id", "timetable_slot_history", "slot_id"),
    ("ix_lessons_teacher_id", "lessons", "teacher_id"),
    ("ix_lessons_class_id", "lessons", "class_id"),
    ("ix_lessons_subject_id", "lessons", "subject_id"),
    ("ix_enroll_class_id", "student_class_enrollments", "class_id"),
    ("ix_enroll_student_id", "student_class_enrollments", "student_id"),
    ("ix_teacher_avail_teacher_id", "teacher_availability", "teacher_id"),
    ("ix_student_avail_student_id", "student_availability", "student_id"),
]


def upgrade() -> None:
    for name, table, col in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})")


def downgrade() -> None:
    for name, _table, _col in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
