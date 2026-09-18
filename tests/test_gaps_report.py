"""🕳 Κενά ανά μαθητή/καθηγητή + προτάσεις διόρθωσης.

Κάθε πρόταση πρέπει να (α) μειώνει τα συνολικά κενά και (β) να περνά από
το κανονικό PUT του slot — ίδιοι έλεγχοι με το drag & drop.
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
    Classroom, Lesson, Period, SchoolClass, SchoolSettings, Student, StudentClassEnrollment,
    Subject, Teacher, TeacherAvailability, TimetableSlot, TimetableSolution,
)
from backend.routers import solver as solver_router
from backend.services import gaps_report as g


# --- pure ---------------------------------------------------------------------

def test_day_holes_and_runs():
    assert g.day_holes({0, 3, 4, 7}) == [1, 2, 5, 6]
    assert g.day_holes({2}) == [] and g.day_holes(set()) == []
    assert g.hole_runs([1, 2, 5, 6, 9]) == [[1, 2], [5, 6], [9]]


def test_gap_count_is_per_day():
    assert g.gap_count({(0, 0), (0, 2), (1, 1), (1, 4)}) == 1 + 2


def test_move_delta_counts_everyone_affected():
    people = {"S": {(0, 0), (0, 2)}, "T": {(0, 2), (0, 3)}}
    # η ώρα της 2 πάει στο 1: ο S κλείνει το κενό του, ο T αποκτά κενό (1,_,3)
    assert g.move_delta(people, (0, 2), (0, 1)) == {"S": -1, "T": 1}


# --- σενάριο ------------------------------------------------------------------

@pytest.fixture()
def env():
    """Δευτέρα: ο μαθητής Σ έχει Α1 στην 1η (Τ1) και Β2 στην 3η (Τ2) → κενό 2η."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))
    subj = Subject(name="ΦΥΣΙΚΗ", short_name="Φ", color="#000000")
    t1 = Teacher(name="Τ1", short_name="Τ1", color="#000000")
    t2 = Teacher(name="Τ2", short_name="Τ2", color="#000000")
    c1, c2 = SchoolClass(name="Α1", short_name="Α1"), SchoolClass(name="Β2", short_name="Β2")
    room = Classroom(name="Αίθ", short_name="Α", room_type="regular")
    stu = Student(first_name="Νίκος", last_name="Παππάς", grade="Β΄ Λυκείου")
    ps = [Period(name=f"{i}η", short_name=str(i), start_time=f"{15 + i}:00", end_time=f"{16 + i}:00",
                 is_break=False, sort_order=i) for i in (1, 2, 3)]
    brk = Period(name="Δ", short_name="Δ", start_time="16:55", end_time="17:00", is_break=True, sort_order=15)
    s.add_all([subj, t1, t2, c1, c2, room, stu, brk, *ps])
    s.commit()
    s.add_all([StudentClassEnrollment(student_id=stu.id, class_id=c1.id),
               StudentClassEnrollment(student_id=stu.id, class_id=c2.id)])
    sol = TimetableSolution(name="Χ", status="optimal")
    l1 = Lesson(subject_id=subj.id, teacher_id=t1.id, class_id=c1.id, periods_per_week=1)
    l2 = Lesson(subject_id=subj.id, teacher_id=t2.id, class_id=c2.id, periods_per_week=1)
    s.add_all([sol, l1, l2])
    s.commit()
    a = TimetableSlot(solution_id=sol.id, lesson_id=l1.id, day_of_week=0, period_id=ps[0].id,
                      classroom_id=room.id, is_unplaced=False)
    b = TimetableSlot(solution_id=sol.id, lesson_id=l2.id, day_of_week=0, period_id=ps[2].id,
                      classroom_id=room.id, is_unplaced=False)
    s.add_all([a, b])
    s.commit()
    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.s, c.sol, c.a, c.b, c.stu, c.t2, c.ps = s, sol, a, b, stu, t2, ps
    yield c
    s.close()


def test_report_lists_student_gap_and_weekly_hours(env):
    rep = env.get(f"/api/solver/solutions/{env.sol.id}/gaps").json()
    (st,) = rep["students"]
    assert st["name"] == "Παππάς Νίκος" and st["grade"] == "Β΄ Λυκείου"
    assert st["weekly_hours"] == 2 and st["days"] == 1 and st["gap_total"] == 1
    assert st["gaps"] == [{"day": 0, "day_name": "Δευτέρα", "from": "17:00", "to": "18:00", "hours": 1}]
    assert all(t["gap_total"] == 0 for t in rep["teachers"])   # το διάλειμμα δεν είναι κενό
    assert rep["totals"] == {"student_gaps": 1, "teacher_gaps": 0}


def _suggest(env):
    return env.get(f"/api/solver/solutions/{env.sol.id}/gaps/suggestions",
                   params={"kind": "student", "person_id": env.stu.id, "day": 0}).json()


def test_suggestions_close_the_gap_and_are_accepted_by_the_real_move(env):
    sugg = _suggest(env)
    assert {s["slot_id"] for s in sugg} == {env.a.id, env.b.id}
    assert all(s["gap_delta"] == -1 and s["period_id"] == env.ps[1].id for s in sugg)
    assert sugg[0]["effects"] == [{"name": "Παππάς Νίκος", "delta": -1}]
    pick = sugg[0]
    res = env.put(f"/api/solver/solutions/{env.sol.id}/slots/{pick['slot_id']}",
                  json={"day_of_week": pick["day_of_week"], "period_id": pick["period_id"]})
    assert res.status_code == 200, res.text
    assert env.get(f"/api/solver/solutions/{env.sol.id}/gaps").json()["totals"]["student_gaps"] == 0
    assert _suggest(env) == []


def test_locked_and_blocked_moves_are_never_suggested(env):
    env.a.is_locked = True
    env.s.add(TeacherAvailability(teacher_id=env.t2.id, day_of_week=0, period_id=env.ps[1].id,
                                  status="unavailable"))
    env.s.commit()
    assert _suggest(env) == []


def test_bad_params_and_missing_solution(env):
    base = f"/api/solver/solutions/{env.sol.id}/gaps/suggestions"
    assert env.get(base, params={"kind": "x", "person_id": 1, "day": 0}).status_code == 422
    assert env.get("/api/solver/solutions/999/gaps").status_code == 404
