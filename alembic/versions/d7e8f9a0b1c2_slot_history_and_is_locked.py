"""slot_history table + timetable_slots.is_locked

These two schema objects were created only by `Base.metadata.create_all`
at boot — they existed in no migration. That meant a DB restored purely
from migrations (disaster recovery) would lack them, and undo/redo +
lock/regenerate would 500 with UndefinedColumn / UndefinedTable.

This migration backfills both so Alembic is the single source of truth.
It is written idempotently (IF NOT EXISTS) because the live production DB
already has these objects via create_all — running `alembic upgrade head`
there must be a no-op that simply records this revision.

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-06-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. timetable_slots.is_locked (model: Boolean, default False)
    op.execute(
        "ALTER TABLE timetable_slots "
        "ADD COLUMN IF NOT EXISTS is_locked BOOLEAN DEFAULT FALSE"
    )

    # 2. timetable_slot_history — audit log for manual slot edits (undo/redo)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS timetable_slot_history (
            id                SERIAL PRIMARY KEY,
            solution_id       INTEGER NOT NULL
                                REFERENCES timetable_solutions(id) ON DELETE CASCADE,
            slot_id           INTEGER NOT NULL
                                REFERENCES timetable_slots(id) ON DELETE CASCADE,
            performed_at      TIMESTAMP NOT NULL DEFAULT now(),
            operation         VARCHAR(20) NOT NULL DEFAULT 'move',
            prev_day_of_week  INTEGER,
            prev_period_id    INTEGER,
            prev_classroom_id INTEGER,
            prev_is_locked    BOOLEAN NOT NULL DEFAULT FALSE,
            prev_is_unplaced  BOOLEAN NOT NULL DEFAULT FALSE,
            new_day_of_week   INTEGER,
            new_period_id     INTEGER,
            new_classroom_id  INTEGER,
            new_is_locked     BOOLEAN NOT NULL DEFAULT FALSE,
            new_is_unplaced   BOOLEAN NOT NULL DEFAULT FALSE,
            undone            BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT ck_history_op
                CHECK (operation IN ('move', 'lock', 'unlock', 'place', 'unplace'))
        )
        """
    )
    # FK index (Postgres doesn't auto-index FKs) — undo/redo/summary filter on it.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_slot_history_solution_id "
        "ON timetable_slot_history (solution_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS timetable_slot_history")
    op.execute("ALTER TABLE timetable_slots DROP COLUMN IF EXISTS is_locked")
