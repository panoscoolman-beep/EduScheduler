"""Ονομαστικά conflicts για τη χειροκίνητη τοποθέτηση (drag & drop).

Μέχρι τώρα ο enforcer απαντούσε με γενικές φράσεις («Ο καθηγητής διδάσκει
ήδη σε άλλη τάξη αυτή τη μέρα/ώρα») ενώ είχε ήδη φορτώσει το slot που
μπλοκάρει. Εδώ ζουν τα κοινά κομμάτια που κάνουν το μήνυμα συγκεκριμένο
(«Ο Νικολάου διδάσκει ήδη Μαθηματικά στο Β2 (αίθ. 3) — Τρίτη 3η») και
δίνουν στο frontend δομημένα στοιχεία (ποιο slot φταίει) για highlight.

Συμβατότητα: το `detail` της απάντησης παραμένει string (τα υπάρχοντα
tests και ο client το διαβάζουν έτσι)· η δομή μπαίνει σε ξεχωριστό κλειδί
`conflict` μέσω exception handler που εγκαθιστά το main.py.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.models import Classroom, Period, Student, TimetableSlot

GREEK_DAYS = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

# Κωδικοί conflict — σταθεροί για το frontend (εικονίδια/χρώματα).
TEACHER_BUSY = "teacher_busy"
CLASS_BUSY = "class_busy"
ROOM_BUSY = "room_busy"
ROOMS_EXHAUSTED = "rooms_exhausted"
NO_ROOM = "no_room"
TEACHER_UNAVAILABLE = "teacher_unavailable"
STUDENT_UNAVAILABLE = "student_unavailable"
SHARED_STUDENT = "shared_student"

MAX_NAMES = 3  # πόσα ονόματα μαθητών/αιθουσών γράφουμε πριν το «και N ακόμα»


class PlacementConflict(HTTPException):
    """400 με ονομαστικό μήνυμα ΚΑΙ δομημένα στοιχεία του conflict.

    `detail` = το μήνυμα (string, όπως πάντα). `conflict` = dict με
    code, message, blocking_slot_id, day/period/κ.λπ. — φτάνει στον client
    ως ξεχωριστό κλειδί όταν είναι εγκατεστημένος ο handler.
    """

    def __init__(self, code: str, message: str, **extra):
        super().__init__(status_code=400, detail=message)
        self.conflict = {"code": code, "message": message, **extra}

    def prefixed(self, prefix: str, **extra) -> "PlacementConflict":
        """Νέο exception με πρόθεμα στο μήνυμα (π.χ. ποια κάρτα του swap)."""
        data = {k: v for k, v in self.conflict.items() if k not in ("code", "message")}
        data.update(extra)
        return PlacementConflict(self.conflict["code"], f"{prefix}{self.conflict['message']}", **data)


def install_conflict_handler(app: FastAPI) -> None:
    """Σειριοποίηση PlacementConflict: {"detail": msg, "conflict": {...}}."""

    @app.exception_handler(PlacementConflict)
    async def _handle(_request: Request, exc: PlacementConflict):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "conflict": exc.conflict},
        )


# ─── Περιγραφές / μορφοποίηση ──────────────────────────────────────────


def day_name(day_of_week: int | None) -> str:
    if day_of_week is None or not (0 <= day_of_week < len(GREEK_DAYS)):
        return "—"
    return GREEK_DAYS[day_of_week]


def period_label(period: Period | None) -> str:
    if period is None:
        return "—"
    return f"{period.short_name} ({period.start_time})" if period.start_time else period.short_name


def cell_label(day_of_week: int | None, period: Period | None) -> str:
    """«Τρίτη 3η (18:00)» — πού ακριβώς είναι το πρόβλημα."""
    return f"{day_name(day_of_week)} {period_label(period)}"


def student_display(student: Student | None) -> str:
    if student is None:
        return "μαθητής"
    return f"{student.last_name} {student.first_name}".strip()


def join_names(names: list[str], max_names: int = MAX_NAMES) -> str:
    """«Α, Β, Γ και 2 ακόμα» — για λίστες μαθητών/αιθουσών."""
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) <= max_names:
        return ", ".join(names)
    return f"{', '.join(names[:max_names])} και {len(names) - max_names} ακόμα"


def describe_slot(db: Session, slot: TimetableSlot) -> dict:
    """Ταυτότητα ενός τοποθετημένου slot για μήνυμα + highlight.

    Επιστρέφει subject/teacher/class_name/classroom (strings, ποτέ None)
    και slot_id. Το αίθουσα-όνομα φορτώνεται με ένα μικρό query.
    """
    lesson = slot.lesson
    room_name = ""
    if slot.classroom_id is not None:
        room = db.query(Classroom).filter(Classroom.id == slot.classroom_id).first()
        room_name = room.name if room else ""
    return {
        "slot_id": slot.id,
        "subject": (lesson.subject.name if lesson and lesson.subject else "") or "",
        "teacher": (lesson.teacher.name if lesson and lesson.teacher else "") or "",
        "class_name": (
            lesson.school_class.short_name if lesson and lesson.school_class else ""
        ) or "",
        "classroom": room_name,
    }


def lesson_phrase(info: dict) -> str:
    """«Μαθηματικά στο Β2 (αίθ. 3)» από ένα describe_slot dict."""
    parts = info.get("subject") or "μάθημα"
    if info.get("class_name"):
        parts += f" στο {info['class_name']}"
    if info.get("classroom"):
        parts += f" (αίθ. {info['classroom']})"
    return parts
