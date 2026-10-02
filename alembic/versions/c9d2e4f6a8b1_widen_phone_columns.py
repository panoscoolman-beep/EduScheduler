"""Τηλέφωνα 30 → 100 χαρακτήρες (students.phone, teachers.phone)

Το CRM δέχεται τηλέφωνο έως 100 (μαθητές) / 50 (καθηγητές) χαρακτήρες· εδώ η
στήλη ήταν VARCHAR(30), οπότε ένα μεγαλύτερο τηλέφωνο έβγαζε 500 στη φόρμα
και στη μαζική «Εισαγωγή από CRM» έριχνε όλη την παρτίδα.

ΜΟΝΟ ΔΙΕΥΡΥΝΣΗ: αλλάζει μια στήλη μόνο αν είναι VARCHAR με όριο < 100
(idempotent — δεύτερη εκτέλεση = καμία αλλαγή· ποτέ στένεμα). Στο Postgres η
διεύρυνση varchar είναι αλλαγή μεταδεδομένων, χωρίς rewrite του πίνακα.
downgrade = no-op: το στένεμα θα μπορούσε να χάσει/απορρίψει δεδομένα.

Revision ID: c9d2e4f6a8b1
Revises: a7b3e2d9c4f1
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c9d2e4f6a8b1"
down_revision: Union[str, None] = "a7b3e2d9c4f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WIDEN = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = '{table}' AND column_name = 'phone'
          AND data_type = 'character varying'
          AND character_maximum_length < 100
    ) THEN
        ALTER TABLE {table} ALTER COLUMN phone TYPE VARCHAR(100);
    END IF;
END $$;
"""


def upgrade() -> None:
    for table in ("students", "teachers"):
        op.execute(_WIDEN.format(table=table))


def downgrade() -> None:
    # Σκόπιμα κενό: στένεμα σε VARCHAR(30) θα απέρριπτε/έκοβε υπάρχοντα τηλέφωνα.
    pass
