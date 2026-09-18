"""📦 Αρχειοθέτηση καθηγητών / τμημάτων / αιθουσών (services/archive.py)."""
from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, Subject, Teacher, Term, TimetableSlot, TimetableSolution,
)
from backend.routers import classes as classes_router
from backend.routers import classrooms as classrooms_router
from backend.routers import teachers as teachers_router
from backend.services.slot_placement import pick_default_classroom


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add_all([Term(id=1, name="ΧΕΙΜΕΡΙΝΟ", is_active=True), Term(id=2, name="Παλιό", is_active=False)])
    subj = Subject(name="Άλγεβρα", short_name="ΑΛΓ", color="#000")
    busy_t, free_t = Teacher(name="Διδάσκει", short_name="Δ", color="#000000"), Teacher(name="Έφυγε", short_name="Ε", color="#000000")
    busy_c, old_c = SchoolClass(name="Β2", short_name="Β2"), SchoolClass(name="Περσινό", short_name="ΠΕ")
    used_r = Classroom(name="Αίθ 1", short_name="Α1", room_type="regular")
    old_r = Classroom(name="Αποθήκη", short_name="ΑΠ", room_type="regular")
    period = Period(name="1η", short_name="1", start_time="14:00", end_time="15:00", is_break=False, sort_order=1)
    s.add_all([subj, busy_t, free_t, busy_c, old_c, used_r, old_r, period])
    s.commit()
    active_lesson = Lesson(subject_id=subj.id, teacher_id=busy_t.id, class_id=busy_c.id,
                           periods_per_week=1, term_id=1)
    old_lesson = Lesson(subject_id=subj.id, teacher_id=free_t.id, class_id=old_c.id,
                        periods_per_week=1, term_id=2)
    live = TimetableSolution(name="Ζωντανό", status="optimal", term_id=1)
    archived = TimetableSolution(name="Αρχείο", status="optimal", term_id=1,
                                 archived_at=datetime.datetime(2026, 9, 18))
    s.add_all([active_lesson, old_lesson, live, archived])
    s.commit()
    s.add(TimetableSlot(solution_id=live.id, lesson_id=active_lesson.id, day_of_week=0,
                        period_id=period.id, classroom_id=used_r.id, is_unplaced=False))
    s.add(TimetableSlot(solution_id=archived.id, lesson_id=active_lesson.id, day_of_week=1,
                        period_id=period.id, classroom_id=old_r.id, is_unplaced=False))
    s.commit()

    app = FastAPI()
    app.include_router(teachers_router.router, prefix="/api/teachers")
    app.include_router(classes_router.router, prefix="/api/classes")
    app.include_router(classrooms_router.router, prefix="/api/classrooms")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session = s
    c.ids = {"busy_t": busy_t.id, "free_t": free_t.id, "busy_c": busy_c.id, "old_c": old_c.id,
             "used_r": used_r.id, "old_r": old_r.id, "lesson": active_lesson.id}
    yield c
    s.close()


def _names(c, path, archived=False):
    url = f"/api/{path}/" + ("?include_archived=true" if archived else "")
    return {x["name"]: x["archived"] for x in c.get(url).json()}


@pytest.mark.parametrize("path, key", [("teachers", "busy_t"), ("classes", "busy_c")])
def test_cannot_archive_what_the_active_scenario_uses(env, path, key):
    res = env.post(f"/api/{path}/{env.ids[key]}/archive")
    assert res.status_code == 409
    assert "ενεργού σεναρίου «ΧΕΙΜΕΡΙΝΟ»" in res.json()["detail"]


@pytest.mark.parametrize("path, key, name", [("teachers", "free_t", "Έφυγε"), ("classes", "old_c", "Περσινό")])
def test_archive_hides_from_lists_and_restores(env, path, key, name):
    res = env.post(f"/api/{path}/{env.ids[key]}/archive")
    assert res.status_code == 200 and res.json()["archived"] is True
    assert name not in _names(env, path)
    assert _names(env, path, archived=True)[name] is True
    assert env.post(f"/api/{path}/{env.ids[key]}/unarchive").status_code == 200
    assert _names(env, path)[name] is False


def test_classroom_with_live_placed_hours_cannot_be_archived(env):
    res = env.post(f"/api/classrooms/{env.ids['used_r']}/archive")
    assert res.status_code == 409 and "τοποθετημένες 1 ώρες" in res.json()["detail"]
    # Η «Αποθήκη» έχει ώρα μόνο σε ΑΡΧΕΙΟΘΕΤΗΜΕΝΟ πρόγραμμα → επιτρέπεται.
    assert env.post(f"/api/classrooms/{env.ids['old_r']}/archive").status_code == 200
    assert env.post("/api/classrooms/999/archive").status_code == 404


def test_archived_rooms_are_never_picked_for_new_placements(env):
    s = env.session
    env.post(f"/api/classrooms/{env.ids['old_r']}/archive")
    lesson = s.query(Lesson).filter(Lesson.id == env.ids["lesson"]).first()
    picked = pick_default_classroom(s, lesson)
    assert picked == env.ids["used_r"]
    assert pick_default_classroom(s, lesson, exclude_room_ids={env.ids["used_r"]}) is None
