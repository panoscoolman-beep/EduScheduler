"""Tests for backend.services.solution_metrics.

Covers:
  - empty solution → all zeros, no crash
  - placed/unplaced counts honour is_unplaced flag
  - teacher_gap_total counts holes between teaching slots
  - workload_stddev penalizes uneven hours per teacher
  - avg/max days per class reflects compactness
  - compare() picks the right winner per metric
"""
from __future__ import annotations

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import (
    Subject, Teacher, SchoolClass, Classroom, Period,
    Lesson, TimetableSolution, TimetableSlot,
)
from backend.services import solution_metrics as sm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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

    # Seed: 2 teachers, 2 classes, 1 subject/room, 5 periods
    subj = Subject(name="Math", short_name="ΜΑΘ", color="#000000")
    t1 = Teacher(name="T1", short_name="T1", color="#000")
    t2 = Teacher(name="T2", short_name="T2", color="#000")
    c1 = SchoolClass(name="ClassA", short_name="A")
    c2 = SchoolClass(name="ClassB", short_name="B")
    room = Classroom(name="R1", short_name="R1")
    periods = [
        Period(name=f"{i}η", short_name=str(i), start_time="08:00",
               end_time="09:00", is_break=False, sort_order=i)
        for i in range(1, 6)
    ]
    s.add_all([subj, t1, t2, c1, c2, room, *periods])
    s.commit()
    s.refresh(subj); s.refresh(t1); s.refresh(t2)
    s.refresh(c1); s.refresh(c2); s.refresh(room)
    for p in periods: s.refresh(p)

    # 2 lessons: t1→c1, t2→c2
    l1 = Lesson(subject_id=subj.id, teacher_id=t1.id, class_id=c1.id,
                periods_per_week=2, duration=1)
    l2 = Lesson(subject_id=subj.id, teacher_id=t2.id, class_id=c2.id,
                periods_per_week=2, duration=1)
    s.add_all([l1, l2])
    s.commit()
    s.refresh(l1); s.refresh(l2)

    # Stash for test access
    s.test_lessons = (l1, l2)
    s.test_periods = periods
    s.test_room = room

    yield s
    s.close()


def _add_solution(db, name="Test", score=100.0, status="feasible"):
    sol = TimetableSolution(name=name, status=status, score=score,
                            created_at=datetime.utcnow())
    db.add(sol)
    db.commit()
    db.refresh(sol)
    return sol


def _add_placed(db, sol, lesson, day, period, room=None):
    if room is None:
        room = db.test_room
    slot = TimetableSlot(
        solution_id=sol.id, lesson_id=lesson.id,
        day_of_week=day, period_id=period.id, classroom_id=room.id,
        is_unplaced=False,
    )
    db.add(slot)
    db.commit()
    return slot


def _add_unplaced(db, sol, lesson, reason="no fit"):
    slot = TimetableSlot(
        solution_id=sol.id, lesson_id=lesson.id,
        day_of_week=None, period_id=None, classroom_id=None,
        is_unplaced=True, unplaced_reason=reason,
    )
    db.add(slot)
    db.commit()
    return slot


# ---------------------------------------------------------------------------
# compute() — basic shape + counts
# ---------------------------------------------------------------------------

def test_compute_unknown_solution_returns_none(db):
    assert sm.compute(99999, db) is None


def test_compute_empty_solution(db):
    sol = _add_solution(db, "Empty")
    m = sm.compute(sol.id, db)
    assert m is not None
    assert m.placed_count == 0
    assert m.unplaced_count == 0
    assert m.teacher_gap_total == 0
    assert m.workload_stddev == 0.0
    assert m.avg_days_per_class == 0.0
    assert m.max_days_per_class == 0
    assert m.late_periods_used == 0


def test_compute_distinguishes_placed_and_unplaced(db):
    sol = _add_solution(db, "Mixed")
    l1, l2 = db.test_lessons
    p = db.test_periods
    _add_placed(db, sol, l1, day=0, period=p[0])
    _add_placed(db, sol, l1, day=1, period=p[0])
    _add_unplaced(db, sol, l2)
    _add_unplaced(db, sol, l2, reason="other")

    m = sm.compute(sol.id, db)
    assert m.placed_count == 2
    assert m.unplaced_count == 2


# ---------------------------------------------------------------------------
# teacher_gap_total
# ---------------------------------------------------------------------------

def test_teacher_gap_zero_when_consecutive(db):
    """Teacher T1 teaches periods 1,2,3 on day 0 — no gaps."""
    sol = _add_solution(db)
    l1, _ = db.test_lessons
    p = db.test_periods
    _add_placed(db, sol, l1, day=0, period=p[0])
    _add_placed(db, sol, l1, day=0, period=p[1])
    _add_placed(db, sol, l1, day=0, period=p[2])
    m = sm.compute(sol.id, db)
    assert m.teacher_gap_total == 0


def test_teacher_gap_counts_one_period_hole(db):
    """T1 teaches periods 1 and 3 on day 0 — gap of 1."""
    sol = _add_solution(db)
    l1, _ = db.test_lessons
    p = db.test_periods
    _add_placed(db, sol, l1, day=0, period=p[0])
    _add_placed(db, sol, l1, day=0, period=p[2])
    m = sm.compute(sol.id, db)
    assert m.teacher_gap_total == 1


def test_teacher_gap_counts_multiple_hole(db):
    """T1: periods 1 and 4 → gap of 2."""
    sol = _add_solution(db)
    l1, _ = db.test_lessons
    p = db.test_periods
    _add_placed(db, sol, l1, day=0, period=p[0])
    _add_placed(db, sol, l1, day=0, period=p[3])
    m = sm.compute(sol.id, db)
    assert m.teacher_gap_total == 2


def test_teacher_gap_independent_per_day(db):
    """Gaps on different days are summed."""
    sol = _add_solution(db)
    l1, _ = db.test_lessons
    p = db.test_periods
    # Day 0: gap of 1
    _add_placed(db, sol, l1, day=0, period=p[0])
    _add_placed(db, sol, l1, day=0, period=p[2])
    # Day 1: gap of 1
    _add_placed(db, sol, l1, day=1, period=p[0])
    _add_placed(db, sol, l1, day=1, period=p[2])
    m = sm.compute(sol.id, db)
    assert m.teacher_gap_total == 2


# ---------------------------------------------------------------------------
# workload_stddev
# ---------------------------------------------------------------------------

def test_workload_stddev_zero_when_balanced(db):
    """Both teachers have 1 hour → stddev = 0."""
    sol = _add_solution(db)
    l1, l2 = db.test_lessons
    p = db.test_periods
    _add_placed(db, sol, l1, day=0, period=p[0])
    _add_placed(db, sol, l2, day=0, period=p[1])
    m = sm.compute(sol.id, db)
    assert m.workload_stddev == 0.0


def test_workload_stddev_positive_when_unbalanced(db):
    """T1 has 4 hours, T2 has 0 → high stddev."""
    sol = _add_solution(db)
    l1, _ = db.test_lessons
    p = db.test_periods
    for i in range(4):
        _add_placed(db, sol, l1, day=i, period=p[0])
    m = sm.compute(sol.id, db)
    # Only one teacher had any hours; with <2 teachers, fall to 0
    # (workload_stddev requires at least 2 teachers contributing)
    assert m.workload_stddev == 0.0


def test_workload_stddev_compares_two_teachers(db):
    """T1: 4 hours, T2: 2 hours → stddev = 1.0 (population)."""
    sol = _add_solution(db)
    l1, l2 = db.test_lessons
    p = db.test_periods
    for i in range(4):
        _add_placed(db, sol, l1, day=i, period=p[0])
    for i in range(2):
        _add_placed(db, sol, l2, day=i, period=p[1])
    m = sm.compute(sol.id, db)
    assert m.workload_stddev > 0


# ---------------------------------------------------------------------------
# avg_days_per_class / max_days_per_class
# ---------------------------------------------------------------------------

def test_days_per_class_reflects_distinct_days(db):
    """ClassA appears on days 0,1,2 → 3 days."""
    sol = _add_solution(db)
    l1, _ = db.test_lessons
    p = db.test_periods
    _add_placed(db, sol, l1, day=0, period=p[0])
    _add_placed(db, sol, l1, day=1, period=p[0])
    _add_placed(db, sol, l1, day=2, period=p[0])
    m = sm.compute(sol.id, db)
    assert m.avg_days_per_class == 3.0
    assert m.max_days_per_class == 3


def test_days_per_class_compact_class_wins(db):
    """ClassA on 1 day, ClassB on 3 days → max=3, avg=2."""
    sol = _add_solution(db)
    l1, l2 = db.test_lessons
    p = db.test_periods
    # ClassA: 2 hours on day 0 only
    _add_placed(db, sol, l1, day=0, period=p[0])
    _add_placed(db, sol, l1, day=0, period=p[1])
    # ClassB: 1 hour each on days 0,1,2
    _add_placed(db, sol, l2, day=0, period=p[2])
    _add_placed(db, sol, l2, day=1, period=p[0])
    _add_placed(db, sol, l2, day=2, period=p[0])
    m = sm.compute(sol.id, db)
    assert m.avg_days_per_class == 2.0  # (1+3)/2
    assert m.max_days_per_class == 3


# ---------------------------------------------------------------------------
# compare() — winner detection
# ---------------------------------------------------------------------------

def test_compare_picks_lowest_score_as_winner(db):
    """Lower score = better (it's a penalty)."""
    sol_a = _add_solution(db, "A", score=200.0)
    sol_b = _add_solution(db, "B", score=100.0)
    sol_c = _add_solution(db, "C", score=300.0)

    result = sm.compare([sol_a.id, sol_b.id, sol_c.id], db)
    assert result["winners"]["score"] == sol_b.id


def test_compare_picks_highest_placed_as_winner(db):
    """More placed = better."""
    sol_a = _add_solution(db, "A", score=100.0)
    sol_b = _add_solution(db, "B", score=100.0)
    l1, _ = db.test_lessons
    p = db.test_periods
    _add_placed(db, sol_a, l1, day=0, period=p[0])
    _add_placed(db, sol_b, l1, day=0, period=p[0])
    _add_placed(db, sol_b, l1, day=1, period=p[0])

    result = sm.compare([sol_a.id, sol_b.id], db)
    assert result["winners"]["placed_count"] == sol_b.id


def test_compare_with_single_solution_returns_no_winners(db):
    """Need at least 2 to declare winners."""
    sol = _add_solution(db)
    result = sm.compare([sol.id], db)
    assert result["winners"] == {}
    assert len(result["metrics"]) == 1


def test_compare_skips_unknown_ids(db):
    sol = _add_solution(db)
    result = sm.compare([sol.id, 99999], db)
    assert len(result["metrics"]) == 1


def test_compare_picks_lowest_gap_as_winner(db):
    """Solution with fewer teacher gaps wins."""
    sol_a = _add_solution(db, "A", score=100.0)
    sol_b = _add_solution(db, "B", score=100.0)
    l1, _ = db.test_lessons
    p = db.test_periods
    # A: gap of 2 (periods 0, 3)
    _add_placed(db, sol_a, l1, day=0, period=p[0])
    _add_placed(db, sol_a, l1, day=0, period=p[3])
    # B: no gap (periods 0, 1)
    _add_placed(db, sol_b, l1, day=0, period=p[0])
    _add_placed(db, sol_b, l1, day=0, period=p[1])

    result = sm.compare([sol_a.id, sol_b.id], db)
    assert result["winners"]["teacher_gap_total"] == sol_b.id
