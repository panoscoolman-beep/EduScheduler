"""Tests for the parking-lot sync service.

When a new Lesson is created after solver runs already exist, those
runs need the lesson added as unplaced slots so the user can drag it
into place. The service handles this — these tests verify it.
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
    TimetableSolution,
)
from backend.services.parking_lot_sync import (
    add_lesson_to_open_solutions,
    add_lessons_to_open_solutions,
    sync_lesson_slot_count,
    UNPLACED_REASON,
)


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

    subj = Subject(name="Math", short_name="Μ", color="#000")
    teacher = Teacher(name="T", short_name="T", color="#000")
    cls = SchoolClass(name="A1", short_name="A1")
    room = Classroom(name="R1", short_name="R1")
    period = Period(
        name="1η", short_name="1", start_time="08:00",
        end_time="08:50", is_break=False, sort_order=1,
    )
    s.add_all([subj, teacher, cls, room, period])
    s.commit()
    for o in [subj, teacher, cls, room, period]:
        s.refresh(o)

    s.test_subject = subj
    s.test_teacher = teacher
    s.test_class = cls
    s.test_room = room
    s.test_period = period
    yield s
    s.close()


def _make_lesson(db, periods_per_week=3, distribution=None):
    lesson = Lesson(
        subject_id=db.test_subject.id,
        teacher_id=db.test_teacher.id,
        class_id=db.test_class.id,
        periods_per_week=periods_per_week,
        distribution=distribution,
        duration=1,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


def _make_solution(db, status="optimal"):
    sol = TimetableSolution(name=f"sol-{status}", status=status)
    db.add(sol)
    db.commit()
    db.refresh(sol)
    return sol


def test_no_solutions_means_no_slots_created(db):
    lesson = _make_lesson(db, periods_per_week=2)
    result = add_lesson_to_open_solutions(db, lesson.id)
    assert result["added_to"] == []
    assert result["skipped"] == []
    assert db.query(TimetableSlot).count() == 0


def test_creates_one_unplaced_slot_per_period_in_each_active_solution(db):
    sol1 = _make_solution(db, "optimal")
    sol2 = _make_solution(db, "feasible")
    lesson = _make_lesson(db, periods_per_week=4)

    result = add_lesson_to_open_solutions(db, lesson.id)
    assert len(result["added_to"]) == 2
    assert all(entry["slots_added"] == 4 for entry in result["added_to"])

    # Each solution has 4 unplaced slots for this lesson
    for sol in (sol1, sol2):
        slots = (
            db.query(TimetableSlot)
            .filter(
                TimetableSlot.solution_id == sol.id,
                TimetableSlot.lesson_id == lesson.id,
            )
            .all()
        )
        assert len(slots) == 4
        assert all(s.is_unplaced for s in slots)
        assert all(s.day_of_week is None for s in slots)
        assert all(s.unplaced_reason == UNPLACED_REASON for s in slots)


def test_skips_solutions_that_are_not_active(db):
    """generating / infeasible / draft solutions should NOT receive
    parking-lot slots."""
    _make_solution(db, "optimal")
    _make_solution(db, "infeasible")
    _make_solution(db, "draft")
    _make_solution(db, "generating")
    lesson = _make_lesson(db, periods_per_week=2)

    result = add_lesson_to_open_solutions(db, lesson.id)
    assert len(result["added_to"]) == 1  # only the optimal one
    assert db.query(TimetableSlot).count() == 2  # 2 hours × 1 active solution


def test_distribution_doesnt_change_parking_lot_count(db):
    """Even if distribution is '2,2', we still create 4 unplaced slots
    (one per hour) so manual placement is straightforward."""
    sol = _make_solution(db, "optimal")
    lesson = _make_lesson(db, periods_per_week=4, distribution="2,2")

    result = add_lesson_to_open_solutions(db, lesson.id)
    assert result["added_to"][0]["slots_added"] == 4
    slots = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == sol.id)
        .count()
    )
    assert slots == 4


def test_idempotent_when_lesson_already_present(db):
    """Calling twice for the same lesson must NOT double up the parking
    lot. The second call sees existing slots and skips."""
    sol = _make_solution(db, "optimal")
    lesson = _make_lesson(db, periods_per_week=3)

    add_lesson_to_open_solutions(db, lesson.id)
    second = add_lesson_to_open_solutions(db, lesson.id)

    assert second["added_to"] == []
    assert any(s["solution_id"] == sol.id for s in second["skipped"])
    assert (
        db.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == sol.id)
        .count()
        == 3
    )


def test_unknown_lesson_id_returns_empty_summary(db):
    _make_solution(db, "optimal")
    result = add_lesson_to_open_solutions(db, 9999)
    assert result == {"lesson_id": 9999, "added_to": [], "skipped": []}
    assert db.query(TimetableSlot).count() == 0


def test_bulk_helper_processes_each_lesson(db):
    _make_solution(db, "optimal")
    l1 = _make_lesson(db, periods_per_week=1)
    l2 = _make_lesson(db, periods_per_week=2)
    l3 = _make_lesson(db, periods_per_week=3)

    summaries = add_lessons_to_open_solutions(db, [l1.id, l2.id, l3.id])
    assert len(summaries) == 3
    # 1 + 2 + 3 = 6 slots
    assert db.query(TimetableSlot).count() == 6


def test_sync_increases_slot_count_when_periods_per_week_grows(db):
    """User edits a lesson from 2h/week to 4h/week → +2 unplaced
    slots in each active solution."""
    sol = _make_solution(db, "optimal")
    lesson = _make_lesson(db, periods_per_week=2)
    add_lesson_to_open_solutions(db, lesson.id)
    assert (
        db.query(TimetableSlot)
        .filter(TimetableSlot.lesson_id == lesson.id)
        .count()
        == 2
    )

    # User bumps to 4 hours
    lesson.periods_per_week = 4
    db.commit()

    result = sync_lesson_slot_count(db, lesson.id)
    assert result["target_periods_per_week"] == 4
    assert result["synced"][0]["added"] == 2
    assert result["synced"][0]["removed"] == 0

    slots = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.lesson_id == lesson.id)
        .all()
    )
    assert len(slots) == 4
    assert sum(1 for s in slots if s.is_unplaced) == 4


def test_sync_is_noop_when_count_matches(db):
    sol = _make_solution(db, "optimal")
    lesson = _make_lesson(db, periods_per_week=3)
    add_lesson_to_open_solutions(db, lesson.id)

    result = sync_lesson_slot_count(db, lesson.id)
    assert result["synced"] == []
    assert result["skipped"][0]["reason"] == "already_in_sync"
    assert (
        db.query(TimetableSlot)
        .filter(TimetableSlot.lesson_id == lesson.id)
        .count()
        == 3
    )


def test_sync_decreases_by_removing_unplaced_only(db):
    """User edits a lesson from 4h/week to 2h/week → 2 unplaced slots
    are removed, but placed slots are preserved."""
    sol = _make_solution(db, "optimal")
    lesson = _make_lesson(db, periods_per_week=4)
    add_lesson_to_open_solutions(db, lesson.id)

    # User has dragged 2 of the 4 slots onto the grid (placed)
    placed_ids = [
        s.id for s in db.query(TimetableSlot)
        .filter(TimetableSlot.lesson_id == lesson.id)
        .limit(2)
        .all()
    ]
    db.query(TimetableSlot).filter(TimetableSlot.id.in_(placed_ids)).update(
        {
            "day_of_week": 0,
            "period_id": db.test_period.id,
            "classroom_id": db.test_room.id,
            "is_unplaced": False,
            "unplaced_reason": None,
        },
        synchronize_session=False,
    )
    db.commit()

    # Now user reduces to 2h/week
    lesson.periods_per_week = 2
    db.commit()

    result = sync_lesson_slot_count(db, lesson.id)
    assert result["synced"][0]["removed"] == 2
    assert result["synced"][0]["surplus_placed"] == 0

    remaining = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.lesson_id == lesson.id)
        .all()
    )
    assert len(remaining) == 2
    # Both remaining slots should be the placed ones
    assert all(not s.is_unplaced for s in remaining)


def test_sync_preserves_placed_slots_when_unplaced_pool_too_small(db):
    """If user reduces ppw below the placed-slot count, we never
    delete placed slots — the surplus is reported instead."""
    sol = _make_solution(db, "optimal")
    lesson = _make_lesson(db, periods_per_week=3)
    add_lesson_to_open_solutions(db, lesson.id)

    # User placed all 3 slots — bulk update to satisfy CHECK constraint
    db.query(TimetableSlot).filter(TimetableSlot.lesson_id == lesson.id).update(
        {
            "day_of_week": 0,
            "period_id": db.test_period.id,
            "classroom_id": db.test_room.id,
            "is_unplaced": False,
            "unplaced_reason": None,
        },
        synchronize_session=False,
    )
    db.commit()

    # Reduce to 1 hour
    lesson.periods_per_week = 1
    db.commit()

    result = sync_lesson_slot_count(db, lesson.id)
    assert result["synced"][0]["removed"] == 0  # nothing in unplaced pool
    assert result["synced"][0]["surplus_placed"] == 2

    # All 3 placed slots survive — the user has to remove them manually
    assert (
        db.query(TimetableSlot)
        .filter(TimetableSlot.lesson_id == lesson.id)
        .count()
        == 3
    )


def test_sync_adds_to_solutions_that_lacked_the_lesson(db):
    """Lesson exists, sync called on a solution that has 0 slots for
    it — adds full ppw worth of unplaced slots."""
    sol_old = _make_solution(db, "optimal")
    lesson = _make_lesson(db, periods_per_week=2)
    add_lesson_to_open_solutions(db, lesson.id)

    sol_new = _make_solution(db, "feasible")  # newer solution, missing the lesson

    result = sync_lesson_slot_count(db, lesson.id)
    new_synced = next(
        (s for s in result["synced"] if s["solution_id"] == sol_new.id), None
    )
    assert new_synced is not None
    assert new_synced["added"] == 2

    new_slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.solution_id == sol_new.id,
            TimetableSlot.lesson_id == lesson.id,
        )
        .count()
    )
    assert new_slots == 2


def test_does_not_touch_existing_placed_slots_for_other_lessons(db):
    """Other lessons' placements must remain untouched."""
    sol = _make_solution(db, "optimal")
    other_lesson = _make_lesson(db, periods_per_week=1)
    db.add(
        TimetableSlot(
            solution_id=sol.id,
            lesson_id=other_lesson.id,
            day_of_week=0,
            period_id=db.test_period.id,
            classroom_id=db.test_room.id,
            is_unplaced=False,
        )
    )
    db.commit()

    new_lesson = _make_lesson(db, periods_per_week=2)
    add_lesson_to_open_solutions(db, new_lesson.id)

    # The original placed slot for `other_lesson` is intact
    placed = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.solution_id == sol.id,
            TimetableSlot.lesson_id == other_lesson.id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .one()
    )
    assert placed.day_of_week == 0
    # And new lesson got its 2 unplaced slots
    new_unplaced = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.solution_id == sol.id,
            TimetableSlot.lesson_id == new_lesson.id,
            TimetableSlot.is_unplaced == True,  # noqa: E712
        )
        .count()
    )
    assert new_unplaced == 2
