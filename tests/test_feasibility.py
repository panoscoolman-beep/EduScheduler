"""Tests for the pre-solve feasibility check service.

These tests verify the arithmetic-only checks γίνονται σωστά πριν
καλέσουμε τον CP-SAT solver — δηλαδή να εντοπίζουμε over-constrained
προβλήματα σε ms αντί να περιμένουμε 30s.
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
    Student,
    StudentAvailability,
    StudentClassEnrollment,
    Subject,
    Teacher,
    TeacherAvailability,
)
from backend.services.feasibility import check_feasibility


@pytest.fixture()
def db():
    """Empty in-memory DB. Each test seeds what it needs."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _seed_minimal(db, days_per_week=5, n_periods=6, n_rooms=2):
    """Seed a small but solvable problem: 1 teacher, 1 class, 1 subject."""
    db.add(
        SchoolSettings(
            school_name="T", days_per_week=days_per_week, institution_type="frontistirio"
        )
    )
    subj = Subject(name="Math", short_name="ΜΑΘ", color="#000")
    teacher = Teacher(name="Νικολάου", short_name="ΓΝ", color="#000")
    cls = SchoolClass(name="A1", short_name="A1")
    rooms = [
        Classroom(name=f"R{i}", short_name=f"R{i}", room_type="regular")
        for i in range(1, n_rooms + 1)
    ]
    periods = [
        Period(
            name=f"{i}η",
            short_name=str(i),
            start_time=f"{7+i:02d}:00",
            end_time=f"{7+i:02d}:50",
            is_break=False,
            sort_order=i,
        )
        for i in range(1, n_periods + 1)
    ]
    db.add_all([subj, teacher, cls, *rooms, *periods])
    db.commit()
    for o in [subj, teacher, cls, *rooms, *periods]:
        db.refresh(o)
    return {"subject": subj, "teacher": teacher, "class": cls, "rooms": rooms, "periods": periods}


def test_empty_db_reports_errors_and_not_feasible(db):
    report = check_feasibility(db)
    assert report.feasible is False
    assert any("καθηγητές" in e for e in report.errors)
    assert any("τάξεις" in e for e in report.errors)
    assert any("μαθήματα" in e for e in report.errors)


def test_minimal_setup_is_feasible(db):
    seed = _seed_minimal(db)
    db.add(
        Lesson(
            subject_id=seed["subject"].id,
            teacher_id=seed["teacher"].id,
            class_id=seed["class"].id,
            periods_per_week=4,
            duration=1,
        )
    )
    db.commit()

    report = check_feasibility(db)
    assert report.feasible is True
    assert report.errors == []
    assert report.stats["total_lessons"] == 1
    assert report.stats["total_periods_needed"] == 4
    assert report.stats["total_slots_available"] == 5 * 6 * 2  # 60


def test_global_overload_flagged_as_error(db):
    seed = _seed_minimal(db, days_per_week=5, n_periods=2, n_rooms=1)
    # capacity = 5×2×1 = 10, demand = 11
    db.add(
        Lesson(
            subject_id=seed["subject"].id,
            teacher_id=seed["teacher"].id,
            class_id=seed["class"].id,
            periods_per_week=11,
            duration=1,
        )
    )
    db.commit()

    report = check_feasibility(db)
    assert report.feasible is False
    assert any("Δεν επαρκούν" in e for e in report.errors)


def test_high_load_warns_above_85pct(db):
    seed = _seed_minimal(db, days_per_week=5, n_periods=4, n_rooms=1)
    # capacity = 20, demand = 18 → 90% load
    db.add(
        Lesson(
            subject_id=seed["subject"].id,
            teacher_id=seed["teacher"].id,
            class_id=seed["class"].id,
            periods_per_week=18,
            duration=1,
        )
    )
    db.commit()

    report = check_feasibility(db)
    # capacity = 20, but class needs 18 hours → also class warning at 90%.
    # The global load warning should still trigger since 18/20 = 0.9 > 0.85.
    assert report.feasible is True
    assert any("Υψηλή πληρότητα" in w for w in report.warnings)


def test_teacher_overloaded_by_max_periods_per_day(db):
    seed = _seed_minimal(db, days_per_week=5, n_periods=6, n_rooms=2)
    teacher = seed["teacher"]
    teacher.max_periods_per_day = 2  # cap him at 2 hours/day → 10/week max
    db.commit()

    db.add(
        Lesson(
            subject_id=seed["subject"].id,
            teacher_id=teacher.id,
            class_id=seed["class"].id,
            periods_per_week=15,  # more than the 10 his cap allows
            duration=1,
        )
    )
    db.commit()

    report = check_feasibility(db)
    assert report.feasible is False
    assert any(teacher.name in e and "10" in e for e in report.errors)


def test_teacher_overloaded_by_unavailability(db):
    seed = _seed_minimal(db)
    teacher = seed["teacher"]
    # Make teacher unavailable on most slots (5 days × 6 periods = 30 total)
    # leaving only 4 slots free.
    for d in range(5):
        for p_idx, p in enumerate(seed["periods"]):
            if d == 0 and p_idx < 4:  # leave first 4 of Monday open
                continue
            db.add(
                TeacherAvailability(
                    teacher_id=teacher.id,
                    day_of_week=d,
                    period_id=p.id,
                    status="unavailable",
                )
            )
    db.commit()

    db.add(
        Lesson(
            subject_id=seed["subject"].id,
            teacher_id=teacher.id,
            class_id=seed["class"].id,
            periods_per_week=10,  # but only 4 slots free
            duration=1,
        )
    )
    db.commit()

    report = check_feasibility(db)
    assert report.feasible is False


def test_class_overloaded_by_total_periods(db):
    seed = _seed_minimal(db, days_per_week=5, n_periods=4, n_rooms=3)
    # class capacity = 5×4 = 20, demand = 25 → fail even though
    # global capacity (60) is fine.
    # Need multiple teachers so we don't trip teacher capacity first.
    t2 = Teacher(name="T2", short_name="T2", color="#000")
    t3 = Teacher(name="T3", short_name="T3", color="#000")
    db.add_all([t2, t3])
    db.commit()
    db.refresh(t2)
    db.refresh(t3)

    db.add_all(
        [
            Lesson(
                subject_id=seed["subject"].id,
                teacher_id=seed["teacher"].id,
                class_id=seed["class"].id,
                periods_per_week=10,
                duration=1,
            ),
            Lesson(
                subject_id=seed["subject"].id,
                teacher_id=t2.id,
                class_id=seed["class"].id,
                periods_per_week=10,
                duration=1,
            ),
            Lesson(
                subject_id=seed["subject"].id,
                teacher_id=t3.id,
                class_id=seed["class"].id,
                periods_per_week=5,
                duration=1,
            ),
        ]
    )
    db.commit()

    report = check_feasibility(db)
    assert report.feasible is False
    assert any("Τάξη A1" in e and "25" in e for e in report.errors)


def test_special_room_required_but_none_exists(db):
    seed = _seed_minimal(db)
    lab_subject = Subject(
        name="Φυσική",
        short_name="ΦΥΣ",
        color="#000",
        requires_special_room=True,
        special_room_type="lab",
    )
    db.add(lab_subject)
    db.commit()
    db.refresh(lab_subject)

    db.add(
        Lesson(
            subject_id=lab_subject.id,
            teacher_id=seed["teacher"].id,
            class_id=seed["class"].id,
            periods_per_week=2,
            duration=1,
        )
    )
    db.commit()

    report = check_feasibility(db)
    assert report.feasible is False
    assert any("lab" in e and "δεν υπάρχει" in e for e in report.errors)


def test_special_room_demand_exceeds_capacity(db):
    seed = _seed_minimal(db, days_per_week=5, n_periods=2, n_rooms=2)
    # Convert one room to a lab; demand 11 hours but lab capacity is 10
    seed["rooms"][0].room_type = "lab"
    db.commit()

    lab_subject = Subject(
        name="Φυσική",
        short_name="ΦΥΣ",
        color="#000",
        requires_special_room=True,
        special_room_type="lab",
    )
    t2 = Teacher(name="T2", short_name="T2", color="#000")
    c2 = SchoolClass(name="A2", short_name="A2")
    db.add_all([lab_subject, t2, c2])
    db.commit()
    db.refresh(lab_subject)
    db.refresh(t2)
    db.refresh(c2)

    db.add_all(
        [
            Lesson(
                subject_id=lab_subject.id,
                teacher_id=seed["teacher"].id,
                class_id=seed["class"].id,
                periods_per_week=6,
                duration=1,
            ),
            Lesson(
                subject_id=lab_subject.id,
                teacher_id=t2.id,
                class_id=c2.id,
                periods_per_week=5,
                duration=1,
            ),
        ]
    )
    db.commit()

    report = check_feasibility(db)
    assert report.feasible is False
    assert any("lab" in e and "11" in e for e in report.errors)


def test_block_too_long_for_school_day(db):
    seed = _seed_minimal(db, days_per_week=5, n_periods=4, n_rooms=2)
    db.add(
        Lesson(
            subject_id=seed["subject"].id,
            teacher_id=seed["teacher"].id,
            class_id=seed["class"].id,
            periods_per_week=5,
            distribution="5",  # one giant 5-hour block, but day has 4 periods
            duration=1,
        )
    )
    db.commit()

    report = check_feasibility(db)
    assert report.feasible is False
    assert any("block" in e and "5" in e for e in report.errors)


def test_student_overloaded_by_enrollments(db):
    seed = _seed_minimal(db)
    # Two classes, both with 18 hours each. Student enrolled in both → 36
    # hours, but week has only 5×6 = 30 slots.
    c2 = SchoolClass(name="A2", short_name="A2")
    student = Student(first_name="Παύλος", last_name="Π", phone="6900000000")
    db.add_all([c2, student])
    db.commit()
    db.refresh(c2)
    db.refresh(student)

    db.add_all(
        [
            Lesson(
                subject_id=seed["subject"].id,
                teacher_id=seed["teacher"].id,
                class_id=seed["class"].id,
                periods_per_week=18,
                duration=1,
            ),
            Lesson(
                subject_id=seed["subject"].id,
                teacher_id=seed["teacher"].id,
                class_id=c2.id,
                periods_per_week=18,
                duration=1,
            ),
            StudentClassEnrollment(student_id=student.id, class_id=seed["class"].id),
            StudentClassEnrollment(student_id=student.id, class_id=c2.id),
        ]
    )
    db.commit()

    report = check_feasibility(db)
    # Many things will be flagged, but the student error must be among them
    assert report.feasible is False
    assert any(f"id={student.id}" in e and "36" in e for e in report.errors)


def test_stats_contain_load_factor_and_per_teacher_load(db):
    seed = _seed_minimal(db)
    db.add(
        Lesson(
            subject_id=seed["subject"].id,
            teacher_id=seed["teacher"].id,
            class_id=seed["class"].id,
            periods_per_week=6,
            duration=1,
        )
    )
    db.commit()

    report = check_feasibility(db)
    assert report.stats["load_factor"] == round(6 / 60, 3)
    assert isinstance(report.stats["teacher_load"], list)
    assert report.stats["teacher_load"][0]["required"] == 6
    assert report.stats["teacher_load"][0]["capacity"] == 30


def test_to_dict_serializes_all_fields(db):
    _seed_minimal(db)
    report = check_feasibility(db)
    payload = report.to_dict()
    assert set(payload.keys()) == {"feasible", "errors", "warnings", "stats"}
    assert isinstance(payload["feasible"], bool)
