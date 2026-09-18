"""🧩 «Γέμισε τα κενά»: regenerate με ΟΛΕΣ τις τοποθετημένες ώρες σταθερές,
permissive, σε νέο πρόγραμμα. Ο solver αντικαθίσταται από καταγραφή."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, Subject, Teacher, TimetableSlot, TimetableSolution,
)
from backend.routers import solver as solver_router


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    subj = Subject(name="Φ", short_name="Φ", color="#000000")
    t = Teacher(name="Τ", short_name="Τ", color="#000000")
    c = SchoolClass(name="Β2", short_name="Β2")
    r = Classroom(name="Α", short_name="Α", room_type="regular")
    p = Period(name="1η", short_name="1η", start_time="14:00", end_time="15:00", is_break=False, sort_order=1)
    s.add_all([subj, t, c, r, p])
    s.commit()
    src = TimetableSolution(name="ΧΕΙΜΕΡΙΝΟ", status="optimal")
    lesson = Lesson(subject_id=subj.id, teacher_id=t.id, class_id=c.id, periods_per_week=3)
    s.add_all([src, lesson])
    s.commit()
    s.add_all([
        TimetableSlot(solution_id=src.id, lesson_id=lesson.id, day_of_week=0, period_id=p.id,
                      classroom_id=r.id, is_unplaced=False, is_locked=True),
        TimetableSlot(solution_id=src.id, lesson_id=lesson.id, day_of_week=1, period_id=p.id,
                      classroom_id=r.id, is_unplaced=False, is_locked=False),
        TimetableSlot(solution_id=src.id, lesson_id=lesson.id, is_unplaced=True),
    ])
    s.commit()
    runs = []
    monkeypatch.setattr(solver_router, "_run_generation_job", lambda *a: runs.append(a))
    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.session, client.src, client.runs = s, src, runs
    yield client
    s.close()


def test_fill_gaps_fixes_every_placed_hour_and_forces_permissive(env):
    res = env.post(f"/api/solver/regenerate/{env.src.id}",
                   json={"name": "Συμπλήρωση", "mode": "strict", "lock_all_placed": True})
    assert res.status_code == 200, res.text
    ((solution_id, _max_t, mode, warm, locked, meta),) = env.runs
    assert mode == "permissive"                                   # ό,τι δεν χωρά → Παλέτα
    assert sorted(a["day_of_week"] for a in locked) == [0, 1]     # ΚΑΙ η μη κλειδωμένη
    assert meta == {"locked_from_solution": env.src.id, "locked_count": 2, "fill_gaps": True}
    new = env.session.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    assert new.name == "Συμπλήρωση" and new.id != env.src.id      # νέο πρόγραμμα, όχι αλλαγή


def test_plain_lock_and_regenerate_is_unchanged(env):
    env.post(f"/api/solver/regenerate/{env.src.id}", json={"name": "v2", "mode": "strict"})
    ((_, _, mode, _, locked, meta),) = env.runs
    assert mode == "strict" and [a["day_of_week"] for a in locked] == [0] and meta["fill_gaps"] is False
