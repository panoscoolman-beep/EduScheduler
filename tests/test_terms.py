"""Tests για τα Σενάρια (Terms) — τη μόνη destructive business λογική που
μπήκε (Phase 1+2) χωρίς κάλυψη: clone, shift-times, activate, delete.

Ιδιαίτερο βάρος στο shift_term_times: κάνει snapshot→DELETE→reinsert στη
διαθεσιμότητα και ΡΙΧΝΕΙ οριστικά ό,τι πέφτει εκτός εύρους — πρέπει (α) να
είναι αντιστρέψιμο για in-range offsets, (β) να μετρά σωστά τι έριξε, και
(γ) να ΑΡΝΕΙΤΑΙ ένα offset που θα άδειαζε ολόκληρο το σενάριο.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom,
    Lesson,
    Period,
    SchoolClass,
    SchoolSettings,
    Subject,
    Teacher,
    TeacherAvailability,
    Term,
    TimetableSlot,
    TimetableSolution,
)
from backend.routers import terms as terms_router


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Το delete-cascade των terms είναι DB-level (ForeignKey ondelete=CASCADE).
    # Το sqlite ΔΕΝ επιβάλλει FKs χωρίς αυτό το pragma — χωρίς αυτό το
    # delete test θα περνούσε ψευδώς ακόμα κι αν το cascade χαλούσε.
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fks(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    app = FastAPI()
    app.include_router(terms_router.router, prefix="/api/terms")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session = s
    yield c
    s.close()


def _seed_catalog(s, n_periods=4):
    """Global catalog: settings, περίοδοι, καθηγητής, τάξη, μάθημα, αίθουσα."""
    s.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))
    subj = Subject(name="Math", short_name="Μ", color="#000")
    teacher = Teacher(name="Νικολάου", short_name="Ν", color="#000")
    cls = SchoolClass(name="A1", short_name="A1")
    room = Classroom(name="R1", short_name="R1", room_type="regular")
    periods = [
        Period(name=f"{i}η", short_name=str(i), start_time=f"{7+i:02d}:00",
               end_time=f"{7+i:02d}:50", is_break=False, sort_order=i)
        for i in range(1, n_periods + 1)
    ]
    s.add_all([subj, teacher, cls, room, *periods])
    s.commit()
    for o in [subj, teacher, cls, room, *periods]:
        s.refresh(o)
    return {"subject": subj, "teacher": teacher, "class": cls,
            "room": room, "periods": periods}


def _seed_term_with_inputs(s, seed, *, name="Κύριο", active=True,
                           availability_periods=(0,)):
    """Term + 1 lesson + availability του καθηγητή στα δοσμένα period indexes."""
    term = Term(name=name, is_active=active)
    s.add(term)
    s.commit()
    s.refresh(term)
    s.add(Lesson(subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
                 class_id=seed["class"].id, periods_per_week=2, duration=1,
                 term_id=term.id))
    for idx in availability_periods:
        s.add(TeacherAvailability(teacher_id=seed["teacher"].id, day_of_week=0,
                                  period_id=seed["periods"][idx].id,
                                  status="unavailable", term_id=term.id))
    s.commit()
    return term


def _availability_pairs(s, term_id):
    rows = s.query(TeacherAvailability).filter(
        TeacherAvailability.term_id == term_id
    ).all()
    return sorted((r.day_of_week, r.period_id) for r in rows)


# ------------------------------ create / activate ----------------------------

def test_first_term_becomes_active_automatically(client):
    res = client.post("/api/terms/", json={"name": "Πρώτο"})
    assert res.status_code == 201
    assert res.json()["is_active"] is True


def test_activate_is_exclusive(client):
    a = client.post("/api/terms/", json={"name": "A"}).json()
    b = client.post("/api/terms/", json={"name": "B"}).json()
    assert a["is_active"] is True and b["is_active"] is False

    res = client.post(f"/api/terms/{b['id']}/activate")
    assert res.status_code == 200
    terms = {t["id"]: t["is_active"] for t in client.get("/api/terms/").json()}
    assert terms == {a["id"]: False, b["id"]: True}


# ---------------------------------- clone ------------------------------------

def test_clone_copies_inputs_but_not_solutions(client):
    s = client.session
    seed = _seed_catalog(s)
    term = _seed_term_with_inputs(s, seed, availability_periods=(0, 1))
    sol = TimetableSolution(name="p1", status="optimal", term_id=term.id)
    s.add(sol)
    s.commit()

    res = client.post(f"/api/terms/{term.id}/clone",
                      json={"name": "Πείραμα", "activate": False})
    assert res.status_code == 201
    new_id = res.json()["id"]

    # Ίδια inputs στο νέο σενάριο…
    assert s.query(Lesson).filter(Lesson.term_id == new_id).count() == 1
    assert s.query(TeacherAvailability).filter(
        TeacherAvailability.term_id == new_id).count() == 2
    # …χωρίς προγράμματα, και με την πηγή ανέγγιχτη.
    assert s.query(TimetableSolution).filter(
        TimetableSolution.term_id == new_id).count() == 0
    assert s.query(Lesson).filter(Lesson.term_id == term.id).count() == 1
    assert s.query(TimetableSolution).filter(
        TimetableSolution.term_id == term.id).count() == 1
    # Χωρίς activate=True η πηγή μένει ενεργή.
    assert res.json()["is_active"] is False


def test_clone_inherits_term_dates(client):
    """Τα όρια του σεναρίου (ICS UNTIL/EXDATE) περνούν στο αντίγραφο —
    αλλιώς ο κλώνος θα έχανε σιωπηλά τη λήξη του ημερολογίου."""
    import datetime as dt
    s = client.session
    seed = _seed_catalog(s)
    term = _seed_term_with_inputs(s, seed)
    term.start_date = dt.date(2026, 9, 7)
    term.end_date = dt.date(2027, 5, 28)
    s.commit()

    res = client.post(f"/api/terms/{term.id}/clone",
                      json={"name": "Κλώνος", "activate": False})
    assert res.status_code == 201
    body = res.json()
    assert body["start_date"] == "2026-09-07"
    assert body["end_date"] == "2027-05-28"


def test_update_term_rejects_inverted_dates(client):
    t = client.post("/api/terms/", json={"name": "Α"}).json()
    res = client.put(f"/api/terms/{t['id']}",
                     json={"start_date": "2027-01-01", "end_date": "2026-01-01"})
    assert res.status_code == 400


def test_clone_with_activate_switches_active(client):
    s = client.session
    seed = _seed_catalog(s)
    term = _seed_term_with_inputs(s, seed)
    res = client.post(f"/api/terms/{term.id}/clone",
                      json={"name": "Νέο", "activate": True})
    assert res.status_code == 201
    assert res.json()["is_active"] is True
    s.refresh(term)
    assert term.is_active is False


# ------------------------------- shift-times ---------------------------------

def test_shift_plus_then_minus_is_roundtrip(client):
    s = client.session
    seed = _seed_catalog(s, n_periods=4)
    term = _seed_term_with_inputs(s, seed, availability_periods=(0, 1))
    before = _availability_pairs(s, term.id)

    r1 = client.post(f"/api/terms/{term.id}/shift-times", json={"offset": 2})
    assert r1.status_code == 200
    assert r1.json()["availability_moved"] == 2
    assert r1.json()["availability_dropped"] == 0
    s.expire_all()
    assert _availability_pairs(s, term.id) != before

    r2 = client.post(f"/api/terms/{term.id}/shift-times", json={"offset": -2})
    assert r2.status_code == 200
    s.expire_all()
    assert _availability_pairs(s, term.id) == before


def test_shift_drops_out_of_range_and_unplaces_slots_with_counts(client):
    s = client.session
    seed = _seed_catalog(s, n_periods=4)
    # Διαθεσιμότητα στις περιόδους 1η και 4η (indexes 0, 3).
    term = _seed_term_with_inputs(s, seed, availability_periods=(0, 3))
    lesson = s.query(Lesson).filter(Lesson.term_id == term.id).first()
    sol = TimetableSolution(name="p1", status="optimal", term_id=term.id)
    s.add(sol)
    s.commit()
    s.refresh(sol)
    # Slot στην 4η ώρα → με offset +1 βγαίνει εκτός εύρους.
    slot = TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=0,
                         period_id=seed["periods"][3].id,
                         classroom_id=seed["room"].id)
    s.add(slot)
    s.commit()
    s.refresh(slot)

    res = client.post(f"/api/terms/{term.id}/shift-times", json={"offset": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["availability_moved"] == 1     # 1η → 2η
    assert body["availability_dropped"] == 1   # 4η → εκτός
    assert body["slots_unplaced"] == 1
    s.expire_all()
    s.refresh(slot)
    assert slot.is_unplaced is True
    assert slot.period_id is None


def test_shift_wiping_whole_scenario_is_refused(client):
    """|offset| >= αριθμός διδακτικών ωρών θα άδειαζε ΟΛΟ το σενάριο —
    πρέπει να απορρίπτεται πριν αγγίξει δεδομένα (400, τίποτα δεν χάνεται)."""
    s = client.session
    seed = _seed_catalog(s, n_periods=4)
    term = _seed_term_with_inputs(s, seed, availability_periods=(0, 1, 2, 3))

    res = client.post(f"/api/terms/{term.id}/shift-times", json={"offset": 4})
    assert res.status_code == 400
    # Τίποτα δεν διαγράφηκε.
    assert len(_availability_pairs(s, term.id)) == 4


def test_shift_zero_offset_rejected(client):
    s = client.session
    seed = _seed_catalog(s)
    term = _seed_term_with_inputs(s, seed)
    res = client.post(f"/api/terms/{term.id}/shift-times", json={"offset": 0})
    assert res.status_code == 400


# ---------------------------------- delete -----------------------------------

def test_delete_last_term_refused(client):
    t = client.post("/api/terms/", json={"name": "Μόνο"}).json()
    res = client.delete(f"/api/terms/{t['id']}")
    assert res.status_code == 400


def test_delete_term_with_data_needs_force_and_reports_counts(client):
    s = client.session
    seed = _seed_catalog(s)
    term = _seed_term_with_inputs(s, seed)  # active, με 1 lesson
    other = Term(name="Άλλο", is_active=False)
    s.add(other)
    s.commit()

    res = client.delete(f"/api/terms/{term.id}")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["requires_force"] is True
    assert detail["lessons"] == 1


def test_delete_active_term_with_force_reactivates_next(client):
    s = client.session
    seed = _seed_catalog(s)
    term = _seed_term_with_inputs(s, seed, active=True)
    other = Term(name="Άλλο", is_active=False)
    s.add(other)
    s.commit()
    s.refresh(other)

    res = client.delete(f"/api/terms/{term.id}?force=true")
    assert res.status_code == 204
    s.expire_all()
    assert s.query(Term).count() == 1
    assert s.query(Term).first().is_active is True
    # Τα scoped δεδομένα του διαγραμμένου σεναρίου έφυγαν μαζί του.
    assert s.query(Lesson).filter(Lesson.term_id == term.id).count() == 0
