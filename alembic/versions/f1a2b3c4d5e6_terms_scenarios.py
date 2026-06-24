"""Terms / scenarios — scope lessons, availability, solutions per scenario

Adds a `terms` table and a term_id FK to lessons, teacher_availability,
student_availability, timetable_solutions. Backfills ALL existing rows to a
default term ("Τρέχον πρόγραμμα", is_active=TRUE) so NO existing data/program
is lost or changed — they all live under that default scenario.

Availability unique constraints are widened to include term_id so the same
teacher/student day+period can exist in different scenarios (needed for clone).

Idempotent (IF NOT EXISTS / guarded) so it's safe to re-run on the live DB.

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
Create Date: 2026-06-24 22:30:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCOPED = ["lessons", "teacher_availability", "student_availability", "timetable_solutions"]


def upgrade() -> None:
    # 1) terms table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS terms (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            short_name VARCHAR(20),
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            notes TEXT,
            created_at TIMESTAMP
        )
        """
    )

    # 2) default term — only if empty (preserves & adopts all existing data)
    op.execute(
        """
        INSERT INTO terms (name, short_name, is_active, created_at)
        SELECT 'Τρέχον πρόγραμμα', 'ΤΡΕΧ', TRUE, (now() AT TIME ZONE 'utc')
        WHERE NOT EXISTS (SELECT 1 FROM terms)
        """
    )

    # 3) add term_id to each scoped table → backfill → FK → index → NOT NULL
    for table in _SCOPED:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS term_id INTEGER")
        op.execute(
            f"""
            UPDATE {table}
               SET term_id = (SELECT id FROM terms ORDER BY is_active DESC, id ASC LIMIT 1)
             WHERE term_id IS NULL
            """
        )
        op.execute(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_{table}_term') THEN
                    ALTER TABLE {table}
                        ADD CONSTRAINT fk_{table}_term
                        FOREIGN KEY (term_id) REFERENCES terms(id) ON DELETE CASCADE;
                END IF;
            END $$;
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_term_id ON {table} (term_id)")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN term_id SET NOT NULL")

    # 4) widen availability unique constraints to include term_id
    op.execute("ALTER TABLE teacher_availability DROP CONSTRAINT IF EXISTS uq_teacher_day_period")
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_teacher_term_day_period') THEN
                ALTER TABLE teacher_availability
                    ADD CONSTRAINT uq_teacher_term_day_period
                    UNIQUE (term_id, teacher_id, day_of_week, period_id);
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE student_availability DROP CONSTRAINT IF EXISTS uq_student_day_period")
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_student_term_day_period') THEN
                ALTER TABLE student_availability
                    ADD CONSTRAINT uq_student_term_day_period
                    UNIQUE (term_id, student_id, day_of_week, period_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE teacher_availability DROP CONSTRAINT IF EXISTS uq_teacher_term_day_period")
    op.execute("ALTER TABLE student_availability DROP CONSTRAINT IF EXISTS uq_student_term_day_period")
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_teacher_day_period') THEN
                ALTER TABLE teacher_availability
                    ADD CONSTRAINT uq_teacher_day_period UNIQUE (teacher_id, day_of_week, period_id);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_student_day_period') THEN
                ALTER TABLE student_availability
                    ADD CONSTRAINT uq_student_day_period UNIQUE (student_id, day_of_week, period_id);
            END IF;
        END $$;
        """
    )
    for table in _SCOPED:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS fk_{table}_term")
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_term_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS term_id")
    op.execute("DROP TABLE IF EXISTS terms")
