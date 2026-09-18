"""🅿️ Άδειασμα καθηγητή/τμήματος: όλες οι ώρες στην Παλέτα (όχι οι 🔒),
επαναφορά όλων μαζί με undo-to του πρώτου βήματος."""
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
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    subj = Subject(name="Φυσική", short_name="ΦΥΣ", color="#000000")
    t1, t2 = Teacher(name="Α", short_name="Α", color="#000000"), Teacher(name="Β", short_name="Β", color="#000000")
    c1, c2 = SchoolClass(name="Β2", short_name="Β2"), SchoolClass(name="Γ1", short_name="Γ1")
    room = Classroom(name="Αίθ", short_name="Α", room_type="regular")
    p = Period(name="1η", short_name="1η", start_time="14:00", end_time="15:00", is_break=False, sort_order=1)
    s.add_all([subj, t1, t2, c1, c2, room, p])
    s.commit()
    sol = TimetableSolution(name="Π", status="optimal")
    l1 = Lesson(subject_id=subj.id, teacher_id=t1.id, class_id=c1.id, periods_per_week=3)
    l2 = Lesson(subject_id=subj.id, teacher_id=t2.id, class_id=c2.id, periods_per_week=1)
    s.add_all([sol, l1, l2])
    s.commit()
    for day, locked in ((0, False), (1, False), (2, True)):
        s.add(TimetableSlot(solution_id=sol.id, lesson_id=l1.id, day_of_week=day, period_id=p.id,
                            classroom_id=room.id, is_unplaced=False, is_locked=locked))
    s.add(TimetableSlot(solution_id=sol.id, lesson_id=l2.id, day_of_week=3, period_id=p.id,
                        classroom_id=room.id, is_unplaced=False))
    s.commit()
    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session, c.sol, c.t1, c.c1, c.l1, c.l2 = s, sol, t1, c1, l1, l2
    yield c
    s.close()


def _state(env, lesson_id):
    rows = [(s.day_of_week, s.is_unplaced, s.is_locked)
            for s in env.session.query(TimetableSlot).filter(TimetableSlot.lesson_id == lesson_id)]
    return sorted(rows, key=lambda r: (-1 if r[0] is None else r[0], r[1], r[2]))


def test_empty_a_teacher_keeps_locked_and_touches_nobody_else(env):
    res = env.post(f"/api/solver/solutions/{env.sol.id}/unplace-bulk", json={"teacher_id": env.t1.id}).json()
    assert (res["unplaced"], res["skipped_locked"]) == (2, 1)
    assert "1 κλειδωμένες" in res["message"]
    env.session.expire_all()
    l1 = _state(env, env.l1.id)
    assert sum(1 for d, u, _ in l1 if u) == 2 and (2, False, True) in l1           # η 🔒 έμεινε
    assert _state(env, env.l2.id) == [(3, False, False)]                           # άλλος καθηγητής: ανέγγιχτος
    assert res["history"]["can_undo"] == 2


def test_restore_all_puts_everything_back_exactly(env):
    before = _state(env, env.l1.id)
    res = env.post(f"/api/solver/solutions/{env.sol.id}/unplace-bulk", json={"class_id": env.c1.id}).json()
    back = env.post(f"/api/solver/solutions/{env.sol.id}/history/undo-to/{res['first_entry_id']}").json()
    assert back["undone"] == 2
    env.session.expire_all()
    assert _state(env, env.l1.id) == before


def test_exactly_one_target_is_required(env):
    url = f"/api/solver/solutions/{env.sol.id}/unplace-bulk"
    assert env.post(url, json={}).status_code == 422
    assert env.post(url, json={"teacher_id": env.t1.id, "class_id": env.c1.id}).status_code == 422
    assert env.post("/api/solver/solutions/999/unplace-bulk", json={"teacher_id": 1}).status_code == 404
    nothing = env.post(url, json={"teacher_id": 999}).json()
    assert nothing["unplaced"] == 0 and nothing["first_entry_id"] is None
