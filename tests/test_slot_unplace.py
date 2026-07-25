"""Tests for POST /solutions/{sid}/slots/{slot_id}/unplace.

Αφαίρεση τοποθετημένης ώρας πίσω στην Παλέτα: NULL θέση, is_unplaced,
history 'unplace' (ο μόνος τρόπος αφαίρεσης χωρίς solver), undo που
επαναφέρει την ώρα ακριβώς εκεί που ήταν.
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
    Subject,
    Teacher,
    TimetableSlot,
    TimetableSlotHistory,
    TimetableSolution,
)
from backend.routers import solver as solver_router
from backend.routers.solver import MANUAL_UNPLACE_REASON


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    subj = Subject(name="Μ", short_name="Μ", color="#000")
    teacher = Teacher(name="Τ", short_name="Τ", color="#000")
    cls = SchoolClass(name="Α1", short_name="Α1")
    room = Classroom(name="R1", short_name="R1", room_type="regular")
    period = Period(name="1η", short_name="1", start_time="08:00",
                    end_time="08:50", is_break=False, sort_order=1)
    s.add_all([subj, teacher, cls, room, period])
    s.commit()
    for o in [subj, teacher, cls, room, period]:
        s.refresh(o)

    lesson = Lesson(
        subject_id=subj.id, teacher_id=teacher.id, class_id=cls.id,
        periods_per_week=2, duration=1,
    )
    sol = TimetableSolution(name="t", status="optimal")
    s.add_all([lesson, sol])
    s.commit()
    s.refresh(lesson)
    s.refresh(sol)

    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.s = s
    client.sol = sol
    client.lesson = lesson
    client.room = room
    client.period = period
    yield client
    s.close()


def _slot(env, day=0, locked=False, unplaced=False):
    slot = TimetableSlot(
        solution_id=env.sol.id, lesson_id=env.lesson.id,
        day_of_week=None if unplaced else day,
        period_id=None if unplaced else env.period.id,
        classroom_id=None if unplaced else env.room.id,
        is_unplaced=unplaced, is_locked=locked,
    )
    env.s.add(slot)
    env.s.commit()
    env.s.refresh(slot)
    return slot


def _unplace(env, slot_id):
    return env.post(f"/api/solver/solutions/{env.sol.id}/slots/{slot_id}/unplace")


def test_unplace_nulls_position_and_sets_reason(env):
    slot = _slot(env, day=2)
    res = _unplace(env, slot.id)
    assert res.status_code == 200
    body = res.json()
    assert body["slot"]["is_unplaced"] is True
    assert body["slot"]["day_of_week"] is None

    env.s.refresh(slot)
    assert slot.is_unplaced is True
    assert slot.day_of_week is None
    assert slot.period_id is None
    assert slot.classroom_id is None
    assert slot.unplaced_reason == MANUAL_UNPLACE_REASON

    entry = env.s.query(TimetableSlotHistory).one()
    assert entry.operation == "unplace"


def test_unplace_refuses_locked_already_unplaced_and_missing(env):
    locked = _slot(env, locked=True)
    assert _unplace(env, locked.id).status_code == 400

    parked = _slot(env, unplaced=True)
    assert _unplace(env, parked.id).status_code == 400

    assert _unplace(env, 9999).status_code == 404


def test_undo_restores_exact_previous_position(env):
    slot = _slot(env, day=3)
    assert _unplace(env, slot.id).status_code == 200

    res = env.post(f"/api/solver/solutions/{env.sol.id}/undo")
    assert res.status_code == 200
    env.s.refresh(slot)
    assert slot.is_unplaced is False
    assert slot.day_of_week == 3
    assert slot.period_id == env.period.id
    assert slot.classroom_id == env.room.id
    assert slot.unplaced_reason is None


def test_unplaced_slot_can_be_replaced_via_normal_drop(env):
    """Πλήρης κύκλος: unplace → η ώρα ξανατοποθετείται με το κανονικό PUT
    (όπως όταν σέρνεται από την Παλέτα)."""
    slot = _slot(env, day=1)
    assert _unplace(env, slot.id).status_code == 200

    res = env.put(
        f"/api/solver/solutions/{env.sol.id}/slots/{slot.id}",
        json={"day_of_week": 4, "period_id": env.period.id},
    )
    assert res.status_code == 200
    env.s.refresh(slot)
    assert slot.is_unplaced is False
    assert slot.day_of_week == 4
