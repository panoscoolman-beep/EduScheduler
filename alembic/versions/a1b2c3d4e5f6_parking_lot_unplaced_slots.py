"""parking_lot_unplaced_slots

Phase 2 of the solver overhaul — make TimetableSlot represent both
placed lessons (the schedule grid) and unplaced lessons (the parking
lot panel). The user can drag from parking → grid manually when the
solver couldn't fit everything.

Schema changes:
  - day_of_week, period_id, classroom_id become NULLable
  - new column is_unplaced BOOLEAN NOT NULL DEFAULT FALSE
  - new column unplaced_reason VARCHAR(500) NULLable
  - drop old ck_slot_day_range, re-add tolerating NULL
  - add ck_slot_placement_consistent: either all 3 placement cols are
    NULL with is_unplaced=TRUE, or all 3 are NOT NULL with
    is_unplaced=FALSE

Revision ID: a1b2c3d4e5f6
Revises: 377b9423f40e
Create Date: 2026-05-07 02:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "377b9423f40e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop old check constraint that forbids NULL day_of_week
    op.drop_constraint("ck_slot_day_range", "timetable_slots", type_="check")

    # 2. Make placement columns nullable
    op.alter_column("timetable_slots", "day_of_week", nullable=True)
    op.alter_column("timetable_slots", "period_id", nullable=True)
    op.alter_column("timetable_slots", "classroom_id", nullable=True)

    # 3. New columns
    op.add_column(
        "timetable_slots",
        sa.Column("is_unplaced", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "timetable_slots",
        sa.Column("unplaced_reason", sa.String(length=500), nullable=True),
    )

    # 4. Re-add the day-range check tolerating NULL
    op.create_check_constraint(
        "ck_slot_day_range",
        "timetable_slots",
        "day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)",
    )

    # 5. Consistency: placed → all three cols set, unplaced → all NULL
    op.create_check_constraint(
        "ck_slot_placement_consistent",
        "timetable_slots",
        "(is_unplaced = TRUE AND day_of_week IS NULL AND period_id IS NULL AND classroom_id IS NULL)"
        " OR (is_unplaced = FALSE AND day_of_week IS NOT NULL AND period_id IS NOT NULL AND classroom_id IS NOT NULL)",
    )


def downgrade() -> None:
    # Reverse order. We'll lose any unplaced rows — caller's responsibility.
    op.execute("DELETE FROM timetable_slots WHERE is_unplaced = TRUE")

    op.drop_constraint("ck_slot_placement_consistent", "timetable_slots", type_="check")
    op.drop_constraint("ck_slot_day_range", "timetable_slots", type_="check")

    op.drop_column("timetable_slots", "unplaced_reason")
    op.drop_column("timetable_slots", "is_unplaced")

    op.alter_column("timetable_slots", "classroom_id", nullable=False)
    op.alter_column("timetable_slots", "period_id", nullable=False)
    op.alter_column("timetable_slots", "day_of_week", nullable=False)

    op.create_check_constraint(
        "ck_slot_day_range",
        "timetable_slots",
        "day_of_week >= 0 AND day_of_week <= 6",
    )
