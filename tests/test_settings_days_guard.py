"""«Ημέρες / εβδομάδα»: λιγότερες ημέρες με τοποθετημένες ώρες σε ημέρα που
αφαιρείται → 409 χωρίς force (οι ώρες θα «χάνονταν» από πλέγμα/εκτυπώσεις και
ο solver θα προσπερνούσε τα κλειδωμένα). Αύξηση: πάντα επιτρέπεται."""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, SchoolSettings, StudentAvailability, Student,
    Subject, Teacher, TeacherAvailability, Term, TimetableSlot, TimetableSolution,
)
from backend.routers import settings as settings_router


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    term = Term(name="Χειμερινό", is_active=True)
    subj = Subject(name="ΜΑΘ", short_name="ΜΑΘ", color="#000000")
    teacher = Teacher(name="Τ1", short_name="Τ1", color="#000000")
    cls = SchoolClass(name="Α1", short_name="Α1")
    room = Classroom(name="R1", short_name="R1", room_type="regular")
    period = Period(name="1η", short_name="1", start_time="16:00", end_time="17:00",
                    is_break=False, sort_order=1)
    student = Student(first_name="Νίκος", last_name="Π")
    s.add_all([term, subj, teacher, cls, room, period, student])
    s.add(SchoolSettings(id=1, school_name="Κορυφή", days_per_week=6))
    s.commit()
    live = TimetableSolution(name="Τρέχον", status="optimal", term_id=term.id)
    old = TimetableSolution(name="Παλιό", status="optimal", term_id=term.id,
                            archived_at=dt.datetime(2026, 9, 20))
    lesson = Lesson(subject_id=subj.id, teacher_id=teacher.id, class_id=cls.id,
                    periods_per_week=3, term_id=term.id)
    s.add_all([live, old, lesson])
    s.commit()

    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/settings")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.s, c.live, c.old, c.lesson, c.period, c.room = s, live, old, lesson, period, room
    c.teacher, c.student, c.term = teacher, student, term
    yield c
    s.close()


def _slot(env, sol, day, locked=False):
    slot = TimetableSlot(solution_id=sol.id, lesson_id=env.lesson.id, day_of_week=day,
                         period_id=env.period.id, classroom_id=env.room.id,
                         is_unplaced=False, is_locked=locked)
    env.s.add(slot)
    env.s.commit()
    return slot


def _put_days(env, days):
    return env.put("/api/settings/", json={"school_name": "Κορυφή", "days_per_week": days,
                                            "institution_type": "frontistirio"})


def _days(env):
    env.s.expire_all()
    return env.s.get(SchoolSettings, 1).days_per_week


def test_lowering_with_placed_saturday_hours_is_refused_without_force(env):
    _slot(env, env.live, 5, locked=True)
    _slot(env, env.live, 5)
    _slot(env, env.live, 0)                              # Δευτέρα: αδιάφορη
    res = _put_days(env, 5)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "days_in_use" and "requires_force" not in detail
    assert detail["message"].startswith(
        "Δεν άλλαξαν οι ημέρες: υπάρχουν τοποθετημένες ώρες στο Σάββατο: "
        "«Τρέχον» (σενάριο «Χειμερινό») 2 ώρες.")
    assert "Παλέτα" in detail["message"]
    assert detail["programmes"] == [{
        "solution_id": env.live.id, "solution_name": "Τρέχον", "term_id": env.term.id,
        "term_name": "Χειμερινό", "archived": False, "slots": 2, "days": [5]}]
    assert _days(env) == 6                                 # τίποτα δεν άλλαξε
    assert _put_days(env, 6).status_code == 200            # ίδια τιμή: ΟΚ


def test_message_mentions_archived_programmes_and_availability_as_information(env):
    _slot(env, env.live, 5)
    _slot(env, env.old, 5)
    env.s.add_all([
        TeacherAvailability(term_id=env.term.id, teacher_id=env.teacher.id, day_of_week=5,
                            period_id=env.period.id, status="unavailable"),
        StudentAvailability(term_id=env.term.id, student_id=env.student.id, day_of_week=5,
                            period_id=env.period.id, status="unavailable"),
        TeacherAvailability(term_id=env.term.id, teacher_id=env.teacher.id, day_of_week=0,
                            period_id=env.period.id, status="unavailable"),
    ])
    env.s.commit()
    detail = _put_days(env, 5).json()["detail"]
    msg = detail["message"]
    assert "«Τρέχον» (σενάριο «Χειμερινό») 1 ώρες" in msg
    assert "αρχειοθετημένα προγράμματα" in msg and "«Παλιό» (σενάριο «Χειμερινό») 1 ώρες" in msg
    assert "2 κωλύματα" in msg and detail["availability"] == 2


def test_archived_only_hours_do_not_block(env):
    _slot(env, env.old, 5)
    assert _put_days(env, 5).status_code == 200
    assert _days(env) == 5


def test_no_hours_on_removed_days_and_increasing_are_always_allowed(env):
    _slot(env, env.live, 4)                              # Παρασκευή: μένει
    assert _put_days(env, 5).status_code == 200
    assert _days(env) == 5
    _slot(env, env.live, 5)                              # ώρα Σαββάτου ενώ είναι 5 μέρες
    assert _put_days(env, 7).status_code == 200          # αύξηση: πάντα ΟΚ
    assert _days(env) == 7
    res = _put_days(env, 4)                              # αφαιρούνται Παρασκευή + Σάββατο
    assert res.status_code == 409
    assert "σε Παρασκευή, Σάββατο" in res.json()["detail"]["message"]
