"""📢 G3-12: δύο αιτήματα «Δημοσίευση» / «Αποστολή email» που επικαλύπτονται
(διπλό κλικ, δύο καρτέλες) δεν βγάζουν δύο δημοσιεύσεις ούτε διπλά email.

Χρειάζεται πραγματική Postgres (το κλείδωμα είναι pg_advisory_xact_lock· η
SQLite των υπόλοιπων tests δεν έχει ταυτόχρονες συναλλαγές). Τρέχει μόνο με
EDS_TEST_POSTGRES_URL=postgresql://user@host:port/postgres — φτιάχνει και
σβήνει δική του βάση· ποτέ σε βάση με δεδομένα.
"""
from __future__ import annotations

import os
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, SolutionPublication, Subject, Teacher, Term, TimetableSlot,
    TimetableSolution,
)
from backend.services import publication as svc

PG_URL = os.environ.get("EDS_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="χρειάζεται EDS_TEST_POSTGRES_URL (Postgres μιας χρήσης)")

_DB = "eds_publication_lock_test"
_WAIT = 1.5   # όσο «κρατά» το 1ο αίτημα ανοιχτή τη συναλλαγή του


@pytest.fixture()
def pg():
    admin = create_engine(PG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{_DB}"'))
    engine = create_engine(make_url(PG_URL).set(database=_DB))
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        term = Term(name="Χειμερινό", is_active=True)
        subj = Subject(name="ΦΥΣΙΚΗ", short_name="Φ", color="#000000")
        t = Teacher(name="Γ. Παπαδόπουλος", short_name="ΓΠ", color="#000000", email="g@example.com")
        c = SchoolClass(name="Β2", short_name="Β2")
        r = Classroom(name="Αίθ. Α", short_name="Α", room_type="regular")
        p = Period(name="1η", short_name="1", start_time="16:00", end_time="17:00", is_break=False, sort_order=1)
        s.add_all([term, subj, t, c, r, p])
        s.commit()
        sol = TimetableSolution(name="ΧΕΙΜΕΡΙΝΟ", status="optimal", term_id=term.id)
        lesson = Lesson(subject_id=subj.id, teacher_id=t.id, class_id=c.id, periods_per_week=1, term_id=term.id)
        s.add_all([sol, lesson])
        s.commit()
        s.add(TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=0, period_id=p.id,
                            classroom_id=r.id, is_unplaced=False))
        s.commit()
        ids = {"sol": sol.id, "teacher": t.id}
    yield Session, ids
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB}" WITH (FORCE)'))
    admin.dispose()


def _race(first_inside: threading.Event, second_done: threading.Event, action) -> dict:
    """Το «A» μπαίνει πρώτο και περιμένει (έως _WAIT) μέσα στη συναλλαγή του·
    στο μεταξύ τρέχει ολόκληρο το «B». Επιστρέφει {όνομα: αποτέλεσμα}."""
    results = {}

    def run(name):
        try:
            results[name] = action(name)
        finally:
            if name == "B":
                second_done.set()

    a = threading.Thread(target=run, args=("A",), name="A")
    a.start()
    assert first_inside.wait(10)
    b = threading.Thread(target=run, args=("B",), name="B")
    b.start()
    a.join(20)
    b.join(20)
    return results


def test_overlapping_publish_requests_make_one_publication(pg, monkeypatch):
    Session, ids = pg
    inside, done = threading.Event(), threading.Event()
    real_preview = svc.preview

    def slow_preview(db, solution_id):
        data = real_preview(db, solution_id)
        if threading.current_thread().name == "A":
            inside.set()
            done.wait(_WAIT)
        return data
    monkeypatch.setattr(svc, "preview", slow_preview)

    def publish(_name):
        with Session() as db:
            try:
                pub = svc.publish(db, ids["sol"], None, True, [ids["teacher"]])
                db.commit()
                return "ok"
            except svc.PublishError as exc:
                db.rollback()
                return exc.code

    results = _race(inside, done, publish)
    assert results == {"A": "ok", "B": "no_changes"}
    with Session() as db:
        assert db.query(SolutionPublication).count() == 1


def test_overlapping_email_requests_queue_the_emails_once(pg, monkeypatch):
    Session, ids = pg
    with Session() as db:
        pid = svc.publish(db, ids["sol"], None, True, []).id
        db.commit()
    inside, done = threading.Event(), threading.Event()
    real_latest = svc.latest_publication

    def slow_latest(db, term_id):
        pub = real_latest(db, term_id)
        if threading.current_thread().name == "A":
            inside.set()
            done.wait(_WAIT)
        return pub
    monkeypatch.setattr(svc, "latest_publication", slow_latest)

    def request(_name):
        with Session() as db:
            try:
                svc.request_emails(db, pid, [ids["teacher"]])
                db.commit()
                return "ok"
            except svc.PublishError as exc:
                db.rollback()
                return exc.code

    results = _race(inside, done, request)
    assert sorted(results.values()) == ["ok", "sending"]   # ΕΝΑ background job, όχι δύο
