"""Αρχειοθέτηση προγράμματος: βγαίνει από τη ροή χωρίς να χαθεί τίποτα.

Ένα παλιό πρόγραμμα του ίδιου σεναρίου «κρατούσε» ώρες: εμφανιζόταν στη λίστα,
έπαιρνε slots από τον parking-lot sync και μπλόκαρε το καθάρισμα της Παλέτας
(«🔍 Τι επηρεάζει;»). Η αρχειοθέτηση το βγάζει από όλα αυτά — αναστρέψιμα.
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
    Classroom, Lesson, Period, SchoolClass, Subject, Teacher, Term,
    TimetableSlot, TimetableSolution,
)
from backend.routers import solver as solver_router
from backend.services.lesson_impact import lesson_impact
from backend.services.parking_lot_sync import sync_lesson_slot_count


@pytest.fixture()
def client():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()

    term = Term(id=1, name="Τρέχον", is_active=True)
    subj = Subject(name="Άλγεβρα", short_name="ΑΛΓ", color="#000")
    teacher = Teacher(name="Καθ", short_name="Κ", color="#000")
    cls = SchoolClass(name="Γ ΕΠΑΛ", short_name="ΓΕ")
    room = Classroom(name="Α1", short_name="Α1", room_type="regular")
    period = Period(name="1η", short_name="1", start_time="14:00",
                    end_time="15:00", is_break=False, sort_order=1)
    s.add_all([term, subj, teacher, cls, room, period])
    s.commit()
    for o in (term, subj, teacher, cls, room, period):
        s.refresh(o)

    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session, c.subj, c.teacher, c.cls, c.room, c.period = s, subj, teacher, cls, room, period
    yield c
    s.close()


def _solution(c, name, status="optimal"):
    sol = TimetableSolution(name=name, status=status, term_id=1)
    c.session.add(sol)
    c.session.commit()
    c.session.refresh(sol)
    return sol


def _lesson(c, ppw=3):
    lesson = Lesson(subject_id=c.subj.id, teacher_id=c.teacher.id,
                    class_id=c.cls.id, periods_per_week=ppw, term_id=1)
    c.session.add(lesson)
    c.session.commit()
    c.session.refresh(lesson)
    return lesson


def _slots(c, sol, lesson, placed=0, unplaced=0):
    for i in range(placed):
        c.session.add(TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=i % 5,
                                    period_id=c.period.id, classroom_id=c.room.id, is_unplaced=False))
    for _ in range(unplaced):
        c.session.add(TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, is_unplaced=True))
    c.session.commit()


def _names(payload):
    return [s["name"] for s in payload]


def test_archive_hides_the_programme_from_the_list_and_restores_it(client):
    _solution(client, "ΧΕΙΜΕΡΙΝΟ")
    old = _solution(client, "Παλιό 8/5")

    res = client.post(f"/api/solver/solutions/{old.id}/archive").json()
    assert res["archived"] is True and "αρχειοθετήθηκε" in res["message"]

    assert _names(client.get("/api/solver/solutions").json()) == ["ΧΕΙΜΕΡΙΝΟ"]
    with_archived = client.get("/api/solver/solutions?include_archived=true").json()
    assert {s["name"]: s["archived"] for s in with_archived} == {"ΧΕΙΜΕΡΙΝΟ": False, "Παλιό 8/5": True}

    back = client.post(f"/api/solver/solutions/{old.id}/unarchive").json()
    assert back["archived"] is False
    assert sorted(_names(client.get("/api/solver/solutions").json())) == ["Παλιό 8/5", "ΧΕΙΜΕΡΙΝΟ"]


def test_archived_programme_keeps_all_its_hours(client):
    old = _solution(client, "Παλιό")
    lesson = _lesson(client)
    _slots(client, old, lesson, placed=3)

    client.post(f"/api/solver/solutions/{old.id}/archive")
    kept = client.session.query(TimetableSlot).filter(TimetableSlot.solution_id == old.id).count()
    assert kept == 3                                   # τίποτα δεν σβήστηκε
    assert client.get(f"/api/solver/solutions/{old.id}").status_code == 200


def test_archived_programme_stops_holding_palette_hours(client):
    """Η πραγματική περίπτωση: το παλιό πρόγραμμα κρατούσε τις 3 ώρες και
    μπλόκαρε το καθάρισμα στο τρέχον."""
    current = _solution(client, "ΧΕΙΜΕΡΙΝΟ")
    old = _solution(client, "Παλιό 8/5")
    lesson = _lesson(client, ppw=3)
    _slots(client, current, lesson, unplaced=3)
    _slots(client, old, lesson, placed=3)

    before = lesson_impact(client.session, lesson.id)
    assert before["trim"]["can_trim"] is False
    assert before["trim"]["blocked_reason"] == "nothing_to_trim"

    client.post(f"/api/solver/solutions/{old.id}/archive")

    after = lesson_impact(client.session, lesson.id)
    assert [r["solution_name"] for r in after["solutions"]] == ["ΧΕΙΜΕΡΙΝΟ"]
    assert after["trim"]["blocked_reason"] == "no_placed_hours"    # → πρόταση διαγραφής
    assert after["delete"]["requires_force"] is False              # καμία τοποθετημένη πια


def test_archived_programme_gets_no_new_slots_from_sync(client):
    current = _solution(client, "ΧΕΙΜΕΡΙΝΟ")
    old = _solution(client, "Παλιό")
    lesson = _lesson(client, ppw=2)
    _slots(client, current, lesson, unplaced=2)
    _slots(client, old, lesson, unplaced=2)
    client.post(f"/api/solver/solutions/{old.id}/archive")

    lesson.periods_per_week = 4
    client.session.commit()
    sync_lesson_slot_count(client.session, lesson.id)

    def count(sol):
        return client.session.query(TimetableSlot).filter(
            TimetableSlot.solution_id == sol.id, TimetableSlot.lesson_id == lesson.id).count()

    assert count(current) == 4      # το ενεργό συμπληρώθηκε
    assert count(old) == 2          # το αρχειοθετημένο έμεινε ανέγγιχτο


def test_cannot_archive_a_programme_while_it_is_being_generated(client):
    running = _solution(client, "Τρέχει", status="generating")
    res = client.post(f"/api/solver/solutions/{running.id}/archive")
    assert res.status_code == 409 and "υπολογίζεται" in res.json()["detail"]
    client.session.refresh(running)
    assert running.archived_at is None


def test_archive_404_for_unknown_programme(client):
    assert client.post("/api/solver/solutions/999/archive").status_code == 404
    assert client.post("/api/solver/solutions/999/unarchive").status_code == 404
