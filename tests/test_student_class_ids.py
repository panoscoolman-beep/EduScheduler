"""Tests for the Student.class_ids property + StudentResponse schema.

The frontend "Προβολή ανά Μαθητή" view needs to know which classes
each student attends so it can filter the timetable to only those
slots. We expose this via class_ids on the existing /api/students/
endpoint to avoid an extra round-trip.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import (
    SchoolClass,
    Student,
    StudentClassEnrollment,
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
    yield s
    s.close()


def test_student_with_no_enrollments_has_empty_class_ids(db):
    student = Student(first_name="Α", last_name="Β")
    db.add(student)
    db.commit()
    db.refresh(student)
    assert student.class_ids == []


def test_student_with_one_enrollment_returns_that_class_id(db):
    student = Student(first_name="Α", last_name="Β")
    cls = SchoolClass(name="A1", short_name="A1")
    db.add_all([student, cls])
    db.commit()
    db.refresh(student)
    db.refresh(cls)

    db.add(StudentClassEnrollment(student_id=student.id, class_id=cls.id))
    db.commit()
    db.refresh(student)

    assert student.class_ids == [cls.id]


def test_student_with_multiple_enrollments_returns_all_class_ids(db):
    student = Student(first_name="Α", last_name="Β")
    classes = [SchoolClass(name=f"C{i}", short_name=f"C{i}") for i in range(1, 4)]
    db.add_all([student, *classes])
    db.commit()
    db.refresh(student)
    for c in classes:
        db.refresh(c)

    for c in classes:
        db.add(StudentClassEnrollment(student_id=student.id, class_id=c.id))
    db.commit()
    db.refresh(student)

    assert sorted(student.class_ids) == sorted([c.id for c in classes])


def test_student_response_serializes_class_ids():
    """StudentResponse pydantic schema should include class_ids field
    so the API exposes it without an extra hop."""
    from backend.schemas import StudentResponse

    fields = StudentResponse.model_fields
    assert "class_ids" in fields, "StudentResponse must expose class_ids"


def test_two_students_have_independent_class_id_lists(db):
    """Adding enrollments to one student must not affect the other."""
    s1 = Student(first_name="Α", last_name="Β")
    s2 = Student(first_name="Γ", last_name="Δ")
    cls = SchoolClass(name="A1", short_name="A1")
    db.add_all([s1, s2, cls])
    db.commit()
    for o in [s1, s2, cls]:
        db.refresh(o)

    db.add(StudentClassEnrollment(student_id=s1.id, class_id=cls.id))
    db.commit()
    db.refresh(s1)
    db.refresh(s2)

    assert s1.class_ids == [cls.id]
    assert s2.class_ids == []
