"""Αλλαγή καθηγητή/τμήματος σε κάρτα με τοποθετημένες ώρες — έλεγχος συγκρούσεων.

Οι τοποθετημένες ώρες μένουν στη θέση τους όταν αλλάζει ο καθηγητής ή το
τμήμα μιας κάρτας. Χωρίς έλεγχο, ο νέος καθηγητής μπορεί να βρεθεί σε δύο
τάξεις ταυτόχρονα (ή μαθητές του νέου τμήματος σε δύο μαθήματα) σιωπηλά.
Εδώ βρίσκουμε ποιες ώρες συγκρούονται, σε όλα τα ενεργά (μη αρχειοθετημένα)
προγράμματα του σεναρίου της κάρτας. Pure read.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.models import (
    Lesson, Period, SchoolClass, Student, StudentAvailability, StudentClassEnrollment, Subject,
    Teacher, TeacherAvailability, TimetableSlot, TimetableSolution,
)
from backend.services import lesson_roster
from backend.services import placement_conflicts as pc


def _describe(db: Session, slot: TimetableSlot) -> str:
    lesson = db.query(Lesson).filter(Lesson.id == slot.lesson_id).first()
    subject = db.query(Subject).filter(Subject.id == lesson.subject_id).first()
    klass = db.query(SchoolClass).filter(SchoolClass.id == lesson.class_id).first()
    return f"{subject.name if subject else 'μάθημα'} ({klass.name if klass else ''})"


def change_conflicts(db: Session, lesson: Lesson, new_teacher_id: int, new_class_id: int) -> list[dict]:
    teacher_changed = new_teacher_id != lesson.teacher_id
    class_changed = new_class_id != lesson.class_id
    if not (teacher_changed or class_changed):
        return []

    solutions = {s.id: s for s in db.query(TimetableSolution).filter(
        TimetableSolution.term_id == lesson.term_id,
        TimetableSolution.archived_at.is_(None)).all()}
    if not solutions:
        return []
    mine = db.query(TimetableSlot).filter(
        TimetableSlot.lesson_id == lesson.id,
        TimetableSlot.solution_id.in_(solutions),
        TimetableSlot.is_unplaced == False).all()  # noqa: E712
    if not mine:
        return []

    periods = {p.id: p for p in db.query(Period).all()}
    teacher = db.query(Teacher).filter(Teacher.id == new_teacher_id).first()
    new_class = db.query(SchoolClass).filter(SchoolClass.id == new_class_id).first()
    new_students = {sid for (sid,) in db.query(StudentClassEnrollment.student_id)
                    .filter(StudentClassEnrollment.class_id == new_class_id).all()} if class_changed else set()
    teacher_unav = {(d, p) for d, p in db.query(TeacherAvailability.day_of_week, TeacherAvailability.period_id)
                    .filter(TeacherAvailability.teacher_id == new_teacher_id,
                            TeacherAvailability.status == "unavailable",
                            TeacherAvailability.term_id == lesson.term_id).all()} if teacher_changed else set()
    student_unav: dict = {}
    if new_students:
        for d, p, sid in (db.query(StudentAvailability.day_of_week, StudentAvailability.period_id,
                                   StudentAvailability.student_id)
                          .filter(StudentAvailability.student_id.in_(new_students),
                                  StudentAvailability.status == "unavailable",
                                  StudentAvailability.term_id == lesson.term_id).all()):
            student_unav.setdefault((d, p), set()).add(sid)

    def student_names(ids) -> str:
        rows = db.query(Student).filter(Student.id.in_(ids)).all()
        return pc.join_names([pc.student_display(s) for s in rows])

    out = []
    for slot in mine:
        cell = (slot.day_of_week, slot.period_id)
        others = (db.query(TimetableSlot, Lesson)
                  .join(Lesson, Lesson.id == TimetableSlot.lesson_id)
                  .filter(TimetableSlot.solution_id == slot.solution_id,
                          TimetableSlot.id != slot.id,
                          TimetableSlot.day_of_week == slot.day_of_week,
                          TimetableSlot.period_id == slot.period_id,
                          TimetableSlot.is_unplaced == False).all())  # noqa: E712
        reason = None
        if teacher_changed:
            busy = next((o for o, l in others if l.teacher_id == new_teacher_id), None)
            if busy is not None:
                reason = f"ο/η {teacher.name if teacher else 'καθηγητής'} διδάσκει ήδη {_describe(db, busy)}"
            elif cell in teacher_unav:
                reason = f"κώλυμα του/της {teacher.name if teacher else 'καθηγητή'}"
        if reason is None and class_changed:
            busy = next((o for o, l in others if l.class_id == new_class_id), None)
            # Ποιοι είναι στις ΑΛΛΕΣ κάρτες εκείνη την ώρα: η λίστα κάθε κάρτας
            # (τμήμα + προσθήκες − εξαιρέσεις), όχι σκέτο το τμήμα της.
            shared = set()
            if new_students:
                for students in lesson_roster.roster_map(db, [l for _o, l in others]).values():
                    shared |= new_students & students
            if busy is not None:
                reason = f"το τμήμα {new_class.name if new_class else ''} έχει ήδη {_describe(db, busy)}"
            elif shared:
                reason = f"κοινοί μαθητές σε άλλο μάθημα: {student_names(shared)}"
            elif cell in student_unav:
                reason = f"κώλυμα μαθητή: {student_names(student_unav[cell])}"
        if reason:
            out.append({
                "slot_id": slot.id,
                "solution": solutions[slot.solution_id].name,
                "when": pc.cell_label(slot.day_of_week, periods.get(slot.period_id)),
                "reason": reason,
            })
    return out


def conflicts_message(conflicts: list[dict]) -> str:
    lines = "; ".join(f"{c['when']} ({c['solution']}): {c['reason']}" for c in conflicts[:5])
    more = f" και άλλες {len(conflicts) - 5}" if len(conflicts) > 5 else ""
    return (f"Η αλλαγή συγκρούεται σε {len(conflicts)} τοποθετημένες ώρες — {lines}{more}. "
            "Αν συνεχίσεις, αυτές οι ώρες πάνε στην Παλέτα για να τις ξανατοποθετήσεις "
            "(αναιρείται από το 🕘 Ιστορικό).")
