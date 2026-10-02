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

Ασφάλεια (1/10/2026): η αναίρεση/επανάληψη ΔΕΝ γράφει πια τυφλά την παλιά
θέση. Πριν αλλάξει οτιδήποτε ελέγχει:
  • σύγκρουση (καθηγητής / τμήμα / αίθουσα / κοινός μαθητής) στο κελί-στόχο
    → 409 `HistoryConflict`, ΤΙΠΟΤΑ δεν αλλάζει και το ιστορικό μένει ίδιο
    (ο χρήστης μετακινεί την κάρτα που πιάνει τη θέση και ξαναδοκιμάζει).
    Εξαίρεση: τα δύο «move» ενός swap (κάρτα πάνω σε κάρτα) — αν το ένα μόνο
    του θα έφερνε δύο κάρτες στο ίδιο κελί, αναιρούνται/επαναλαμβάνονται ΜΑΖΙ.
    Όταν δεν υπάρχει σύγκρουση, όλα γίνονται βήμα-βήμα όπως πριν.
  • θέση που δεν υπάρχει πια (αίθουσα/ώρα διαγράφηκε) → η εγγραφή
    παραλείπεται (σημαδεύεται, χωρίς να αγγιχτεί το slot) και επιστρέφεται 409
    με εξήγηση· το επόμενο Ctrl+Z συνεχίζει με τις παλαιότερες. Πριν: 500 σε
    κάθε Ctrl+Z και «κολλημένο» ιστορικό.
  • ώρα που είναι ΤΩΡΑ διάλειμμα (αναστρέψιμο) → 409 `break_hour` (δομημένο,
    `BreakHourConflict`) χωρίς καμία αλλαγή· όταν η ώρα ξαναγίνει διδακτική, η
    ίδια αναίρεση επαναφέρει την κάρτα. Με ρητή επιβεβαίωση του χρήστη
    (`skip_break=True`) οι εγγραφές αυτές παραλείπονται ΟΠΩΣ οι «νεκρές»
    (σημαδεύονται, η κάρτα δεν αγγίζεται) και η ίδια ενέργεια ΣΥΝΕΧΙΖΕΙ με την
    επόμενη εφαρμόσιμη — αλλιώς οι παλαιότερες αλλαγές θα ήταν απρόσιτες.
  • σφάλμα βάσης στο flush → rollback + 409 (ποτέ 500).
"""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.models import Classroom, Period, Student, TimetableSlot, TimetableSlotHistory
from backend.services import lesson_roster
from backend.services import placement_conflicts as pc

_UNDO, _REDO = "undo", "redo"
_STATE_FIELDS = ("day_of_week", "period_id", "classroom_id", "is_locked", "is_unplaced")


class HistoryConflict(HTTPException):
    """409: η αναίρεση/επανάληψη δεν έγινε — το `detail` (string) λέει γιατί."""

    def __init__(self, message: str):
        super().__init__(status_code=409, detail=message)


class BreakHourConflict(HTTPException):
    """409 `break_hour`: η ώρα-στόχος είναι τώρα διάλειμμα. Δομημένο detail, ώστε
    το frontend να προσφέρει «παράλειψη και συνέχεια» (`skip_break=true`)."""

    def __init__(self, entry: TimetableSlotHistory, period_name: str, direction: str):
        if direction == _UNDO:
            what, rest = "η αναίρεση", "τις παλαιότερες"
        else:
            what, rest = "η επανάληψη", "τις επόμενες"
        message = (f"Η «{period_name}» είναι τώρα διάλειμμα — {what} αυτής της αλλαγής θα "
                   "έβαζε την κάρτα σε διάλειμμα. Μπορείς να την παραλείψεις και να συνεχίσεις "
                   f"με {rest} αλλαγές, ή να ξανακάνεις την ώρα διδακτική. Δεν άλλαξε τίποτα.")
        super().__init__(status_code=409, detail={
            "code": "break_hour", "requires_force": True, "entry_id": entry.id,
            "period": period_name, "message": message,
        })


class _Skip(Exception):
    """Εσωτερικό: η θέση-στόχος της εγγραφής δεν μπορεί να εφαρμοστεί.
    kind = "dead" (αίθουσα/ώρα διαγράφηκε) ή "break" (ώρα-διάλειμμα, μόνο με
    skip_break)."""

    def __init__(self, entry: TimetableSlotHistory, reason: str, kind: str = "dead"):
        super().__init__(reason)
        self.entry = entry
        self.reason = reason
        self.kind = kind


@dataclass
class StepResult:
    """Αποτέλεσμα ενός undo/redo: η εγγραφή που εφαρμόστηκε (None = τίποτα) και
    πόσες εγγραφές σε ώρα-διάλειμμα παραλείφθηκαν (μόνο με skip_break)."""
    entry: TimetableSlotHistory | None
    skipped_break: int = 0


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


def _latest_active(db: Session, solution_id: int, before_id: int | None = None):
    """Η νεότερη ΜΗ αναιρεμένη εγγραφή (προαιρετικά: παλαιότερη από before_id)."""
    q = db.query(TimetableSlotHistory).filter(
        TimetableSlotHistory.solution_id == solution_id,
        TimetableSlotHistory.undone == False,  # noqa: E712
    )
    if before_id is not None:
        q = q.filter(TimetableSlotHistory.id < before_id)
    return q.order_by(TimetableSlotHistory.id.desc()).first()


def _next_redoable(db: Session, solution_id: int, after_id: int | None = None):
    """Η παλαιότερη αναιρεμένη εγγραφή μετά την τελευταία ενεργή (ο κλάδος
    redo) — προαιρετικά: η επόμενη μετά το after_id."""
    last_active = _latest_active(db, solution_id)
    floor = max(last_active.id if last_active else 0, after_id or 0)
    return (
        db.query(TimetableSlotHistory)
        .filter(
            TimetableSlotHistory.solution_id == solution_id,
            TimetableSlotHistory.undone == True,  # noqa: E712
            TimetableSlotHistory.id > floor,
        )
        .order_by(TimetableSlotHistory.id.asc())
        .first()
    )


def _target_state(entry: TimetableSlotHistory, direction: str) -> dict:
    side = "prev" if direction == _UNDO else "new"
    return {f: getattr(entry, f"{side}_{f}") for f in _STATE_FIELDS}


def _unusable(db: Session, state: dict) -> str | None:
    """Γιατί η θέση-στόχος δεν μπορεί πια ΠΟΤΕ να εφαρμοστεί (None = μπορεί):
    διαγραμμένη αίθουσα/ώρα ή ελλιπής θέση → η εγγραφή παραλείπεται.
    Η Παλέτα εφαρμόζεται πάντα."""
    if state["is_unplaced"]:
        return None
    if state["day_of_week"] is None or state["period_id"] is None or state["classroom_id"] is None:
        return "η θέση της είναι ελλιπής"
    if db.query(Period.id).filter(Period.id == state["period_id"]).first() is None:
        return "η ώρα της δεν υπάρχει πια (διαγράφηκε)"
    if db.query(Classroom.id).filter(Classroom.id == state["classroom_id"]).first() is None:
        return "η αίθουσά της δεν υπάρχει πια (διαγράφηκε)"
    return None


def _break_now(db: Session, state: dict) -> Period | None:
    """Η ώρα-στόχος, αν είναι ΤΩΡΑ διάλειμμα — αναστρέψιμο (ξαναγίνεται
    διδακτική), οπότε η εγγραφή παραλείπεται ΜΟΝΟ με ρητή επιβεβαίωση
    (skip_break)· αλλιώς άρνηση με εξήγηση και ιστορικό ανέγγιχτο."""
    if state["is_unplaced"] or state["period_id"] is None:
        return None
    period = db.query(Period).filter(Period.id == state["period_id"]).first()
    return period if period is not None and period.is_break else None


def _is_swap_pair(a: TimetableSlotHistory, b: TimetableSlotHistory) -> bool:
    """Τα δύο «move» ενός swap: η μία κάρτα πήγε εκεί από όπου έφυγε η άλλη
    και αντίστροφα (το swap_slots τα γράφει διαδοχικά)."""
    if a.slot_id == b.slot_id or a.operation != "move" or b.operation != "move":
        return False
    if a.prev_is_unplaced or a.new_is_unplaced or b.prev_is_unplaced or b.new_is_unplaced:
        return False
    return ((a.prev_day_of_week, a.prev_period_id) == (b.new_day_of_week, b.new_period_id)
            and (b.prev_day_of_week, b.prev_period_id) == (a.new_day_of_week, a.new_period_id))


def _clash_reason(db: Session, solution_id: int, changes: list[tuple], direction: str) -> str | None:
    """Θα δημιουργούσε η εφαρμογή των `changes` [(slot, state)] διπλοκράτηση;

    Ελέγχει ΜΟΝΟ σκληρές συγκρούσεις — καθηγητής, τμήμα, αίθουσα, κοινός
    μαθητής (όχι κωλύματα) — και μόνο για slot που πράγματι μετακινείται: όσο
    μένει στη θέση του δεν «φτιάχνει» νέα σύγκρουση. Pure read."""
    moving = {slot.id for slot, _ in changes}
    for slot, state in changes:
        if state["is_unplaced"]:
            continue
        cell = (state["day_of_week"], state["period_id"])
        same_cell = (not slot.is_unplaced) and (slot.day_of_week, slot.period_id) == cell
        if same_cell and slot.classroom_id == state["classroom_id"]:
            continue
        occupants = [
            (other, other.classroom_id)
            for other in db.query(TimetableSlot).filter(
                TimetableSlot.solution_id == solution_id,
                TimetableSlot.is_unplaced == False,  # noqa: E712
                TimetableSlot.day_of_week == cell[0],
                TimetableSlot.period_id == cell[1],
                TimetableSlot.id.notin_(sorted(moving)),
            ).all()
        ]
        occupants += [
            (other, other_state["classroom_id"]) for other, other_state in changes
            if other.id != slot.id and not other_state["is_unplaced"]
            and (other_state["day_of_week"], other_state["period_id"]) == cell
        ]
        if not occupants:
            continue
        lesson = slot.lesson
        mine = set() if same_cell else lesson_roster.students_of(db, lesson)
        rosters = lesson_roster.roster_map(db, [o.lesson for o, _ in occupants if o.lesson]) if mine else {}
        reason = None
        for other, room in occupants:
            other_lesson = other.lesson
            info = pc.describe_slot(db, other)
            if not same_cell and other_lesson.teacher_id == lesson.teacher_id:
                reason = f"ο καθηγητής {info['teacher']} διδάσκει ήδη {pc.lesson_phrase(info)}"
            elif not same_cell and other_lesson.class_id == lesson.class_id:
                reason = (f"το τμήμα {info['class_name']} κάνει ήδη {info['subject'] or 'άλλο μάθημα'}"
                          + (f" με {info['teacher']}" if info["teacher"] else ""))
            elif room == state["classroom_id"]:
                room_obj = db.query(Classroom).filter(Classroom.id == room).first()
                reason = (f"η αίθουσα {room_obj.name if room_obj else ''} είναι πιασμένη από "
                          f"{info['subject']}" + (f" στο {info['class_name']}" if info["class_name"] else ""))
            elif other_lesson.id != lesson.id and mine & rosters.get(other_lesson.id, set()):
                shared = sorted(mine & rosters[other_lesson.id])
                student = db.query(Student).filter(Student.id == shared[0]).first()
                reason = (f"ο/η {pc.student_display(student)} είναι και στο {info['class_name']}, "
                          f"που έχει {info['subject']}")
            if reason:
                break
        if reason:
            me = pc.describe_slot(db, slot)
            label = pc.lesson_phrase({"subject": me["subject"], "class_name": me["class_name"]})
            period = db.query(Period).filter(Period.id == cell[1]).first()
            verb = "θα ξαναγύριζε" if direction == _UNDO else "θα ξαναπήγαινε"
            return (f"η κάρτα «{label}» {verb} σε θέση που δεν είναι πια ελεύθερη "
                    f"({pc.cell_label(cell[0], period)}): {reason}")
    return None


def _apply(slot: TimetableSlot, state: dict, direction: str) -> None:
    slot.day_of_week = state["day_of_week"]
    slot.period_id = state["period_id"]
    slot.classroom_id = state["classroom_id"]
    slot.is_locked = state["is_locked"]
    slot.is_unplaced = state["is_unplaced"]
    if slot.is_unplaced:
        slot.unplaced_reason = slot.unplaced_reason or (
            "Επαναφορά από undo" if direction == _UNDO else "Επαναφορά από redo")
    else:
        slot.unplaced_reason = None


def _step(db: Session, solution_id: int, direction: str,
          skip_break: bool = False) -> list[TimetableSlotHistory] | None:
    """Ένα βήμα undo/redo ΧΩΡΙΣ commit. Επιστρέφει τις εγγραφές που
    εφαρμόστηκαν (1, ή 2 για τα δύο μισά ενός swap) ή None αν δεν υπάρχει
    τίποτα. Σηκώνει `_Skip` (θέση που δεν υπάρχει πια, ή — με skip_break —
    ώρα-διάλειμμα), `BreakHourConflict` (ώρα-διάλειμμα χωρίς skip_break) ή
    `HistoryConflict` (διπλοκράτηση). Σε όλα: τίποτα δεν άλλαξε."""
    entry = (_latest_active(db, solution_id) if direction == _UNDO
             else _next_redoable(db, solution_id))
    if entry is None:
        return None
    slot = db.query(TimetableSlot).filter(TimetableSlot.id == entry.slot_id).first()
    if slot is None:
        return None
    state = _target_state(entry, direction)
    reason = _unusable(db, state)
    if reason:
        raise _Skip(entry, reason)
    action = "Η αναίρεση" if direction == _UNDO else "Η επανάληψη"
    on_break = _break_now(db, state)
    if on_break is not None:
        if skip_break:
            raise _Skip(entry, f"η «{on_break.name}» είναι τώρα διάλειμμα", kind="break")
        raise BreakHourConflict(entry, on_break.name, direction)

    group = [(entry, slot, state)]
    clash = _clash_reason(db, solution_id, [(slot, state)], direction)
    if clash:
        # Μισό swap; τότε τα δύο μαζί (η άλλη κάρτα αδειάζει ταυτόχρονα το κελί).
        partner = (_latest_active(db, solution_id, before_id=entry.id) if direction == _UNDO
                   else _next_redoable(db, solution_id, after_id=entry.id))
        if partner is not None and _is_swap_pair(entry, partner):
            partner_slot = db.query(TimetableSlot).filter(TimetableSlot.id == partner.slot_id).first()
            partner_state = _target_state(partner, direction)
            if (partner_slot is not None and not _unusable(db, partner_state)
                    and not _break_now(db, partner_state)):
                both = [(slot, state), (partner_slot, partner_state)]
                clash = _clash_reason(db, solution_id, both, direction)
                if not clash:
                    group.append((partner, partner_slot, partner_state))
    if clash:
        raise HistoryConflict(
            f"{action} δεν έγινε: {clash}. Δεν άλλαξε τίποτα — μετακίνησε πρώτα την άλλη "
            "κάρτα και ξαναδοκίμασε.")

    for item, item_slot, item_state in group:
        _apply(item_slot, item_state, direction)
        item.undone = direction == _UNDO
    try:
        db.flush()
    except SQLAlchemyError:
        db.rollback()
        raise HistoryConflict(f"{action} δεν μπορεί να γίνει — κάτι άλλαξε στο μεταξύ. "
                              "Δεν άλλαξε τίποτα.")
    return [item for item, _, _ in group]


def _mark_skipped(db: Session, entry: TimetableSlotHistory, *, undone: bool) -> None:
    """Η εγγραφή περνά στην άλλη στοίβα χωρίς να αγγιχτεί το slot (commit εδώ,
    γιατί ο caller απαντά με 409 και δεν κάνει commit)."""
    entry.undone = undone
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HistoryConflict("Η αλλαγή δεν μπορεί να γίνει — κάτι άλλαξε στο μεταξύ. "
                              "Δεν άλλαξε τίποτα.")


def _skipped_note(skipped: int) -> str:
    return f" (Παραλείφθηκαν και {skipped} αλλαγές σε ώρες-διαλείμματα.)" if skipped else ""


def _run(db: Session, solution_id: int, direction: str, skip_break: bool) -> StepResult:
    """Undo/redo ενός βήματος. Με skip_break οι εγγραφές σε ώρα-διάλειμμα
    παραλείπονται (σημαδεύονται όπως οι «νεκρές», η κάρτα δεν αγγίζεται) και
    συνεχίζει με την επόμενη εφαρμόσιμη. Σε διπλοκράτηση μετά από παραλείψεις
    → rollback ΟΛΟΥ του αιτήματος (τίποτα δεν κρατιέται) και 409."""
    undone = direction == _UNDO
    skipped = 0
    while True:
        try:
            done = _step(db, solution_id, direction, skip_break=skip_break)
        except _Skip as skip:
            if skip.kind == "break":
                skip.entry.undone = undone
                db.flush()
                skipped += 1
                continue
            _mark_skipped(db, skip.entry, undone=undone)
            if undone:
                raise HistoryConflict(
                    f"Η αλλαγή δεν αναιρέθηκε: {skip.reason}. Η κάρτα έμεινε όπου είναι και η "
                    "αλλαγή παραλείφθηκε — πάτα ξανά ↩️ για την προηγούμενη."
                    + _skipped_note(skipped))
            raise HistoryConflict(
                f"Η αλλαγή δεν επαναλήφθηκε: {skip.reason}. Η κάρτα έμεινε όπου είναι και η "
                "αλλαγή παραλείφθηκε — πάτα ξανά ↪ για την επόμενη." + _skipped_note(skipped))
        except HistoryConflict:
            if skipped:
                db.rollback()
            raise
        return StepResult(done[0] if done else None, skipped)


def undo_step(db: Session, solution_id: int, *, skip_break: bool = False) -> StepResult:
    """Αναίρεση της πιο πρόσφατης αλλαγής (βλ. _run). 409 `HistoryConflict` αν θα
    δημιουργούσε διπλοκράτηση ή αν η παλιά θέση δεν υπάρχει πια (η εγγραφή
    παραλείπεται — commit εδώ). 409 `BreakHourConflict` αν η ώρα είναι τώρα
    διάλειμμα και δεν δόθηκε skip_break. Χωρίς commit στην επιτυχία (ο caller)."""
    return _run(db, solution_id, _UNDO, skip_break)


def redo_step(db: Session, solution_id: int, *, skip_break: bool = False) -> StepResult:
    """Επανάληψη της πιο πρόσφατα αναιρεμένης αλλαγής — ίδιοι κανόνες με το undo_step."""
    return _run(db, solution_id, _REDO, skip_break)


def undo(db: Session, solution_id: int) -> TimetableSlotHistory | None:
    """Roll back the most recent un-undone edit. Returns the affected
    history row, or None if there's nothing to undo (βλ. undo_step)."""
    return undo_step(db, solution_id).entry


def redo(db: Session, solution_id: int) -> TimetableSlotHistory | None:
    """Re-apply the most recent undone edit (the one undo() just rolled
    back). Returns the affected row, or None if redo isn't available."""
    return redo_step(db, solution_id).entry


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


# ─── 🕘 λίστα ιστορικού + «αναίρεση μέχρι εδώ» ──────────────────────────

_DAY_SHORT = ["Δευ", "Τρι", "Τετ", "Πεμ", "Παρ", "Σαβ", "Κυρ"]
_OPERATION_LABELS = {
    "move": "Μετακίνηση", "lock": "Κλείδωμα", "unlock": "Ξεκλείδωμα",
    "place": "Τοποθέτηση", "unplace": "Στην Παλέτα",
}


def _position(day, period_id, room_id, unplaced, periods: dict, rooms: dict) -> str:
    """«Δευ 3η · Αίθ 2» ή «Παλέτα»."""
    if unplaced or day is None or period_id is None:
        return "Παλέτα"
    period = periods.get(period_id)
    label = f"{_DAY_SHORT[day] if 0 <= day < 7 else day} {period.short_name if period else ''}".strip()
    return f"{label} · {rooms[room_id]}" if room_id in rooms else label


def history_entries(db: Session, solution_id: int, limit: int = 20) -> dict:
    """Οι τελευταίες αλλαγές (νεότερες πρώτα) με ανθρώπινη περιγραφή."""
    from backend.models import Classroom, Lesson, Period

    rows = (
        db.query(TimetableSlotHistory)
        .filter(TimetableSlotHistory.solution_id == solution_id)
        .order_by(TimetableSlotHistory.id.desc())
        .limit(max(1, min(int(limit), 100)))
        .all()
    )
    periods = {p.id: p for p in db.query(Period).all()}
    rooms = {r.id: r.name for r in db.query(Classroom).all()}
    slot_ids = {r.slot_id for r in rows}
    lessons = {}
    if slot_ids:
        for slot in db.query(TimetableSlot).filter(TimetableSlot.id.in_(slot_ids)).all():
            lesson = db.query(Lesson).filter(Lesson.id == slot.lesson_id).first()
            if lesson:
                parts = [lesson.subject.name if lesson.subject else "",
                         lesson.school_class.name if lesson.school_class else "",
                         lesson.teacher.name if lesson.teacher else ""]
                lessons[slot.id] = " · ".join(p for p in parts if p)
    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "performed_at": r.performed_at.isoformat() if r.performed_at else None,
            "operation": r.operation,
            "operation_label": _OPERATION_LABELS.get(r.operation, r.operation),
            "undone": bool(r.undone),
            "lesson": lessons.get(r.slot_id, ""),
            "from": _position(r.prev_day_of_week, r.prev_period_id, r.prev_classroom_id,
                              r.prev_is_unplaced, periods, rooms),
            "to": _position(r.new_day_of_week, r.new_period_id, r.new_classroom_id,
                            r.new_is_unplaced, periods, rooms),
        })
    return {"items": items, "summary": history_summary(db, solution_id)}


def undo_to(db: Session, solution_id: int, entry_id: int) -> int:
    """Αναίρεση της αλλαγής `entry_id` ΚΑΙ όλων των νεότερων (βλ. undo_to_counts).
    Επιστρέφει πόσες αναιρέθηκαν."""
    return undo_to_counts(db, solution_id, entry_id)[0]


def undo_to_counts(db: Session, solution_id: int, entry_id: int, *,
                   skip_break: bool = False) -> tuple[int, int]:
    """Αναίρεση της αλλαγής `entry_id` ΚΑΙ όλων των νεότερων, με τη σωστή σειρά.
    Επιστρέφει (αναιρέθηκαν, παραλείφθηκαν σε ώρα-διάλειμμα).

    Δεν κάνει commit (all-or-nothing στον caller). ValueError αν η αλλαγή δεν
    ανήκει στο πρόγραμμα ή έχει ήδη αναιρεθεί, ή αν κάποιο βήμα θα δημιουργούσε
    διπλοκράτηση (τότε ο caller κάνει rollback — τίποτα δεν αλλάζει). Αλλαγές
    που δείχνουν σε αίθουσα/ώρα που δεν υπάρχει πια παραλείπονται (η κάρτα
    μένει όπου είναι) και δεν μετρούν. Ώρα-διάλειμμα: `BreakHourConflict` (ο
    caller κάνει rollback), εκτός αν skip_break — τότε παραλείπεται και η
    αναίρεση συνεχίζει ως το `entry_id`. Αναστρέψιμο με redo()."""
    target = (
        db.query(TimetableSlotHistory)
        .filter(TimetableSlotHistory.id == entry_id,
                TimetableSlotHistory.solution_id == solution_id)
        .first()
    )
    if target is None:
        raise ValueError("Η αλλαγή δεν βρέθηκε σε αυτό το πρόγραμμα.")
    if target.undone:
        raise ValueError("Η αλλαγή έχει ήδη αναιρεθεί.")
    count = skipped = 0
    while True:
        latest = (
            db.query(TimetableSlotHistory)
            .filter(TimetableSlotHistory.solution_id == solution_id,
                    TimetableSlotHistory.undone == False)  # noqa: E712
            .order_by(TimetableSlotHistory.id.desc())
            .first()
        )
        if latest is None or latest.id < entry_id:
            return count, skipped
        try:
            done = _step(db, solution_id, _UNDO, skip_break=skip_break)
        except _Skip as skip:
            skip.entry.undone = True
            db.flush()
            skipped += skip.kind == "break"
            continue
        except HistoryConflict as exc:
            raise ValueError(exc.detail) from exc
        if done is None:
            raise ValueError("Μια αλλαγή δεν μπορεί να αναιρεθεί (η ώρα δεν υπάρχει πια).")
        count += len(done)


def remap_periods(db: Session, solution_ids: list[int], target: dict) -> int:
    """«Μετατόπιση ωρών» (term_time_shift): οι θέσεις του ιστορικού ακολουθούν
    τα slots, ώστε το Ctrl+Z να γυρίζει την κάρτα στο ΜΕΤΑΤΟΠΙΣΜΕΝΟ ισοδύναμο
    της παλιάς ώρας (πριν: στην προ-μετατόπισης ώρα, μία ώρα «δίπλα»).

    `target` = ο ΙΔΙΟΣ χάρτης με τα slots ({διδακτική ώρα: νέα ώρα | None}).
    Για κάθε πλευρά (prev/new) με τοποθετημένη θέση σε ΔΙΔΑΚΤΙΚΗ ώρα:
      • εντός εύρους → η νέα ώρα·
      • εκτός εύρους → Παλέτα, όπως ακριβώς το ίδιο το slot (το 🔒 μένει όπως
        ήταν, όπως και στο slot).
    Ώρα που ΔΕΝ είναι διδακτική τώρα (διάλειμμα ή διαγραμμένη) δεν έχει
    μετατοπισμένο ισοδύναμο → μένει ως έχει (η παλιά θέση δεν χάνεται): το undo
    αρνείται/εξηγεί αντί να μαντέψει. Καμία εγγραφή δεν σβήνεται. Χωρίς commit
    (ίδια συναλλαγή με τη μετατόπιση). Επιστρέφει πόσες εγγραφές άλλαξαν."""
    if not solution_ids:
        return 0
    changed = 0
    rows = (db.query(TimetableSlotHistory)
            .filter(TimetableSlotHistory.solution_id.in_(solution_ids)).all())
    for row in rows:
        touched = False
        for side in ("prev", "new"):
            pid = getattr(row, f"{side}_period_id")
            if getattr(row, f"{side}_is_unplaced") or pid is None or pid not in target:
                continue
            new_pid = target[pid]
            if new_pid is None:
                setattr(row, f"{side}_day_of_week", None)
                setattr(row, f"{side}_period_id", None)
                setattr(row, f"{side}_classroom_id", None)
                setattr(row, f"{side}_is_unplaced", True)
            else:
                setattr(row, f"{side}_period_id", new_pid)
            touched = True
        changed += int(touched)
    db.flush()
    return changed


def unplace_placed_slot(db: Session, slot: TimetableSlot, reason: str, *, unlock: bool = False):
    """Τοποθετημένη ώρα → Παλέτα + εγγραφή 'unplace' στο ιστορικό (χωρίς commit).

    `unlock=True` βγάζει και το 🔒 (το «↩️» το επαναφέρει μαζί με τη θέση).
    Επιστρέφει (history entry, νέα κατάσταση)."""
    prev_state = {
        "day_of_week": slot.day_of_week,
        "period_id": slot.period_id,
        "classroom_id": slot.classroom_id,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": False,
    }
    if unlock:
        slot.is_locked = False
    slot.day_of_week = None
    slot.period_id = None
    slot.classroom_id = None
    slot.is_unplaced = True
    slot.unplaced_reason = reason
    new_state = {
        "day_of_week": None,
        "period_id": None,
        "classroom_id": None,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": True,
    }
    entry = record_edit(db, slot, prev_state, new_state, "unplace")
    return entry, new_state
