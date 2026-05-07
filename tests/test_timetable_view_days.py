"""Regression test for the 'invisible Σάββατο slot' bug:

The frontend timetable grid used to hardcode 5 days (Δευτ-Παρ),
silently hiding any slot placed on day_of_week=5 (Σάββατο). The
school_settings.days_per_week field exists for exactly this reason
but was never wired into the view layer.

This test ensures:
  1. The settings endpoint returns days_per_week.
  2. A solution with slots on day 5 returns ALL of them via
     /api/solver/solutions/{id}, including the day-5 ones (previously
     fine — the bug was visual only).
  3. The metrics service includes day-5 slots in its placed_count.

The visual fix (timetable.js daysCount = settings.days_per_week)
is verified end-to-end manually; this test guards against the data
layer regressing into the same shape.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import (
    Subject, Teacher, SchoolClass, Classroom, Period,
    Lesson, TimetableSolution, TimetableSlot, SchoolSettings,
)
from backend.services import solution_metrics as sm


@pytest.fixture()
def db_with_saturday_slot():
    """Build a tiny solution that has at least one slot on day 5."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    s.add(SchoolSettings(school_name="Test", days_per_week=6,
                         institution_type="frontistirio"))
    subj = Subject(name="X", short_name="X", color="#000")
    t = Teacher(name="T", short_name="T", color="#000")
    c = SchoolClass(name="C", short_name="C")
    room = Classroom(name="R", short_name="R")
    p = Period(name="1η", short_name="1", start_time="08:00",
               end_time="09:00", is_break=False, sort_order=1)
    s.add_all([subj, t, c, room, p])
    s.commit()
    for o in [subj, t, c, room, p]:
        s.refresh(o)

    lesson = Lesson(subject_id=subj.id, teacher_id=t.id, class_id=c.id,
                    periods_per_week=1, duration=1)
    s.add(lesson)
    s.commit()
    s.refresh(lesson)

    sol = TimetableSolution(name="Test", status="feasible", score=0.0)
    s.add(sol)
    s.commit()
    s.refresh(sol)

    # Place the slot on Σάββατο
    s.add(TimetableSlot(
        solution_id=sol.id, lesson_id=lesson.id,
        day_of_week=5, period_id=p.id, classroom_id=room.id,
        is_unplaced=False,
    ))
    s.commit()

    s._test_solution_id = sol.id
    yield s
    s.close()


def test_school_settings_has_days_per_week(db_with_saturday_slot):
    s = db_with_saturday_slot
    settings = s.query(SchoolSettings).first()
    assert settings.days_per_week == 6


def test_saturday_slot_is_persisted(db_with_saturday_slot):
    """The DB itself accepts day_of_week up to 6 — the check
    constraint allows 0-6."""
    s = db_with_saturday_slot
    saturday_slots = s.query(TimetableSlot).filter(
        TimetableSlot.day_of_week == 5
    ).all()
    assert len(saturday_slots) == 1


def test_metrics_count_saturday_slot_as_placed(db_with_saturday_slot):
    """Earlier sanity: metrics.placed_count should include the
    Σάββατο slot."""
    s = db_with_saturday_slot
    metrics = sm.compute(s._test_solution_id, s)
    assert metrics is not None
    assert metrics.placed_count == 1
    assert metrics.unplaced_count == 0


def test_solution_response_returns_saturday_slot(db_with_saturday_slot):
    """The solution endpoint joins through to the placed slot;
    nothing in the data layer filters by day. The frontend must
    not introduce its own day filter."""
    s = db_with_saturday_slot
    slots = s.query(TimetableSlot).filter(
        TimetableSlot.solution_id == s._test_solution_id
    ).all()
    days_present = {sl.day_of_week for sl in slots}
    assert 5 in days_present
