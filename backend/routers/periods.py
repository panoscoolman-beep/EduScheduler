"""
Periods API — CRUD for daily time slots / bell schedule.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import (
    Classroom, Period, Term, TimetableSlot, TimetableSolution, TeacherAvailability,
    StudentAvailability,
)
from backend.schemas import PeriodCreate, PeriodResponse
from backend.services import slot_history
from backend.services.placement_conflicts import day_name

router = APIRouter()


@router.get("/", response_model=list[PeriodResponse])
def list_periods(db: Session = Depends(get_db)):
    return db.query(Period).order_by(Period.sort_order).all()


@router.get("/{period_id}", response_model=PeriodResponse)
def get_period(period_id: int, db: Session = Depends(get_db)):
    period = db.query(Period).filter(Period.id == period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="Η ώρα δεν βρέθηκε")
    return period


@router.post("/", response_model=PeriodResponse, status_code=201)
def create_period(data: PeriodCreate, db: Session = Depends(get_db)):
    period = Period(**data.model_dump())
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


BREAK_UNPLACE_REASON = "Η «{name}» έγινε διάλειμμα — ήταν {day} {name}, {room}{lock}"
_REASON_MAX = TimetableSlot.__table__.c.unplaced_reason.type.length or 500


def _break_reason(db: Session, period: Period, slot: TimetableSlot) -> str:
    """Η αιτία στην κάρτα της Παλέτας κρατά ΚΑΙ την παλιά θέση: η εγγραφή του
    ιστορικού μπορεί να χαθεί (μια νέα αλλαγή σβήνει τις παραλειμμένες)."""
    room = db.query(Classroom).filter(Classroom.id == slot.classroom_id).first()
    reason = BREAK_UNPLACE_REASON.format(
        name=period.name, day=day_name(slot.day_of_week), room=room.name if room else "—",
        lock=", 🔒" if slot.is_locked else "")
    return reason if len(reason) <= _REASON_MAX else reason[:_REASON_MAX - 1] + "…"


def _break_usage(db: Session, period_id: int) -> tuple[list, list[dict]]:
    """Τοποθετημένες ώρες στην `period_id` σε ΟΛΑ τα προγράμματα/σενάρια:
    ([(slot, archived)], [ανά πρόγραμμα: όνομα, σενάριο, αρχειοθετημένο, πλήθος])."""
    rows = (
        db.query(TimetableSlot, TimetableSolution, Term)
        .join(TimetableSolution, TimetableSolution.id == TimetableSlot.solution_id)
        .outerjoin(Term, Term.id == TimetableSolution.term_id)
        .filter(TimetableSlot.period_id == period_id,
                TimetableSlot.is_unplaced == False)  # noqa: E712
        .order_by(TimetableSolution.id, TimetableSlot.id)
        .all()
    )
    programmes: dict[int, dict] = {}
    for _slot, sol, term in rows:
        item = programmes.setdefault(sol.id, {
            "solution_id": sol.id, "solution_name": sol.name,
            "term_id": sol.term_id, "term_name": term.name if term else "",
            "archived": sol.archived_at is not None, "slots": 0,
        })
        item["slots"] += 1
    return [(slot, sol.archived_at is not None) for slot, sol, _term in rows], list(programmes.values())


def _break_message(period: Period, slots: int, programmes: list[dict]) -> str:
    listing = ", ".join(
        f"«{p['solution_name']}» (σενάριο «{p['term_name']}»"
        + (", αρχειοθετημένο" if p["archived"] else "") + f"): {p['slots']}"
        for p in programmes)
    active = sum(p["slots"] for p in programmes if not p["archived"])
    archived = slots - active
    text = (f"Η ώρα «{period.name}» έχει {slots} τοποθετημένα μαθήματα σε "
            f"{len(programmes)} πρόγραμμα(τα): {listing}.")
    if active:
        text += (f" Ως διάλειμμα θα χάνονταν από το πρόγραμμα και τις εκτυπώσεις: αν συνεχίσεις, "
                 f"οι {active} ώρες των ενεργών προγραμμάτων πάνε στην Παλέτα και η παλιά τους "
                 "θέση (μέρα, ώρα, αίθουσα, 🔒) μένει στο 🕘 Ιστορικό και στην κάρτα — αν την "
                 "ξανακάνεις διδακτική ώρα, επανέρχονται με «↩️ Αναίρεση». Οι εκκρεμείς "
                 "«Επαναλήψεις» (↪) αυτών των προγραμμάτων χάνονται.")
    if archived:
        text += (f" Τα αρχειοθετημένα προγράμματα ΔΕΝ αλλάζουν: όσο η ώρα είναι διάλειμμα οι "
                 f"{archived} ώρες τους απλώς δεν φαίνονται και ξαναεμφανίζονται μόλις ξαναγίνει "
                 "διδακτική.")
    return text


@router.put("/{period_id}", response_model=PeriodResponse)
def update_period(
    period_id: int,
    data: PeriodCreate,
    force: bool = Query(False, description="Confirm: active programmes' lessons go to the palette"),
    db: Session = Depends(get_db),
):
    """Αλλαγή ώρας. Αν μια ώρα με τοποθετημένα μαθήματα γίνεται «Διάλειμμα»,
    αυτά θα εξαφανίζονταν από πλέγμα/εκτυπώσεις (μένοντας όμως στο .ics και
    στις δημοσιεύσεις). Χωρίς `?force=true` → 409 + πλήθη ανά πρόγραμμα. Με
    force: οι ώρες των ΕΝΕΡΓΩΝ προγραμμάτων (όλων των σεναρίων) πάνε στην Παλέτα
    γραμμένες στο 🕘 ιστορικό (ίδια διαδρομή με το χειροκίνητο «στην Παλέτα»),
    ώστε να επανέλθουν με αναίρεση αν η ώρα ξαναγίνει διδακτική· τα
    ΑΡΧΕΙΟΘΕΤΗΜΕΝΑ δεν αγγίζονται ποτέ (απλώς κρύβονται όσο είναι διάλειμμα,
    όπως πάντα). Δεν χάνεται καμία ώρα ούτε η παλιά της θέση."""
    period = db.query(Period).filter(Period.id == period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="Η ώρα δεν βρέθηκε")
    if data.is_break and not period.is_break:
        placed, programmes = _break_usage(db, period_id)
        if placed and not force:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "period_in_use",
                    "requires_force": True,
                    "message": _break_message(period, len(placed), programmes),
                    "slots": len(placed),
                    "solutions": len(programmes),
                    "programmes": programmes,
                },
            )
        for slot, archived in placed:
            if not archived:
                # Ίδια διαδρομή με το χειροκίνητο «στην Παλέτα»: εγγραφή 'unplace'
                # με την παλιά θέση + 🔒 (το «↩️» τα επαναφέρει μαζί).
                slot_history.unplace_placed_slot(db, slot, _break_reason(db, period, slot),
                                                 unlock=True)
    for key, value in data.model_dump().items():
        setattr(period, key, value)
    db.commit()
    db.refresh(period)
    return period


@router.delete("/{period_id}", status_code=204)
def delete_period(
    period_id: int,
    force: bool = Query(False, description="Confirm destructive cascade delete"),
    db: Session = Depends(get_db),
):
    period = db.query(Period).filter(Period.id == period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="Η ώρα δεν βρέθηκε")

    # ── Safety guard ────────────────────────────────────────────────────
    # Deleting a period CASCADE-deletes every lesson placement
    # (timetable_slots) AND availability on that hour, across ALL solutions
    # — it is global and irreversible. Block unless the caller explicitly
    # confirms with ?force=true (the frontend asks the user first).
    if not force:
        slot_count = (
            db.query(TimetableSlot)
            .filter(TimetableSlot.period_id == period_id).count()
        )
        ta_count = (
            db.query(TeacherAvailability)
            .filter(TeacherAvailability.period_id == period_id).count()
        )
        sa_count = (
            db.query(StudentAvailability)
            .filter(StudentAvailability.period_id == period_id).count()
        )
        if slot_count or ta_count or sa_count:
            sol_count = (
                db.query(TimetableSlot.solution_id)
                .filter(TimetableSlot.period_id == period_id)
                .distinct().count()
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "period_in_use",
                    "requires_force": True,
                    "message": (
                        f"Η ώρα «{period.name}» χρησιμοποιείται. Η διαγραφή θα σβήσει "
                        f"ΟΡΙΣΤΙΚΑ {slot_count} τοποθετήσεις μαθημάτων σε {sol_count} "
                        f"προγράμματα και {ta_count + sa_count} δηλώσεις διαθεσιμότητας, "
                        f"σε ΟΛΑ τα προγράμματα. Θέλεις σίγουρα να συνεχίσεις;"
                    ),
                    "slots": slot_count,
                    "solutions": sol_count,
                    "availability": ta_count + sa_count,
                },
            )

    db.delete(period)
    db.commit()


@router.post("/seed-defaults", response_model=list[PeriodResponse], status_code=201)
def seed_default_periods(db: Session = Depends(get_db)):
    """Populate with standard Greek school period schedule."""
    existing = db.query(Period).count()
    if existing > 0:
        raise HTTPException(status_code=409, detail="Υπάρχουν ήδη ώρες — διαγράψτε τις πρώτα")

    defaults = [
        ("1η Ώρα", "1", "14:00", "14:50", False, 1),
        ("2η Ώρα", "2", "15:00", "15:50", False, 2),
        ("3η Ώρα", "3", "16:00", "16:50", False, 3),
        ("4η Ώρα", "4", "17:00", "17:50", False, 4),
        ("5η Ώρα", "5", "18:00", "18:50", False, 5),
        ("6η Ώρα", "6", "19:00", "19:50", False, 6),
        ("7η Ώρα", "7", "20:00", "20:50", False, 7),
        ("8η Ώρα", "8", "21:00", "21:50", False, 8),
    ]

    periods = []
    for name, short, start, end, is_brk, order in defaults:
        period = Period(
            name=name, short_name=short,
            start_time=start, end_time=end,
            is_break=is_brk, sort_order=order,
        )
        db.add(period)
        periods.append(period)

    db.commit()
    for p in periods:
        db.refresh(p)
    return periods
