"""Αλλαγή καθηγητή/τμήματος σε κάρτα με τοποθετημένες ώρες: 409 με τις
συγκρούσεις· με force η αλλαγή γίνεται και ΜΟΝΟ οι συγκρουόμενες ώρες πάνε
στην Παλέτα (με ιστορικό). Χωρίς σύγκρουση → κανονική αποθήκευση."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, Student, StudentClassEnrollment, Subject, Teacher,
    TeacherAvailability, Term, TimetableSlot, TimetableSlotHistory, TimetableSolution,
)
from backend.routers import lessons as lessons_router


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    term = Term(name="Χ", is_active=True)
    subj = Subject(name="ΧΗΜΕΙΑ", short_name="Χ", color="#000000")
    t1, t2, t3 = (Teacher(name=n, short_name=n, color="#000000") for n in ("Τ1", "Τ2", "Τ3"))
    c1, c2, c3, c4 = (SchoolClass(name=n, short_name=n) for n in ("Γ1", "Γ2", "Γ3", "Γ4"))
    room = Classroom(name="Α", short_name="Α", room_type="regular")
    p1 = Period(name="1η", short_name="1", start_time="15:00", end_time="16:00", is_break=False, sort_order=1)
    p2 = Period(name="2η", short_name="2", start_time="16:00", end_time="17:00", is_break=False, sort_order=2)
    stu = Student(first_name="Νίκος", last_name="Παππάς")
    s.add_all([term, subj, t1, t2, t3, c1, c2, c3, c4, room, p1, p2, stu])
    s.commit()
    s.add_all([StudentClassEnrollment(student_id=stu.id, class_id=c2.id),
               StudentClassEnrollment(student_id=stu.id, class_id=c4.id)])
    sol = TimetableSolution(name="ΧΕΙΜΕΡΙΝΟ", status="optimal", term_id=term.id)
    old = TimetableSolution(name="Παλιό", status="optimal", term_id=term.id, archived_at=datetime(2026, 9, 1))
    l1 = Lesson(subject_id=subj.id, teacher_id=t1.id, class_id=c1.id, periods_per_week=2, term_id=term.id)
    l2 = Lesson(subject_id=subj.id, teacher_id=t2.id, class_id=c2.id, periods_per_week=1, term_id=term.id)
    s.add_all([sol, old, l1, l2])
    s.commit()
    clash = TimetableSlot(solution_id=sol.id, lesson_id=l1.id, day_of_week=0, period_id=p1.id,
                          classroom_id=room.id, is_unplaced=False, is_locked=True)
    free = TimetableSlot(solution_id=sol.id, lesson_id=l1.id, day_of_week=0, period_id=p2.id,
                         classroom_id=room.id, is_unplaced=False)
    s.add_all([clash, free,
               TimetableSlot(solution_id=sol.id, lesson_id=l2.id, day_of_week=0, period_id=p1.id,
                             classroom_id=room.id, is_unplaced=False),
               # αρχειοθετημένο πρόγραμμα: ΔΕΝ μετράει
               TimetableSlot(solution_id=old.id, lesson_id=l1.id, day_of_week=1, period_id=p1.id,
                             classroom_id=room.id, is_unplaced=False),
               TimetableSlot(solution_id=old.id, lesson_id=l2.id, day_of_week=1, period_id=p1.id,
                             classroom_id=room.id, is_unplaced=False)])
    s.commit()
    app = FastAPI()
    app.include_router(lessons_router.router, prefix="/api/lessons")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.s, c.l1, c.clash, c.free = s, l1, clash, free
    c.ids = {"t1": t1.id, "t2": t2.id, "t3": t3.id, "c1": c1.id, "c2": c2.id, "c4": c4.id,
             "subj": subj.id, "p1": p1.id}
    yield c
    s.close()


def _body(env, **kw):
    b = {"subject_id": env.ids["subj"], "teacher_id": env.ids["t1"], "class_id": env.ids["c1"],
         "periods_per_week": 2}
    b.update(kw)
    return b


def test_new_teacher_busy_is_refused_and_nothing_changes(env):
    res = env.put(f"/api/lessons/{env.l1.id}", json=_body(env, teacher_id=env.ids["t2"]))
    assert res.status_code == 409
    d = res.json()["detail"]
    assert d["requires_force"] and [c["slot_id"] for c in d["conflicts"]] == [env.clash.id]
    assert "Τ2 διδάσκει ήδη ΧΗΜΕΙΑ (Γ2)" in d["message"] and "ΧΕΙΜΕΡΙΝΟ" in d["message"]
    env.s.refresh(env.l1)
    assert env.l1.teacher_id == env.ids["t1"]


def test_force_changes_teacher_and_moves_only_the_clash_to_palette(env):
    res = env.put(f"/api/lessons/{env.l1.id}?force=true", json=_body(env, teacher_id=env.ids["t2"]))
    assert res.status_code == 200, res.text
    env.s.refresh(env.l1), env.s.refresh(env.clash), env.s.refresh(env.free)
    assert env.l1.teacher_id == env.ids["t2"]
    assert env.clash.is_unplaced and not env.clash.is_locked
    assert not env.free.is_unplaced                                 # η ελεύθερη ώρα μένει
    (h,) = env.s.query(TimetableSlotHistory).filter(TimetableSlotHistory.slot_id == env.clash.id).all()
    assert h.operation == "unplace" and h.prev_is_locked is True    # το ↩️ ξαναβάζει και το 🔒


def test_free_teacher_or_same_people_save_normally(env):
    assert env.put(f"/api/lessons/{env.l1.id}", json=_body(env, periods_per_week=3)).status_code == 200
    assert env.put(f"/api/lessons/{env.l1.id}", json=_body(env, teacher_id=env.ids["t3"],
                                                              periods_per_week=3)).status_code == 200
    env.s.refresh(env.clash)
    assert not env.clash.is_unplaced


def test_teacher_unavailability_counts(env):
    env.s.add(TeacherAvailability(teacher_id=env.ids["t3"], day_of_week=0, period_id=env.ids["p1"],
                                  status="unavailable", term_id=env.l1.term_id))
    env.s.commit()
    d = env.put(f"/api/lessons/{env.l1.id}", json=_body(env, teacher_id=env.ids["t3"])).json()["detail"]
    assert "κώλυμα" in d["message"]


def test_class_change_checks_class_and_shared_students(env):
    busy = env.put(f"/api/lessons/{env.l1.id}", json=_body(env, class_id=env.ids["c2"])).json()["detail"]
    assert "το τμήμα Γ2 έχει ήδη" in busy["message"]
    shared = env.put(f"/api/lessons/{env.l1.id}", json=_body(env, class_id=env.ids["c4"])).json()["detail"]
    assert "κοινοί μαθητές" in shared["message"] and "Παππάς Νίκος" in shared["message"]
