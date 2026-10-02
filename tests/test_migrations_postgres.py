"""Alembic σε ΑΛΗΘΙΝΟ Postgres: τηλέφωνα 30 → 100 (c9d2e4f6a8b1) και
καθάρισμα «nan» με μόνιμο ίχνος (d1e3f5a7b9c2).

Τρέχει μόνο αν δοθεί URL για Postgres μιας χρήσης (χρήστης με CREATEDB), π.χ.
    EDS_TEST_POSTGRES_ADMIN_URL=postgresql://postgres@127.0.0.1:55432/postgres
(ή το EDS_TEST_POSTGRES_URL των άλλων PG tests). Φτιάχνει ΔΙΚΗ του βάση και
τη σβήνει στο τέλος. Χωρίς μεταβλητή (CI): skip.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

ADMIN_URL = (os.environ.get("EDS_TEST_POSTGRES_ADMIN_URL")
             or os.environ.get("EDS_TEST_POSTGRES_URL"))
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="χρειάζεται EDS_TEST_POSTGRES_ADMIN_URL")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def pg(monkeypatch):
    psycopg2 = pytest.importorskip("psycopg2")
    from alembic.config import Config

    name = f"eds_mig_test_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(ADMIN_URL)
    admin.autocommit = True
    admin.cursor().execute(f"CREATE DATABASE {name}")
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    monkeypatch.setenv("DATABASE_URL", url)
    # Χωρίς alembic.ini: αλλιώς το env.py κάνει fileConfig() και «σβήνει» τους
    # loggers των επόμενων tests. Το URL το δίνει το DATABASE_URL (env.py).
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    conn = psycopg2.connect(url)
    conn.autocommit = True

    def q(sql, *args):
        cur = conn.cursor()
        cur.execute(sql, args)
        return cur.fetchall() if cur.description else None

    yield cfg, q
    conn.close()
    admin.cursor().execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    admin.close()


def test_phone_widening_and_nan_cleanup_on_postgres(pg):
    from alembic import command

    cfg, q = pg
    command.upgrade(cfg, "a7b3e2d9c4f1")                    # η βάση όπως ήταν πριν
    q("INSERT INTO students (first_name, last_name, email, phone) VALUES "
      "('Nan', 'Nancy', 'nan', 'NaN'), ('Άννα', 'Χ', ' NAN ', '6971234567'), "
      "('Γιώργος', 'Π', 'Nancy@x.gr', 'nan2'), ('Ελένη', 'Κ', 'banana@x.gr', NULL)")
    q("INSERT INTO teachers (name, short_name, email, phone, color) VALUES "
      "('nan', 'NAN', 'nan', 'Nan ', '#000000')")

    command.upgrade(cfg, "head")
    widths = dict(q("SELECT table_name, character_maximum_length FROM information_schema.columns "
                    "WHERE column_name = 'phone' AND table_name IN ('students', 'teachers')"))
    assert widths == {"students": 100, "teachers": 100}
    assert q("SELECT first_name, last_name, email, phone FROM students ORDER BY id") == [
        ("Nan", "Nancy", None, None), ("Άννα", "Χ", None, "6971234567"),
        ("Γιώργος", "Π", "Nancy@x.gr", "nan2"), ("Ελένη", "Κ", "banana@x.gr", None)]
    assert q("SELECT name, short_name, email, phone FROM teachers") == [("nan", "NAN", None, None)]
    log = q("SELECT table_name, column_name, old_value FROM data_cleanup_log ORDER BY id")
    assert sorted(log) == sorted([("students", "email", "nan"), ("students", "phone", "NaN"),
                                  ("students", "email", " NAN "), ("teachers", "email", "nan"),
                                  ("teachers", "phone", "Nan ")])

    # Ξανά (downgrade → upgrade): τίποτα δεν αλλάζει, κανένα νέο ίχνος, ο log μένει.
    command.downgrade(cfg, "a7b3e2d9c4f1")
    assert q("SELECT count(*) FROM data_cleanup_log") == [(5,)]
    q("UPDATE students SET phone = repeat('9', 100) WHERE first_name = 'Ελένη'")
    command.upgrade(cfg, "head")
    assert q("SELECT count(*) FROM data_cleanup_log") == [(5,)]
    assert q("SELECT length(phone) FROM students WHERE first_name = 'Ελένη'") == [(100,)]
