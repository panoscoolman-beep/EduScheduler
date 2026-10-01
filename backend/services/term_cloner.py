"""Deep-copy a scenario's INPUT data into a new term.

Copies lessons (with their per-card student overrides) + teacher/student
availability from a source term into a freshly created term. Does NOT copy
timetable_solutions — a new scenario starts without generated programs (you run
the solver fresh). Global catalog entities
(teachers, students, classes, subjects, classrooms, periods) are shared, so only
their references are copied, not the entities themselves.
"""
from sqlalchemy.orm import Session

from backend.models import (
    Term, Lesson, LessonStudentOverride, TeacherAvailability, StudentAvailability,
)


def clone_term_inputs(db: Session, source_term_id: int, new_term: Term) -> dict:
    """Copy inputs from source_term_id into new_term (must already have an id,
    i.e. added + flushed). Returns per-table counts. Caller commits."""
    counts = {"lessons": 0, "lesson_student_overrides": 0,
              "teacher_availability": 0, "student_availability": 0}

    # παλιό lesson.id → νέο lesson.id, για να μεταφερθούν οι 👥 εξαιρέσεις
    # μαθητών ανά κάρτα (lesson_student_overrides) στις νέες κάρτες.
    new_lesson_ids: dict[int, int] = {}
    for lesson in db.query(Lesson).filter(Lesson.term_id == source_term_id).all():
        new_lesson = Lesson(
            term_id=new_term.id,
            subject_id=lesson.subject_id,
            teacher_id=lesson.teacher_id,
            class_id=lesson.class_id,
            classroom_id=lesson.classroom_id,
            periods_per_week=lesson.periods_per_week,
            duration=lesson.duration,
            distribution=lesson.distribution,
            is_locked=lesson.is_locked,
        )
        db.add(new_lesson)
        db.flush()  # χρειαζόμαστε το νέο id για τα overrides
        new_lesson_ids[lesson.id] = new_lesson.id
        counts["lessons"] += 1

    # Χωρίς αυτά, ένας μαθητής που κάνει π.χ. το ένα δίωρο σε άλλο τμήμα θα
    # «γύριζε» στο τμήμα του στο αντίγραφο — λάθος συγκρούσεις στον solver.
    if new_lesson_ids:
        for ov in (
            db.query(LessonStudentOverride)
            .filter(LessonStudentOverride.lesson_id.in_(list(new_lesson_ids)))
            .all()
        ):
            db.add(LessonStudentOverride(
                lesson_id=new_lesson_ids[ov.lesson_id],
                student_id=ov.student_id,
                mode=ov.mode,
            ))
            counts["lesson_student_overrides"] += 1

    for ta in db.query(TeacherAvailability).filter(TeacherAvailability.term_id == source_term_id).all():
        db.add(TeacherAvailability(
            term_id=new_term.id,
            teacher_id=ta.teacher_id,
            day_of_week=ta.day_of_week,
            period_id=ta.period_id,
            status=ta.status,
        ))
        counts["teacher_availability"] += 1

    for sa in db.query(StudentAvailability).filter(StudentAvailability.term_id == source_term_id).all():
        db.add(StudentAvailability(
            term_id=new_term.id,
            student_id=sa.student_id,
            day_of_week=sa.day_of_week,
            period_id=sa.period_id,
            status=sa.status,
        ))
        counts["student_availability"] += 1

    return counts
