"""Φραγή καταστροφικών διαγραφών: καθηγητής, μάθημα, τμήμα, αίθουσα.

Η διαγραφή καθηγητή/μαθήματος/τμήματος σβήνει ΣΕ ΑΛΥΣΙΔΑ όλα τα μαθήματα-κάρτες
του — σε όλα τα σενάρια — και μαζί τις τοποθετημένες ώρες τους σε όλα τα
προγράμματα. Πριν από αυτό ο χρήστης έβλεπε μόνο ένα γενικό «Είστε σίγουροι;».

Τώρα: όταν η οντότητα χρησιμοποιείται, η διαγραφή επιστρέφει 409 με τα ΠΛΗΘΗ
(`requires_force`) και προχωρά μόνο με ρητό `?force=true` — ίδιο μοτίβο με τις
ώρες (periods), τα σενάρια και τα μαθήματα-κάρτες. Το DataTable του frontend
δείχνει ήδη το μήνυμα σε δεύτερο, «κόκκινο» παράθυρο.

Η αίθουσα είναι ειδική περίπτωση: δεν σβήνει μαθήματα, αλλά οι ώρες που είναι
τοποθετημένες σε αυτήν θα έμεναν «τοποθετημένες χωρίς αίθουσα». Με force
επιστρέφουν στην Παλέτα (`unplace_room_slots`) — δεν χάνεται καμία ώρα.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import (
    Lesson,
    SchoolClass,
    StudentClassEnrollment,
    TimetableSlot,
)

ROOM_DELETED_REASON = "Η αίθουσα «{name}» διαγράφηκε — ξανατοποθέτησέ την."


def _lessons_usage(db: Session, *criteria) -> dict:
    """Πόσα μαθήματα-κάρτες ταιριάζουν και πόσες ώρες τους είναι τοποθετημένες."""
    lessons = db.query(Lesson.id, Lesson.term_id).filter(*criteria).all()
    ids = [lesson_id for lesson_id, _ in lessons]
    usage = {
        "lessons": len(ids),
        "terms": len({term_id for _, term_id in lessons}),
        "placed": 0,
        "unplaced": 0,
        "solutions": 0,
    }
    if not ids:
        return usage
    rows = (
        db.query(TimetableSlot.solution_id, TimetableSlot.is_unplaced)
        .filter(TimetableSlot.lesson_id.in_(ids))
        .all()
    )
    usage["placed"] = sum(1 for _, unplaced in rows if not unplaced)
    usage["unplaced"] = sum(1 for _, unplaced in rows if unplaced)
    usage["solutions"] = len({sid for sid, _ in rows})
    return usage


def teacher_usage(db: Session, teacher_id: int) -> dict:
    return _lessons_usage(db, Lesson.teacher_id == teacher_id)


def subject_usage(db: Session, subject_id: int) -> dict:
    return _lessons_usage(db, Lesson.subject_id == subject_id)


def class_usage(db: Session, class_id: int) -> dict:
    usage = _lessons_usage(db, Lesson.class_id == class_id)
    usage["students"] = (
        db.query(StudentClassEnrollment)
        .filter(StudentClassEnrollment.class_id == class_id)
        .count()
    )
    return usage


def classroom_usage(db: Session, classroom_id: int) -> dict:
    rows = (
        db.query(TimetableSlot.solution_id)
        .filter(
            TimetableSlot.classroom_id == classroom_id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .all()
    )
    return {
        "placed": len(rows),
        "solutions": len({sid for (sid,) in rows}),
        "preferred_by_lessons": db.query(Lesson)
        .filter(Lesson.classroom_id == classroom_id).count(),
        "home_room_of_classes": db.query(SchoolClass)
        .filter(SchoolClass.home_room_id == classroom_id).count(),
    }


def _lessons_phrase(u: dict) -> str:
    text = f"{u['lessons']} μαθήματα-κάρτες"
    if u["terms"] > 1:
        text += f" σε {u['terms']} σενάρια"
    if u["placed"]:
        text += f" με {u['placed']} τοποθετημένες ώρες σε {u['solutions']} πρόγραμμα(τα)"
    return text


def guard_lessons_owner(usage: dict, *, force: bool, code: str, subject: str) -> None:
    """409 όταν η οντότητα έχει μαθήματα-κάρτες και δεν δόθηκε force.

    `subject` = ολόκληρη η αρχή της πρότασης, π.χ. «Ο καθηγητής «Χ» έχει»."""
    if not usage["lessons"] or force:
        return
    extra = ""
    if usage.get("students"):
        extra = (f" Επίσης έχει {usage['students']} εγγεγραμμένους μαθητές "
                 "(οι μαθητές ΔΕΝ σβήνονται, μόνο η εγγραφή τους στο τμήμα).")
    raise HTTPException(status_code=409, detail={
        "code": code,
        "requires_force": True,
        "message": (f"{subject} {_lessons_phrase(usage)}. Η διαγραφή θα τα σβήσει ΟΛΑ "
                    f"οριστικά, σε όλα τα προγράμματα.{extra}"),
        "usage": usage,
    })


def guard_classroom(usage: dict, *, force: bool, name: str) -> None:
    if not usage["placed"] or force:
        return
    raise HTTPException(status_code=409, detail={
        "code": "classroom_in_use",
        "requires_force": True,
        "message": (f"Στην αίθουσα «{name}» είναι τοποθετημένες {usage['placed']} ώρες σε "
                    f"{usage['solutions']} πρόγραμμα(τα). Με τη διαγραφή θα επιστρέψουν στην "
                    "Παλέτα για να τις ξανατοποθετήσεις — δεν χάνεται καμία ώρα."),
        "usage": usage,
    })


def unplace_room_slots(db: Session, classroom_id: int, name: str) -> int:
    """Οι ώρες της αίθουσας που σβήνεται → πίσω στην Παλέτα (χωρίς commit).

    Δεν γράφεται ιστορικό undo: η αίθουσα δεν θα υπάρχει πια, οπότε μια
    «αναίρεση» δεν θα είχε πού να τις ξαναβάλει."""
    slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.classroom_id == classroom_id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .all()
    )
    for slot in slots:
        slot.day_of_week = None
        slot.period_id = None
        slot.classroom_id = None
        slot.is_locked = False
        slot.is_unplaced = True
        slot.unplaced_reason = ROOM_DELETED_REASON.format(name=name)
    db.flush()
    return len(slots)
