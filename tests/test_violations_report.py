"""Tests για την αναφορά «γιατί αυτό το score;» — ονομαστικές παραβιάσεις
soft constraints μιας λύσης.

Τα aggregate metrics (solution_metrics) λένε ΠΟΣΑ κενά/αργίες υπάρχουν·
η αναφορά λέει ΠΟΙΟΣ, ΠΟΤΕ και ΠΟΥ — ώστε το tuning των βαρών να μη
γίνεται στα τυφλά.
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
from backend.services.violations_report import compute_violations


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
    subj = Subject(name="Φυσική", short_name="ΦΥΣ", color="#000")
    t1 = Teacher(name="Νικολάου", short_name="Ν", color="#000")
    t2 = Teacher(name="Παπαδόπουλος", short_name="Π", color="#000")
    cls = SchoolClass(name="Γ1", short_name="Γ1")
    room = Classroom(name="Αίθουσα 1", short_name="Α1")
    # 7 διδακτικές ώρες ώστε οι δείκτες 5+ (sort_order 6η/7η) να είναι «αργά».
    periods = [
        Period(name=f"{i}η", short_name=str(i), start_time=f"{10+i}:00",
               end_time=f"{10+i}:50", is_break=False, sort_order=i)
        for i in range(1, 8)
    ]
    s.add_all([subj, t1, t2, cls, room, *periods])
    s.commit()
    for o in [subj, t1, t2, cls, room, *periods]:
        s.refresh(o)
    l1 = Lesson(subject_id=subj.id, teacher_id=t1.id, class_id=cls.id,
                periods_per_week=3, duration=1)
    l2 = Lesson(subject_id=subj.id, teacher_id=t2.id, class_id=cls.id,
                periods_per_week=1, duration=1)
    s.add_all([l1, l2])
    s.commit()
    s.refresh(l1)
    s.refresh(l2)
    sol = TimetableSolution(name="Λύση", status="optimal")
    s.add(sol)
    s.commit()
    s.refresh(sol)
    s.db_objects = {"l1": l1, "l2": l2, "periods": periods, "room": room,
                    "sol": sol, "t1": t1, "t2": t2}
    yield s
    s.close()


def _place(s, o, lesson, day, period_idx):
    s.add(TimetableSlot(solution_id=o["sol"].id, lesson_id=lesson.id,
                        day_of_week=day, period_id=o["periods"][period_idx].id,
                        classroom_id=o["room"].id))
    s.commit()


def test_gap_reported_with_teacher_day_and_periods(db):
    o = db.db_objects
    # Νικολάου, Δευτέρα: 1η και 3η → κενό στη 2η.
    _place(db, o, o["l1"], 0, 0)
    _place(db, o, o["l1"], 0, 2)

    rep = compute_violations(db, o["sol"].id)
    assert rep["summary"]["gap_total"] == 1
    gap = rep["teacher_gaps"][0]
    assert gap["teacher"] == "Νικολάου"
    assert gap["day_name"] == "Δευτέρα"
    assert gap["gap_periods"] == ["2η"]


def test_late_slots_named(db):
    o = db.db_objects
    # 7η ώρα (index 6 > LATE_THRESHOLD_INDEX 4) → «αργά».
    _place(db, o, o["l1"], 1, 6)

    rep = compute_violations(db, o["sol"].id)
    assert rep["summary"]["late_total"] == 1
    late = rep["late_slots"][0]
    assert late["day_name"] == "Τρίτη"
    assert late["period_name"] == "7η"
    assert late["class_name"] == "Γ1"


def test_workload_per_teacher_sorted_desc(db):
    o = db.db_objects
    _place(db, o, o["l1"], 0, 0)
    _place(db, o, o["l1"], 1, 0)
    _place(db, o, o["l2"], 2, 0)

    rep = compute_violations(db, o["sol"].id)
    assert [w["teacher"] for w in rep["workload"]] == ["Νικολάου", "Παπαδόπουλος"]
    assert [w["hours"] for w in rep["workload"]] == [2, 1]


def test_clean_solution_reports_no_violations(db):
    o = db.db_objects
    _place(db, o, o["l1"], 0, 0)
    _place(db, o, o["l1"], 0, 1)  # συνεχόμενες — κανένα κενό, όχι αργά

    rep = compute_violations(db, o["sol"].id)
    assert rep["summary"]["gap_total"] == 0
    assert rep["summary"]["late_total"] == 0
    assert rep["teacher_gaps"] == [] and rep["late_slots"] == []


def test_missing_solution_returns_none(db):
    assert compute_violations(db, 99999) is None


def test_violations_endpoint(db):
    o = db.db_objects
    _place(db, o, o["l1"], 0, 0)
    _place(db, o, o["l1"], 0, 2)

    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    res = c.get(f"/api/solver/solutions/{o['sol'].id}/violations")
    assert res.status_code == 200
    assert res.json()["summary"]["gap_total"] == 1
    assert c.get("/api/solver/solutions/99999/violations").status_code == 404
