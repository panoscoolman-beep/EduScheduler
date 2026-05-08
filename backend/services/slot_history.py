"""Slot edit history — audit log + undo/redo state machine.

Tracks every manual edit a user makes to a timetable slot so they can
walk back recent moves with Ctrl+Z. Lives entirely in the
`timetable_slot_history` table; no in-memory state.

Semantics (standard editor behavior):
  • record(slot, prev, new) — appends one row, default `undone=False`.
    If the *latest* sequence of rows is `undone=True` (i.e. the user
    just undid something) and they now make a NEW edit, those undone
    rows are deleted first — making the redo branch unreachable, as
    every editor does.
  • undo() — picks the latest non-undone row, resets the slot to the
    prev_* fields, marks the row undone.
  • redo() — picks the most-recent undone row that's newer than the
    most-recent non-undone row, applies new_* fields, clears undone.
"""

from sqlalchemy.orm import Session

from backend.models import TimetableSlot, TimetableSlotHistory


def _slot_state(slot: TimetableSlot) -> dict:
    return {
        "day_of_week": slot.day_of_week,
        "period_id": slot.period_id,
        "classroom_id": slot.classroom_id,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": bool(slot.is_unplaced),
    }


def record_edit(
    db: Session,
    slot: TimetableSlot,
    prev: dict,
    new: dict,
    operation: str = "move",
) -> TimetableSlotHistory:
    """Persist an edit. If we're sitting on an undone tail, drop it
    first so the redo branch becomes unreachable (editor convention)."""
    _drop_undone_tail(db, slot.solution_id)

    entry = TimetableSlotHistory(
        solution_id=slot.solution_id,
        slot_id=slot.id,
        operation=operation,
        prev_day_of_week=prev["day_of_week"],
        prev_period_id=prev["period_id"],
        prev_classroom_id=prev["classroom_id"],
        prev_is_locked=prev["is_locked"],
        prev_is_unplaced=prev["is_unplaced"],
        new_day_of_week=new["day_of_week"],
        new_period_id=new["period_id"],
        new_classroom_id=new["classroom_id"],
        new_is_locked=new["is_locked"],
        new_is_unplaced=new["is_unplaced"],
        undone=False,
    )
    db.add(entry)
    db.flush()
    return entry


def undo(db: Session, solution_id: int) -> TimetableSlotHistory | None:
    """Roll back the most recent un-undone edit. Returns the affected
    history row, or None if there's nothing to undo."""
    entry = (
        db.query(TimetableSlotHistory)
        .filter(
            TimetableSlotHistory.solution_id == solution_id,
            TimetableSlotHistory.undone == False,  # noqa: E712
        )
        .order_by(TimetableSlotHistory.id.desc())
        .first()
    )
    if not entry:
        return None

    slot = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.id == entry.slot_id)
        .first()
    )
    if not slot:
        return None

    slot.day_of_week = entry.prev_day_of_week
    slot.period_id = entry.prev_period_id
    slot.classroom_id = entry.prev_classroom_id
    slot.is_locked = entry.prev_is_locked
    slot.is_unplaced = entry.prev_is_unplaced
    if slot.is_unplaced:
        slot.unplaced_reason = slot.unplaced_reason or "Επαναφορά από undo"
    else:
        slot.unplaced_reason = None
    entry.undone = True
    db.flush()
    return entry


def redo(db: Session, solution_id: int) -> TimetableSlotHistory | None:
    """Re-apply the most recent undone edit (the one undo() just rolled
    back). Returns the affected row, or None if redo isn't available."""
    last_active = (
        db.query(TimetableSlotHistory)
        .filter(
            TimetableSlotHistory.solution_id == solution_id,
            TimetableSlotHistory.undone == False,  # noqa: E712
        )
        .order_by(TimetableSlotHistory.id.desc())
        .first()
    )
    last_active_id = last_active.id if last_active else 0

    entry = (
        db.query(TimetableSlotHistory)
        .filter(
            TimetableSlotHistory.solution_id == solution_id,
            TimetableSlotHistory.undone == True,  # noqa: E712
            TimetableSlotHistory.id > last_active_id,
        )
        .order_by(TimetableSlotHistory.id.asc())
        .first()
    )
    if not entry:
        return None

    slot = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.id == entry.slot_id)
        .first()
    )
    if not slot:
        return None

    slot.day_of_week = entry.new_day_of_week
    slot.period_id = entry.new_period_id
    slot.classroom_id = entry.new_classroom_id
    slot.is_locked = entry.new_is_locked
    slot.is_unplaced = entry.new_is_unplaced
    if slot.is_unplaced:
        slot.unplaced_reason = slot.unplaced_reason or "Επαναφορά από redo"
    else:
        slot.unplaced_reason = None
    entry.undone = False
    db.flush()
    return entry


def history_summary(db: Session, solution_id: int) -> dict:
    """Lightweight snapshot for the UI: counts of available undo/redo."""
    rows = (
        db.query(TimetableSlotHistory)
        .filter(TimetableSlotHistory.solution_id == solution_id)
        .order_by(TimetableSlotHistory.id.asc())
        .all()
    )
    can_undo = sum(1 for r in rows if not r.undone)
    can_redo = 0
    last_active_id = max((r.id for r in rows if not r.undone), default=0)
    for r in rows:
        if r.undone and r.id > last_active_id:
            can_redo += 1
    return {"can_undo": can_undo, "can_redo": can_redo, "total": len(rows)}


def _drop_undone_tail(db: Session, solution_id: int) -> None:
    """Delete every undone entry that comes AFTER the most recent
    non-undone entry. Called before a new edit so that fresh user
    actions invalidate the redo path (standard editor behavior)."""
    last_active = (
        db.query(TimetableSlotHistory)
        .filter(
            TimetableSlotHistory.solution_id == solution_id,
            TimetableSlotHistory.undone == False,  # noqa: E712
        )
        .order_by(TimetableSlotHistory.id.desc())
        .first()
    )
    last_active_id = last_active.id if last_active else 0
    db.query(TimetableSlotHistory).filter(
        TimetableSlotHistory.solution_id == solution_id,
        TimetableSlotHistory.undone == True,  # noqa: E712
        TimetableSlotHistory.id > last_active_id,
    ).delete(synchronize_session=False)
