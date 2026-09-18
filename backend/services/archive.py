"""Αρχειοθέτηση καθηγητών, τμημάτων, αιθουσών — «κρύψε τους περσινούς»
αντί για διαγραφή (που σβήνει σε αλυσίδα μαθήματα και ώρες).

Αρχειοθετημένη οντότητα: κρυφή από τις λίστες και τις φόρμες, δεν
προτείνεται σε νέες τοποθετήσεις ούτε στον solver· τα παλιά σενάρια και
προγράμματα μένουν ακέραια. Αναστρέψιμο.

Φραγή: δεν αρχειοθετείται κάτι που ΧΡΗΣΙΜΟΠΟΙΕΙΤΑΙ στο ενεργό σενάριο
(μαθήματα-κάρτες ή — για αίθουσα — τοποθετημένες ώρες σε ζωντανό πρόγραμμα),
γιατί θα «εξαφανιζόταν» από τις λίστες ενώ ακόμα διδάσκει/φιλοξενεί μάθημα.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import (
    Classroom, Lesson, SchoolClass, Teacher, Term, TimetableSlot, TimetableSolution, utcnow_naive,
)
from backend.services.term_context import get_active_term_id

_KINDS = {
    "teacher": (Teacher, "ο καθηγητής", Lesson.teacher_id),
    "class": (SchoolClass, "το τμήμα", Lesson.class_id),
    "classroom": (Classroom, "η αίθουσα", Lesson.classroom_id),
}


def active_classrooms(db: Session) -> list[Classroom]:
    """Αίθουσες διαθέσιμες για νέες τοποθετήσεις/solver (όχι αρχειοθετημένες)."""
    return db.query(Classroom).filter(Classroom.archived_at.is_(None)).all()


def _usage_reason(db: Session, kind: str, entity_id: int) -> str | None:
    _, label, lesson_col = _KINDS[kind]
    term_id = get_active_term_id(db)
    term = db.query(Term).filter(Term.id == term_id).first()
    term_name = term.name if term else ""
    lessons = db.query(Lesson).filter(lesson_col == entity_id, Lesson.term_id == term_id).count()
    if lessons:
        return (f"Δεν αρχειοθετείται: {label} χρησιμοποιείται σε {lessons} μαθήματα-κάρτες του ενεργού "
                f"σεναρίου «{term_name}». Μετέφερέ τα ή σβήσ' τα πρώτα.")
    if kind == "classroom":
        placed = (
            db.query(TimetableSlot)
            .join(TimetableSolution, TimetableSolution.id == TimetableSlot.solution_id)
            .filter(TimetableSlot.classroom_id == entity_id,
                    TimetableSlot.is_unplaced == False,  # noqa: E712
                    TimetableSolution.term_id == term_id,
                    TimetableSolution.archived_at.is_(None))
            .count()
        )
        if placed:
            return (f"Δεν αρχειοθετείται: στην αίθουσα είναι τοποθετημένες {placed} ώρες σε "
                    f"πρόγραμμα του ενεργού σεναρίου «{term_name}». Μετακίνησέ τες πρώτα.")
    return None


def set_archived(db: Session, kind: str, entity_id: int, archived: bool) -> dict:
    model, _, _ = _KINDS[kind]
    entity = db.query(model).filter(model.id == entity_id).first()
    if entity is None:
        raise HTTPException(status_code=404, detail="Δεν βρέθηκε")
    if archived:
        reason = _usage_reason(db, kind, entity_id)
        if reason:
            raise HTTPException(status_code=409, detail=reason)
    entity.archived_at = utcnow_naive() if archived else None
    db.commit()
    name = getattr(entity, "name", "") or ""
    return {
        "id": entity_id, "archived": archived,
        "message": (f"«{name}» αρχειοθετήθηκε — κρύφτηκε από τις λίστες· τα παλιά προγράμματα "
                    "μένουν ακέραια. Επαναφέρεται όποτε θες.") if archived
        else f"«{name}» επανήλθε.",
    }
