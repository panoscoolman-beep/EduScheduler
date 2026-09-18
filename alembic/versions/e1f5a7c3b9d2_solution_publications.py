"""📢 Δημοσιεύσεις προγράμματος (solution_publications)

Additive: νέος πίνακας, κανένα υπάρχον δεδομένο δεν αγγίζεται.

Revision ID: e1f5a7c3b9d2
Revises: b4c5d6e7f8a9
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e1f5a7c3b9d2"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS solution_publications (
            id SERIAL PRIMARY KEY,
            term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
            solution_id INTEGER REFERENCES timetable_solutions(id) ON DELETE SET NULL,
            solution_name VARCHAR(200) NOT NULL,
            published_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            note TEXT,
            snapshot_json TEXT NOT NULL,
            messages_json TEXT NOT NULL,
            notify_telegram BOOLEAN NOT NULL DEFAULT FALSE,
            telegram_sent_at TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_solution_publications_term_id "
               "ON solution_publications (term_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS solution_publications")
