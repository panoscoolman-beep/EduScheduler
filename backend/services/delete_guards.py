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
επιστρέφουν στην Παλέτα (`unplace_room_slots`) σε ΟΛΑ τα προγράμματα με την
παλιά τους θέση γραμμένη στη σημείωση της κάρτας· το καρφίτσωμα στις κάρτες
και η αίθουσα-βάση των τμημάτων σβήνονται (SET NULL). Αν όμως έχει ώρες σε
ΑΡΧΕΙΟΘΕΤΗΜΕΝΟ πρόγραμμα, η διαγραφή αρνείται και με force
(`classroom_in_archived`, χωρίς `requires_force`): το σωστό είναι η
📦 Αρχειοθέτηση της αίθουσας (`backend/services/archive.py`).
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import (
    Lesson,
    LessonStudentOverride,
    SchoolClass,
    StudentAvailability,
    StudentClassEnrollment,
    Term,
    TimetableSlot,
    TimetableSolution,
)
from backend.services.placement_conflicts import day_name

# Η αιτία στην κάρτα της Παλέτας κρατά ΚΑΙ την παλιά θέση (μέρα, ώρα, 🔒):
# δεν γράφεται ιστορικό, άρα είναι το μόνο ίχνος της.
ROOM_DELETED_REASON = "Η αίθουσα «{name}» διαγράφηκε — ήταν {day}, {period}{lock}"
_REASON_MAX = TimetableSlot.__table__.c.unplaced_reason.type.length or 500


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
    """Τοποθετημένες ώρες της αίθουσας σε ΟΛΑ τα προγράμματα/σενάρια (και ανά
    πρόγραμμα: όνομα, σενάριο, αρχειοθετημένο, πλήθος), κάρτες με καρφωμένη
    την αίθουσα και τμήματα που την έχουν αίθουσα-βάση."""
    rows = (
        # TimetableSlot.id keeps one row per slot: a query of entities alone
        # returns each (programme, scenario) pair once, so it undercounts.
        db.query(TimetableSolution, Term, TimetableSlot.id)
        .join(TimetableSlot, TimetableSlot.solution_id == TimetableSolution.id)
        .outerjoin(Term, Term.id == TimetableSolution.term_id)
        .filter(
            TimetableSlot.classroom_id == classroom_id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .order_by(TimetableSolution.id, TimetableSlot.id)
        .all()
    )
    programmes: dict[int, dict] = {}
    for sol, term, _slot_id in rows:
        item = programmes.setdefault(sol.id, {
            "solution_id": sol.id, "solution_name": sol.name,
            "term_id": sol.term_id, "term_name": term.name if term else "",
            "archived": sol.archived_at is not None, "slots": 0,
        })
        item["slots"] += 1
    return {
        "placed": len(rows),
        "solutions": len(programmes),
        "programmes": list(programmes.values()),
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


def student_usage(db: Session, student_id: int) -> dict:
    """Τι σβήνεται μαζί με τον μαθητή: εγγραφές σε τμήματα, 👥 εξαιρέσεις
    καρτών, κωλύματα (όλων των σεναρίων)."""
    return {
        "classes": db.query(StudentClassEnrollment)
        .filter(StudentClassEnrollment.student_id == student_id).count(),
        "overrides": db.query(LessonStudentOverride)
        .filter(LessonStudentOverride.student_id == student_id).count(),
        # κωλύματα = «unavailable» (the matrix may also hold available/preferred rows)
        "availability": db.query(StudentAvailability)
        .filter(StudentAvailability.student_id == student_id,
                StudentAvailability.status == "unavailable").count(),
    }


def guard_student(usage: dict, *, force: bool, name: str) -> None:
    """409 όταν ο μαθητής έχει τμήματα/εξαιρέσεις/κωλύματα και δεν δόθηκε force."""
    if not any(usage.values()) or force:
        return
    raise HTTPException(status_code=409, detail={
        "code": "student_in_use",
        "requires_force": True,
        "message": (f"Ο μαθητής «{name}» έχει {usage['classes']} τμήματα, {usage['overrides']} "
                    f"εξαιρέσεις καρτών, {usage['availability']} κωλύματα. Η διαγραφή τα σβήνει "
                    "όλα οριστικά, σε όλα τα σενάρια. Στο CRM ο μαθητής μένει — η επόμενη "
                    "«Εισαγωγή από CRM» θα τον ξαναφέρει χωρίς τμήματα."),
        "usage": usage,
    })


def programme_label(p: dict) -> str:
    """«Όνομα» (σενάριο «Χ», αρχειοθετημένο) — χωρίς κενό «σενάριο «»»."""
    notes = [f"σενάριο «{p['term_name']}»"] if p.get("term_name") else []
    if p.get("archived"):
        notes.append("αρχειοθετημένο")
    return f"«{p['solution_name']}»" + (f" ({', '.join(notes)})" if notes else "")


def _classroom_message(name: str, usage: dict) -> str:
    parts = []
    if usage["placed"]:
        listing = ", ".join(f"{programme_label(p)}: {p['slots']}"
                            for p in usage.get("programmes", []))
        parts.append(
            f"Στην αίθουσα «{name}» είναι τοποθετημένες {usage['placed']} ώρες σε "
            f"{usage['solutions']} πρόγραμμα(τα): {listing}. Με τη διαγραφή πάνε στην Παλέτα "
            + ("(και στα αρχειοθετημένα προγράμματα) "
               if any(p.get("archived") for p in usage.get("programmes", [])) else "")
            + "χωρίς 🔒, και η παλιά τους θέση (μέρα, ώρα) "
            "μένει ΜΟΝΟ στη σημείωση κάθε κάρτας — δεν υπάρχει «↩️ Αναίρεση».")
    extra = []
    if usage.get("preferred_by_lessons"):
        extra.append(f"είναι καρφωμένη σε {usage['preferred_by_lessons']} μαθήματα-κάρτες")
    if usage.get("home_room_of_classes"):
        extra.append(f"είναι αίθουσα-βάση {usage['home_room_of_classes']} τμημάτων")
    if extra:
        parts.append(f"Η αίθουσα «{name}» " + " και ".join(extra)
                     + " — εκεί το πεδίο αδειάζει (οι κάρτες και τα τμήματα ΔΕΝ σβήνονται).")
    return " ".join(parts)


def guard_classroom(usage: dict, *, force: bool, name: str) -> None:
    """409 όταν η αίθουσα έχει τοποθετημένες ώρες Ή είναι καρφωμένη σε κάρτες /
    αίθουσα-βάση τμημάτων, και δεν δόθηκε force.

    Ώρες σε ΑΡΧΕΙΟΘΕΤΗΜΕΝΟ πρόγραμμα: άρνηση ακόμη και με force — το
    αρχειοθετημένο είναι αρχείο παλιού ωρολογίου και κρατά τις αίθουσές του·
    η σωστή κίνηση είναι η 📦 Αρχειοθέτηση της αίθουσας."""
    archived = [p for p in usage.get("programmes", []) if p.get("archived")]
    if archived:
        listing = ", ".join(f"«{p['solution_name']}»" for p in archived)
        raise HTTPException(status_code=409, detail={
            "code": "classroom_in_archived",
            "requires_force": False,
            "message": (f"Η αίθουσα «{name}» έχει ώρες σε αρχειοθετημένα προγράμματα: {listing}. "
                        "Αν τη διαγράψεις, εκείνα τα προγράμματα θα χάσουν τις θέσεις τους. "
                        "Κάνε της 📦 Αρχειοθέτηση αντί για διαγραφή "
                        "(κρατά τα παλιά προγράμματα ακέραια)."),
            "usage": usage,
        })
    in_use = usage["placed"] or usage.get("preferred_by_lessons") or usage.get("home_room_of_classes")
    if not in_use or force:
        return
    raise HTTPException(status_code=409, detail={
        "code": "classroom_in_use",
        "requires_force": True,
        "message": _classroom_message(name, usage),
        "usage": usage,
    })


def _room_deleted_reason(name: str, slot: TimetableSlot) -> str:
    reason = ROOM_DELETED_REASON.format(
        name=name, day=day_name(slot.day_of_week),
        period=slot.period.name if slot.period else "—",
        lock=", 🔒" if slot.is_locked else "")
    return reason if len(reason) <= _REASON_MAX else reason[:_REASON_MAX - 1] + "…"


def unplace_room_slots(db: Session, classroom_id: int, name: str) -> int:
    """Οι ώρες της αίθουσας που σβήνεται → πίσω στην Παλέτα (χωρίς commit),
    σε ΟΛΑ τα προγράμματα (αλλιώς το delete σκοντάφτει στο
    ck_slot_placement_consistent ή σβήνει τις ώρες των αρχειοθετημένων).

    Δεν γράφεται ιστορικό undo: η αίθουσα δεν θα υπάρχει πια, οπότε μια
    «αναίρεση» δεν θα είχε πού να τις ξαναβάλει — η παλιά θέση μένει στη
    σημείωση της κάρτας (`unplaced_reason`)."""
    slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.classroom_id == classroom_id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .all()
    )
    for slot in slots:
        reason = _room_deleted_reason(name, slot)
        slot.day_of_week = None
        slot.period_id = None
        slot.classroom_id = None
        slot.is_locked = False
        slot.is_unplaced = True
        slot.unplaced_reason = reason
    db.flush()
    return len(slots)
