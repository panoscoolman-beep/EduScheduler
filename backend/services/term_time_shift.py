"""Bulk time-shift for a scenario (term).

Remaps every period reference of a term by a uniform offset over the
sort_order-ordered teaching periods — e.g. offset=+6 moves the morning block
(1η–6η) to the afternoon (7η–12η). Shifts the term's teacher/student
availability and (optionally) its generated programs' slots. References that
fall outside the period range are dropped (availability) or unplaced (slots).

A uniform shift preserves the relative structure, so a previously conflict-free
program stays conflict-free at the new hours (only out-of-range slots drop out).
"""
from sqlalchemy.orm import Session

from backend.models import (
    Period, TeacherAvailability, StudentAvailability,
    TimetableSolution, TimetableSlot,
)


def _build_period_map(db: Session, offset: int):
    """Return (target_by_id, n_periods). target_by_id[pid] = new pid or None."""
    teaching = (
        db.query(Period).filter(Period.is_break == False)  # noqa: E712
        .order_by(Period.sort_order).all()
    )
    ids = [p.id for p in teaching]
    index_by_id = {pid: i for i, pid in enumerate(ids)}
    target = {}
    for pid, i in index_by_id.items():
        j = i + offset
        target[pid] = ids[j] if 0 <= j < len(ids) else None
    return target, len(ids)


def shift_term_times(db: Session, term_id: int, offset: int, shift_solutions: bool = True) -> dict:
    """Apply a uniform period offset to a term. Caller commits. Returns counts."""
    target, _ = _build_period_map(db, offset)
    res = {"availability_moved": 0, "availability_dropped": 0,
           "slots_moved": 0, "slots_unplaced": 0}

    # ── Availability: snapshot → delete → re-insert shifted (avoids unique clashes)
    for model, fk in ((TeacherAvailability, "teacher_id"), (StudentAvailability, "student_id")):
        rows = db.query(model).filter(model.term_id == term_id).all()
        snapshot = [
            {"fk": getattr(r, fk), "day": r.day_of_week, "pid": r.period_id, "status": r.status}
            for r in rows
        ]
        db.query(model).filter(model.term_id == term_id).delete()
        db.flush()
        seen = set()
        for row in snapshot:
            np = target.get(row["pid"])
            if np is None:
                res["availability_dropped"] += 1
                continue
            key = (row["fk"], row["day"], np)
            if key in seen:
                continue
            seen.add(key)
            db.add(model(term_id=term_id, day_of_week=row["day"], period_id=np,
                         status=row["status"], **{fk: row["fk"]}))
            res["availability_moved"] += 1

    # ── Solution slots (optional): shift placed slots; unplace out-of-range
    if shift_solutions:
        sol_ids = [s.id for s in db.query(TimetableSolution).filter(TimetableSolution.term_id == term_id).all()]
        if sol_ids:
            slots = (
                db.query(TimetableSlot)
                .filter(TimetableSlot.solution_id.in_(sol_ids), TimetableSlot.is_unplaced == False)  # noqa: E712
                .all()
            )
            for s in slots:
                np = target.get(s.period_id)
                if np is None:
                    s.is_unplaced = True
                    s.day_of_week = None
                    s.period_id = None
                    s.classroom_id = None
                    s.unplaced_reason = "Εκτός εύρους ωρών μετά τη μετατόπιση"
                    res["slots_unplaced"] += 1
                else:
                    s.period_id = np
                    res["slots_moved"] += 1

    return res
