"""Τι επηρεάζει ένα μάθημα-κάρτα της Παλέτας — και τι θα χαθεί αν σβηστεί.

Η Παλέτα δείχνει ώρες που δεν έχουν μπει ακόμα στο πρόγραμμα. Πριν τις
καθαρίσει ο χρήστης θέλει να ξέρει πού χρησιμοποιείται το μάθημα: σε ποια
προγράμματα του σεναρίου, πόσες ώρες του είναι ήδη τοποθετημένες και πόσες
περιμένουν. Εδώ μαζεύονται ΜΟΝΟ τα γεγονότα· τα κείμενα ζουν στο frontend.

Κανόνας ασφαλείας του «καθαρίσματος»: οι ώρες/εβδομάδα πέφτουν στο ΜΕΓΙΣΤΟ
πλήθος τοποθετημένων ωρών σε οποιοδήποτε πρόγραμμα του σεναρίου. Έτσι δεν
χάνεται ποτέ ώρα που χρησιμοποιείται κάπου — και το sync_lesson_slot_count
σβήνει έτσι κι αλλιώς μόνο μη τοποθετημένες ώρες.
"""
from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from backend.models import (
    Lesson,
    StudentClassEnrollment,
    Term,
    TimetableSlot,
    TimetableSolution,
)
from backend.services.parking_lot_sync import ACTIVE_STATUSES


def _solution_rows(db: Session, lesson: Lesson) -> list[dict]:
    """Ανά πρόγραμμα του ίδιου σεναρίου: τοποθετημένες / στην παλέτα / λείπουν."""
    solutions = (
        db.query(TimetableSolution)
        .filter(
            TimetableSolution.term_id == lesson.term_id,
            TimetableSolution.status.in_(ACTIVE_STATUSES),
            TimetableSolution.archived_at.is_(None),
        )
        .order_by(TimetableSolution.id.desc())
        .all()
    )
    target = int(lesson.periods_per_week)
    rows = []
    for sol in solutions:
        slots = (
            db.query(TimetableSlot)
            .filter(
                TimetableSlot.solution_id == sol.id,
                TimetableSlot.lesson_id == lesson.id,
            )
            .all()
        )
        placed = sum(1 for s in slots if not s.is_unplaced)
        unplaced = sum(1 for s in slots if s.is_unplaced)
        rows.append({
            "solution_id": sol.id,
            "solution_name": sol.name,
            "status": sol.status,
            "placed": placed,
            "unplaced": unplaced,
            "missing": max(0, target - placed - unplaced),
        })
    return rows


def _trim_plan(periods_per_week: int, max_placed: int) -> dict:
    """Μέχρι πού μπορούν να κοπούν οι ώρες χωρίς να χαθεί τοποθετημένη ώρα."""
    if max_placed <= 0:
        return {"can_trim": False, "trim_to": periods_per_week, "would_remove": 0,
                "blocked_reason": "no_placed_hours"}
    if periods_per_week <= max_placed:
        return {"can_trim": False, "trim_to": periods_per_week, "would_remove": 0,
                "blocked_reason": "nothing_to_trim"}
    return {"can_trim": True, "trim_to": max_placed,
            "would_remove": periods_per_week - max_placed, "blocked_reason": None}


def lesson_impact(db: Session, lesson_id: int) -> dict | None:
    """Πλήρης εικόνα ενός μαθήματος-κάρτας. None αν δεν υπάρχει."""
    lesson = (
        db.query(Lesson)
        .options(
            joinedload(Lesson.subject),
            joinedload(Lesson.teacher),
            joinedload(Lesson.school_class),
        )
        .filter(Lesson.id == lesson_id)
        .first()
    )
    if lesson is None:
        return None

    rows = _solution_rows(db, lesson)
    placed_total = sum(r["placed"] for r in rows)
    max_placed = max([r["placed"] for r in rows], default=0)
    students = (
        db.query(StudentClassEnrollment)
        .filter(StudentClassEnrollment.class_id == lesson.class_id)
        .count()
        if lesson.class_id else 0
    )
    term = db.query(Term).filter(Term.id == lesson.term_id).first()

    return {
        "lesson": {
            "id": lesson.id,
            "subject_name": lesson.subject.name if lesson.subject else "",
            "teacher_name": lesson.teacher.name if lesson.teacher else "",
            "class_name": lesson.school_class.name if lesson.school_class else "",
            "class_students": students,
            "periods_per_week": int(lesson.periods_per_week),
            "term_id": lesson.term_id,
            "term_name": term.name if term else "",
        },
        "solutions": rows,
        "totals": {
            "solutions": len(rows),
            "placed": placed_total,
            "unplaced": sum(r["unplaced"] for r in rows),
            "max_placed": max_placed,
        },
        "trim": _trim_plan(int(lesson.periods_per_week), max_placed),
        "delete": {
            "placed_total": placed_total,
            "solutions_with_placed": sum(1 for r in rows if r["placed"]),
            "requires_force": placed_total > 0,
        },
    }
