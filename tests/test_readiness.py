"""«📋 Έλεγχος δεδομένων» πριν από τη Δημιουργία (services/readiness.py)."""
from __future__ import annotations

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import (
    Lesson, SchoolClass, Student, StudentClassEnrollment, Subject, Teacher, Term,
)
from backend.services.readiness import readiness


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(Term(id=1, name="ΧΕΙΜΕΡΙΝΟ", is_active=True))
    subj = Subject(name="Άλγεβρα", short_name="ΑΛΓ", color="#000")
    teacher = Teacher(name="Καθ", short_name="Κ", color="#000")
    with_lessons = SchoolClass(name="Β2", short_name="Β2")
    empty_with_lessons = SchoolClass(name="Άδειο", short_name="ΑΔ")
    no_lessons = SchoolClass(name="Χωρίς μάθημα", short_name="ΧΜ")
    s.add_all([subj, teacher, with_lessons, empty_with_lessons, no_lessons])
    s.commit()
    ok = Student(first_name="Νίκος", last_name="Α", grade="Β΄ Λυκείου")
    loose = Student(first_name="Μαρία", last_name="Β", grade="Γ΄ Λυκείου")      # χωρίς τμήμα
    idle = Student(first_name="Ελένη", last_name="Γ")                           # τμήμα χωρίς μάθημα, χωρίς τάξη
    s.add_all([ok, loose, idle])
    s.commit()
    s.add_all([StudentClassEnrollment(student_id=ok.id, class_id=with_lessons.id),
               StudentClassEnrollment(student_id=idle.id, class_id=no_lessons.id)])
    for cls in (with_lessons, empty_with_lessons):
        s.add(Lesson(subject_id=subj.id, teacher_id=teacher.id, class_id=cls.id,
                     periods_per_week=2, term_id=1))
    s.commit()
    yield s
    s.close()


def test_readiness_lists_what_is_missing(db):
    report = readiness(db, 1)
    by = {c["key"]: c for c in report["checks"]}
    assert report["ok"] is False and report["term_name"] == "ΧΕΙΜΕΡΙΝΟ"
    assert by["students_without_class"]["names"] == ["Β Μαρία"]
    assert by["empty_classes_with_lessons"]["names"] == ["Άδειο"]
    assert by["students_without_lessons"]["names"] == ["Γ Ελένη"]
    assert by["students_without_grade"]["level"] == "info" and by["students_without_grade"]["count"] == 1
    assert by["term_without_dates"]["level"] == "info"


def test_clean_data_is_ok_and_only_infos_do_not_block(db):
    db.query(StudentClassEnrollment).delete()
    db.query(Lesson).delete()
    db.query(Student).delete()
    db.query(SchoolClass).filter(SchoolClass.name != "Β2").delete()
    term = db.query(Term).first()
    term.start_date, term.end_date = datetime.date(2026, 9, 14), datetime.date(2027, 5, 28)
    db.commit()
    assert readiness(db, 1) == {"term_id": 1, "term_name": "ΧΕΙΜΕΡΙΝΟ", "ok": True, "checks": []}


def test_names_are_capped_but_count_is_complete(db):
    for i in range(20):
        db.add(Student(first_name=f"Μ{i:02d}", last_name="Χωρίς", grade="Α΄ Λυκείου"))
    db.commit()
    check = next(c for c in readiness(db, 1)["checks"] if c["key"] == "students_without_class")
    assert check["count"] == 21 and len(check["names"]) == 15
