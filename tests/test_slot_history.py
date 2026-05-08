"""Tests for the slot edit history (undo/redo) service.

Covers the standard editor semantics: record → undo → redo, plus the
"new edit invalidates the redo path" rule that every text editor uses.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
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
from backend.services import slot_history as svc


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

    subj = Subject(name="M", short_name="M", color="#000")
    teacher = Teacher(name="T", short_name="T", color="#000")
    cls = SchoolClass(name="C", short_name="C")
    rooms = [Classroom(name=f"R{i}", short_name=f"R{i}") for i in range(1, 3)]
    periods = [
        Period(
            name=f"{i}η",
            short_name=str(i),
            start_time=f"{7+i:02d}:00",
            end_time=f"{7+i:02d}:50",
            is_break=False,
            sort_order=i,
        )
        for i in range(1, 4)
    ]
    s.add_all([subj, teacher, cls, *rooms, *periods])
    s.commit()
    for o in [subj, teacher, cls, *rooms, *periods]:
        s.refresh(o)

    lesson = Lesson(
        subject_id=subj.id,
        teacher_id=teacher.id,
        class_id=cls.id,
        periods_per_week=1,
        duration=1,
    )
    s.add(lesson)
    s.commit()
    s.refresh(lesson)

    sol = TimetableSolution(name="test-sol", status="feasible")
    s.add(sol)
    s.commit()
    s.refresh(sol)

    slot = TimetableSlot(
        solution_id=sol.id,
        lesson_id=lesson.id,
        day_of_week=0,
        period_id=periods[0].id,
        classroom_id=rooms[0].id,
        is_locked=False,
        is_unplaced=False,
    )
    s.add(slot)
    s.commit()
    s.refresh(slot)

    s.test_solution = sol
    s.test_slot = slot
    s.test_periods = periods
    s.test_rooms = rooms
    yield s
    s.close()


def _move(db, slot, day, period, room):
    """Helper: change a slot in-place and record history."""
    prev = {
        "day_of_week": slot.day_of_week,
        "period_id": slot.period_id,
        "classroom_id": slot.classroom_id,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": bool(slot.is_unplaced),
    }
    slot.day_of_week = day
    slot.period_id = period
    slot.classroom_id = room
    new = {
        "day_of_week": slot.day_of_week,
        "period_id": slot.period_id,
        "classroom_id": slot.classroom_id,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": bool(slot.is_unplaced),
    }
    return svc.record_edit(db, slot, prev, new)


def test_record_edit_appends_history_row(db):
    slot = db.test_slot
    p2 = db.test_periods[1].id

    _move(db, slot, day=1, period=p2, room=db.test_rooms[1].id)
    db.commit()

    rows = db.query(TimetableSlotHistory).all()
    assert len(rows) == 1
    assert rows[0].slot_id == slot.id
    assert rows[0].prev_day_of_week == 0
    assert rows[0].new_day_of_week == 1
    assert rows[0].undone is False


def test_undo_reverts_slot_to_prev_state(db):
    slot = db.test_slot
    p2 = db.test_periods[1].id
    p1 = db.test_periods[0].id
    r2 = db.test_rooms[1].id
    r1 = db.test_rooms[0].id

    _move(db, slot, 1, p2, r2)
    db.commit()
    db.refresh(slot)

    entry = svc.undo(db, db.test_solution.id)
    db.commit()
    db.refresh(slot)

    assert entry is not None
    assert slot.day_of_week == 0
    assert slot.period_id == p1
    assert slot.classroom_id == r1
    assert entry.undone is True


def test_redo_reapplies_undone_edit(db):
    slot = db.test_slot
    p2 = db.test_periods[1].id
    r2 = db.test_rooms[1].id

    _move(db, slot, 1, p2, r2)
    db.commit()

    svc.undo(db, db.test_solution.id)
    db.commit()
    db.refresh(slot)
    assert slot.day_of_week == 0  # back to prev

    svc.redo(db, db.test_solution.id)
    db.commit()
    db.refresh(slot)

    assert slot.day_of_week == 1
    assert slot.period_id == p2
    assert slot.classroom_id == r2


def test_undo_returns_none_when_no_history(db):
    assert svc.undo(db, db.test_solution.id) is None


def test_redo_returns_none_when_no_undone_entry(db):
    slot = db.test_slot
    _move(db, slot, 1, db.test_periods[1].id, db.test_rooms[1].id)
    db.commit()
    # Nothing has been undone yet
    assert svc.redo(db, db.test_solution.id) is None


def test_new_edit_after_undo_invalidates_redo_path(db):
    """Standard editor convention: if you undo, then make a new edit,
    you can't redo to the previously-undone branch — those rows are
    deleted."""
    slot = db.test_slot
    p1 = db.test_periods[0].id
    p2 = db.test_periods[1].id
    p3 = db.test_periods[2].id
    r1 = db.test_rooms[0].id
    r2 = db.test_rooms[1].id

    _move(db, slot, 1, p2, r2)  # edit A
    db.commit()
    svc.undo(db, db.test_solution.id)  # undo A → slot back to prev
    db.commit()
    db.refresh(slot)
    _move(db, slot, 2, p3, r1)  # edit B (new branch)
    db.commit()

    # The undone tail (edit A) should have been removed
    rows = db.query(TimetableSlotHistory).order_by(
        TimetableSlotHistory.id.asc()
    ).all()
    assert len(rows) == 1
    assert rows[0].new_day_of_week == 2  # only edit B survives
    assert svc.redo(db, db.test_solution.id) is None  # no redo branch


def test_multiple_undos_and_redos_walk_the_chain(db):
    slot = db.test_slot
    p1, p2, p3 = (db.test_periods[i].id for i in range(3))
    r1 = db.test_rooms[0].id

    _move(db, slot, 1, p2, r1)  # edit 1
    db.commit()
    _move(db, slot, 2, p3, r1)  # edit 2
    db.commit()
    db.refresh(slot)
    assert slot.day_of_week == 2

    svc.undo(db, db.test_solution.id)  # back to edit 1's result
    db.commit()
    db.refresh(slot)
    assert slot.day_of_week == 1

    svc.undo(db, db.test_solution.id)  # back to original
    db.commit()
    db.refresh(slot)
    assert slot.day_of_week == 0

    svc.redo(db, db.test_solution.id)
    db.commit()
    db.refresh(slot)
    assert slot.day_of_week == 1

    svc.redo(db, db.test_solution.id)
    db.commit()
    db.refresh(slot)
    assert slot.day_of_week == 2


def test_history_summary_counts_correctly(db):
    slot = db.test_slot
    p2 = db.test_periods[1].id
    r2 = db.test_rooms[1].id

    summary = svc.history_summary(db, db.test_solution.id)
    assert summary == {"can_undo": 0, "can_redo": 0, "total": 0}

    _move(db, slot, 1, p2, r2)
    db.commit()
    _move(db, slot, 2, p2, r2)
    db.commit()
    summary = svc.history_summary(db, db.test_solution.id)
    assert summary == {"can_undo": 2, "can_redo": 0, "total": 2}

    svc.undo(db, db.test_solution.id)
    db.commit()
    summary = svc.history_summary(db, db.test_solution.id)
    assert summary == {"can_undo": 1, "can_redo": 1, "total": 2}


def test_history_is_solution_scoped(db):
    """Edits on solution A must not be undoable from solution B."""
    other = TimetableSolution(name="other", status="feasible")
    db.add(other)
    db.commit()
    db.refresh(other)

    slot = db.test_slot
    _move(db, slot, 1, db.test_periods[1].id, db.test_rooms[1].id)
    db.commit()

    # Undo on the OTHER solution finds nothing
    assert svc.undo(db, other.id) is None
    # Undo on the original solution still works
    assert svc.undo(db, db.test_solution.id) is not None
