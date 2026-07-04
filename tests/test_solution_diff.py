"""Tests για το slot-level diff δύο λύσεων: «τι άλλαξε μετά το regenerate;»

Το /api/solver/compare δίνει μόνο aggregate metrics — το diff απαντά το
πρακτικό ερώτημα: ποια μαθήματα μετακινήθηκαν (από πού → πού), τι μπήκε,
τι βγήκε, και πώς άλλαξε ο φόρτος ανά καθηγητή.
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
    TimetableSlot,
    TimetableSolution,
)
from backend.routers import solver as solver_router
from backend.services.solution_diff import compute_diff


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))
    subj = Subject(name="Άλγεβρα", short_name="ΑΛΓ", color="#000")
    t1 = Teacher(name="Νικολάου", short_name="Ν", color="#000")
    cls = SchoolClass(name="Β1", short_name="Β1")
    room = Classroom(name="Αίθουσα 1", short_name="Α1")
    periods = [
        Period(name=f"{i}η", short_name=str(i), start_time=f"{15+i}:00",
               end_time=f"{15+i}:50", is_break=False, sort_order=i)
        for i in range(1, 4)
    ]
    s.add_all([subj, t1, cls, room, *periods])
    s.commit()
    for o in [subj, t1, cls, room, *periods]:
        s.refresh(o)
    lesson = Lesson(subject_id=subj.id, teacher_id=t1.id, class_id=cls.id,
                    periods_per_week=2, duration=1)
    lesson2 = Lesson(subject_id=subj.id, teacher_id=t1.id, class_id=cls.id,
                     periods_per_week=1, duration=1)
    s.add_all([lesson, lesson2])
    s.commit()
    s.refresh(lesson)
    s.refresh(lesson2)

    base = TimetableSolution(name="Πριν", status="optimal")
    other = TimetableSolution(name="Μετά", status="optimal")
    s.add_all([base, other])
    s.commit()
    s.refresh(base)
    s.refresh(other)

    s.db_objects = {"lesson": lesson, "lesson2": lesson2, "periods": periods,
                    "room": room, "base": base, "other": other, "teacher": t1}
    yield s
    s.close()


def _slot(s, solution, lesson, day, period, room, unplaced=False):
    slot = TimetableSlot(solution_id=solution.id, lesson_id=lesson.id,
                         day_of_week=None if unplaced else day,
                         period_id=None if unplaced else period.id,
                         classroom_id=None if unplaced else room.id,
                         is_unplaced=unplaced)
    s.add(slot)
    s.commit()
    return slot


def test_diff_reports_moved_added_removed_and_unchanged(db):
    o = db.db_objects
    p1, p2, p3 = o["periods"]
    # base: lesson @ (Δευ,1η) + (Τρι,2η) · lesson2 @ (Τετ,1η)
    _slot(db, o["base"], o["lesson"], 0, p1, o["room"])
    _slot(db, o["base"], o["lesson"], 1, p2, o["room"])
    _slot(db, o["base"], o["lesson2"], 2, p1, o["room"])
    # other: lesson @ (Δευ,1η) [ίδιο] + (Πεμ,3η) [μετακίνηση] · lesson2 πουθενά [αφαιρέθηκε]
    _slot(db, o["other"], o["lesson"], 0, p1, o["room"])
    _slot(db, o["other"], o["lesson"], 3, p3, o["room"])

    diff = compute_diff(db, o["base"].id, o["other"].id)
    assert diff["unchanged_count"] == 1
    assert len(diff["moved"]) == 1
    mv = diff["moved"][0]
    assert mv["from"]["day_name"] == "Τρίτη" and mv["to"]["day_name"] == "Πέμπτη"
    assert "Άλγεβρα" in mv["lesson"]
    assert len(diff["removed"]) == 1  # το lesson2 έφυγε
    assert diff["added"] == []


def test_diff_teacher_load_delta(db):
    o = db.db_objects
    p1, p2 = o["periods"][0], o["periods"][1]
    _slot(db, o["base"], o["lesson"], 0, p1, o["room"])
    _slot(db, o["other"], o["lesson"], 0, p1, o["room"])
    _slot(db, o["other"], o["lesson"], 1, p2, o["room"])

    diff = compute_diff(db, o["base"].id, o["other"].id)
    loads = {t["teacher"]: t for t in diff["teacher_load"]}
    assert loads["Νικολάου"]["base_hours"] == 1
    assert loads["Νικολάου"]["other_hours"] == 2
    assert loads["Νικολάου"]["delta"] == 1


def test_diff_ignores_unplaced_slots(db):
    o = db.db_objects
    p1 = o["periods"][0]
    _slot(db, o["base"], o["lesson"], 0, p1, o["room"])
    _slot(db, o["other"], o["lesson"], 0, p1, o["room"])
    _slot(db, o["other"], o["lesson2"], None, None, None, unplaced=True)

    diff = compute_diff(db, o["base"].id, o["other"].id)
    assert diff["added"] == [] and diff["removed"] == [] and diff["moved"] == []
    assert diff["unchanged_count"] == 1


def test_diff_missing_solution_returns_none(db):
    o = db.db_objects
    assert compute_diff(db, o["base"].id, 99999) is None


# ------------------------------ HTTP route ------------------------------------

@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.db = db
    return c


def test_diff_endpoint_ok_and_404(client):
    o = client.db.db_objects
    p1 = o["periods"][0]
    _slot(client.db, o["base"], o["lesson"], 0, p1, o["room"])
    _slot(client.db, o["other"], o["lesson"], 1, p1, o["room"])

    res = client.get(f"/api/solver/diff?base_id={o['base'].id}&other_id={o['other'].id}")
    assert res.status_code == 200
    body = res.json()
    assert len(body["moved"]) == 1
    assert body["base"]["name"] == "Πριν" and body["other"]["name"] == "Μετά"

    assert client.get(f"/api/solver/diff?base_id={o['base'].id}&other_id=999").status_code == 404
