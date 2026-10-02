"""🧹 «nan» στα email/τηλέφωνα μαθητών & καθηγητών → κενό (με μόνιμο ίχνος)

Ένα bug του CRM (pandas NaN → κείμενο «nan») έγραψε «nan» σε κενά στοιχεία
επικοινωνίας, που ήρθαν εδώ με τον συγχρονισμό CRM→EDS και με την «Εισαγωγή
από CRM». Το CRM δεν μπορεί να τα καθαρίσει (εκεί None = «μην αγγίξεις»).

Τι κάνει:
  • students.email/phone, teachers.email/phone με lower(btrim(τιμή)) = 'nan'
    → NULL (όλες nullable στο σχήμα). ΜΟΝΟ ακριβές ταίριασμα: «Nancy»,
    «banana», «nan2» μένουν. Ονόματα και κάθε άλλη στήλη: ανέγγιχτα.
  • ΠΡΙΝ από κάθε UPDATE γράφει μία γραμμή ανά πεδίο στο `data_cleanup_log`
    (πίνακας, id, στήλη, παλιά τιμή, αιτία, πότε) — το EduScheduler δεν έχει
    αυτόματο backup πριν από migration (μόνο τα ωριαία του host).

Idempotent: δεύτερη εκτέλεση = τίποτα (δεν έχει μείνει «nan»· ο πίνακας
δημιουργείται IF NOT EXISTS).

Revision ID: d1e3f5a7b9c2
Revises: c9d2e4f6a8b1
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d1e3f5a7b9c2"
down_revision: Union[str, None] = "c9d2e4f6a8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REASON = "«nan» από το CRM (pandas NaN) → κενό"
TARGETS = (("students", "email"), ("students", "phone"),
           ("teachers", "email"), ("teachers", "phone"))


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS data_cleanup_log (
            id SERIAL PRIMARY KEY,
            table_name VARCHAR(64) NOT NULL,
            row_id INTEGER NOT NULL,
            column_name VARCHAR(64) NOT NULL,
            old_value TEXT,
            reason VARCHAR(200) NOT NULL,
            cleaned_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
        )
    """)
    for table, column in TARGETS:
        # Πρώτα το ίχνος, μετά η αλλαγή — στην ίδια συναλλαγή του alembic.
        op.execute(f"""
            INSERT INTO data_cleanup_log (table_name, row_id, column_name, old_value, reason)
            SELECT '{table}', id, '{column}', {column}, '{REASON}'
            FROM {table}
            WHERE lower(btrim({column})) = 'nan'
        """)
        op.execute(f"UPDATE {table} SET {column} = NULL WHERE lower(btrim({column})) = 'nan'")


def downgrade() -> None:
    # Σκόπιμα κενό. Ο `data_cleanup_log` ΔΕΝ σβήνεται: κρατά τις παλιές τιμές
    # (το μόνο ίχνος του καθαρισμού). Ούτε ξαναγράφεται «nan» — ήταν σκουπίδι.
    pass
