"""Tests for solver warm-start functionality.

A warm start lets the CP-SAT solver reuse the assignments from a prior
solution as hints (not hard constraints), which speeds up convergence
when only a small change has been made since the last run.

These tests verify:
  1. hints don't break the solver when there are none
  2. valid hints get applied (count surfaces in stats)
  3. invalid hints (lesson deleted, classroom changed) are silently skipped
  4. hints don't override hard constraints
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
    SchoolSettings,
    Subject,
    Teacher,
    TeacherAvailability,
)
from backend.solver.engine import TimetableSolver


@pytest.fixture()
def db():
    """Build a tiny solvable problem: 2 teachers, 2 classes, 1 subject,
    2 rooms, 4 periods × 5 days. Each (teacher, class) pair gets 1 hour."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    s.add(
        SchoolSettings(
            school_name="Test", days_per_week=5, institution_type="frontistirio"
        )
    )
    subj = Subject(name="M", short_name="M", color="#000")
    teachers = [Teacher(name=f"T{i}", short_name=f"T{i}", color="#000") for i in range(1, 3)]
    classes = [SchoolClass(name=f"C{i}", short_name=f"C{i}") for i in range(1, 3)]
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
        for i in range(1, 5)
    ]
    s.add_all([subj, *teachers, *classes, *rooms, *periods])
    s.commit()
    for o in [subj, *teachers, *classes, *rooms, *periods]:
        s.refresh(o)

    for t in teachers:
        for c in classes:
            s.add(
                Lesson(
                    subject_id=subj.id,
                    teacher_id=t.id,
                    class_id=c.id,
                    periods_per_week=1,
                    duration=1,
                )
            )
    s.commit()

    s.test_teachers = teachers
    s.test_classes = classes
    s.test_rooms = rooms
    s.test_periods = periods
    yield s
    s.close()


def _build_warm_start_from(db, lessons_subset=None):
    """Solve once, then return assignments to use as warm start hints."""
    solver = TimetableSolver(db, max_time_seconds=10)
    result = solver.solve()
    assert result.status in ("optimal", "feasible")
    slots = result.slots
    if lessons_subset is not None:
        slots = [s for s in slots if s["lesson_id"] in lessons_subset]
    return slots


def test_warm_start_with_empty_list_is_a_no_op(db):
    solver = TimetableSolver(db, max_time_seconds=10, warm_start_assignments=[])
    result = solver.solve()
    assert result.status in ("optimal", "feasible")
    assert result.stats["warm_start_hints_applied"] == 0


def test_warm_start_with_none_defaults_to_no_hints(db):
    solver = TimetableSolver(db, max_time_seconds=10, warm_start_assignments=None)
    result = solver.solve()
    assert result.status in ("optimal", "feasible")
    assert result.stats["warm_start_hints_applied"] == 0


def test_valid_warm_start_hints_get_applied(db):
    hints = _build_warm_start_from(db)
    assert len(hints) == 4  # 2 teachers × 2 classes × 1 hour each

    solver = TimetableSolver(db, max_time_seconds=10, warm_start_assignments=hints)
    result = solver.solve()
    assert result.status in ("optimal", "feasible")
    assert result.stats["warm_start_hints_applied"] == 4


def test_warm_start_hints_with_missing_keys_are_skipped(db):
    """Entries with None values in any key field shouldn't break the solver."""
    hints = [
        {"lesson_id": 1, "day_of_week": None, "period_id": 1, "classroom_id": 1},
        {"lesson_id": 1, "day_of_week": 0, "period_id": None, "classroom_id": 1},
    ]
    solver = TimetableSolver(db, max_time_seconds=10, warm_start_assignments=hints)
    result = solver.solve()
    assert result.status in ("optimal", "feasible")
    assert result.stats["warm_start_hints_applied"] == 0


def test_warm_start_skips_hints_for_nonexistent_xvars(db):
    """Hints pointing at lessons that no longer exist should be ignored."""
    hints = [
        {"lesson_id": 9999, "day_of_week": 0, "period_id": 1, "classroom_id": 1},
    ]
    solver = TimetableSolver(db, max_time_seconds=10, warm_start_assignments=hints)
    result = solver.solve()
    assert result.status in ("optimal", "feasible")
    assert result.stats["warm_start_hints_applied"] == 0


def test_warm_start_does_not_override_hard_constraints(db):
    """Even if a hint says 'put teacher T1 here', if T1 is unavailable
    on that day/period, the solver should NOT place the lesson there."""
    teachers = db.test_teachers
    periods = db.test_periods

    # Get an initial solution to use as warm start
    initial = _build_warm_start_from(db)
    # Find any one slot belonging to teacher T1 (lessons 1 and 2 are T1's)
    t1_lesson_ids = {1, 2}
    target = next(s for s in initial if s["lesson_id"] in t1_lesson_ids)
    locked_day = target["day_of_week"]
    locked_period = target["period_id"]

    # Now make T1 unavailable on that exact slot
    db.add(
        TeacherAvailability(
            teacher_id=teachers[0].id,
            day_of_week=locked_day,
            period_id=locked_period,
            status="unavailable",
        )
    )
    db.commit()

    solver = TimetableSolver(
        db, max_time_seconds=10, warm_start_assignments=initial
    )
    result = solver.solve()
    assert result.status in ("optimal", "feasible")

    # Verify no T1 lesson got placed at the now-unavailable slot
    for slot in result.slots:
        if slot["lesson_id"] in t1_lesson_ids:
            assert not (
                slot["day_of_week"] == locked_day
                and slot["period_id"] == locked_period
            ), "Warm-start hint should have been overridden by hard constraint"


def test_warm_start_works_alongside_locked_assignments(db):
    """locked_assignments (hard) + warm_start (hints) can coexist."""
    initial = _build_warm_start_from(db)
    # Lock first slot, hint the rest
    locked = [initial[0]]
    hints = initial[1:]

    solver = TimetableSolver(
        db,
        max_time_seconds=10,
        locked_assignments=locked,
        warm_start_assignments=hints,
    )
    result = solver.solve()
    assert result.status in ("optimal", "feasible")
    assert result.stats["warm_start_hints_applied"] == 3
    # The locked slot should still appear in the result
    locked_key = (
        locked[0]["lesson_id"],
        locked[0]["day_of_week"],
        locked[0]["period_id"],
        locked[0]["classroom_id"],
    )
    placed_keys = {
        (s["lesson_id"], s["day_of_week"], s["period_id"], s["classroom_id"])
        for s in result.slots
    }
    assert locked_key in placed_keys
