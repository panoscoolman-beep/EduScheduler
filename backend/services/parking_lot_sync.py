"""Auto-add new lessons to the parking lot of existing solutions.

When a user creates a new Lesson card after the solver has already
produced one or more timetable solutions, those solutions are missing
the new lesson entirely. Re-running the solver would scramble the
existing schedule. Instead, we drop the new lesson into each open
solution's parking lot as `is_unplaced=True` slots, and the user
manually drags them into place.

Granularity decision: one unplaced slot per **periods_per_week** hour,
not per distribution-block. Reasons:
  • The PUT slot endpoint moves a single (day, period, room) at a time
    — it can't atomically place a 2-period block on two consecutive
    cells. Forcing the user to figure that out post-hoc would be
    confusing.
  • Distribution constraints belong to the solver run; a manual add is
    a free-form placement. The user re-arranges as they see fit.

`add_lesson_to_open_solutions` is idempotent: it short-circuits if the
lesson already has slots in the target solution, so calling it twice
won't double-up the parking lot.

`status` filter: only solutions in `optimal` / `feasible` get touched.
We skip `generating`, `infeasible`, `draft` because they're not user-
facing schedules.
"""

from sqlalchemy.orm import Session

from backend.models import Lesson, TimetableSlot, TimetableSolution

UNPLACED_REASON = "Νέο μάθημα — προστέθηκε στο πρόγραμμα μετά την αρχική λύση"
ACTIVE_STATUSES = ("optimal", "feasible")


def add_lesson_to_open_solutions(db: Session, lesson_id: int) -> dict:
    """Append `periods_per_week` unplaced slots for `lesson_id` to every
    optimal/feasible solution. Returns a per-solution summary."""
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        return {"lesson_id": lesson_id, "added_to": [], "skipped": []}

    solutions = (
        db.query(TimetableSolution)
        .filter(TimetableSolution.status.in_(ACTIVE_STATUSES))
        .all()
    )
    added_to: list[dict] = []
    skipped: list[dict] = []

    for sol in solutions:
        existing = (
            db.query(TimetableSlot)
            .filter(
                TimetableSlot.solution_id == sol.id,
                TimetableSlot.lesson_id == lesson.id,
            )
            .count()
        )
        if existing > 0:
            skipped.append({"solution_id": sol.id, "reason": "already_present"})
            continue

        for _ in range(lesson.periods_per_week):
            db.add(
                TimetableSlot(
                    solution_id=sol.id,
                    lesson_id=lesson.id,
                    day_of_week=None,
                    period_id=None,
                    classroom_id=None,
                    is_unplaced=True,
                    unplaced_reason=UNPLACED_REASON,
                )
            )
        added_to.append(
            {"solution_id": sol.id, "slots_added": lesson.periods_per_week}
        )

    db.commit()
    return {
        "lesson_id": lesson.id,
        "added_to": added_to,
        "skipped": skipped,
    }


def add_lessons_to_open_solutions(
    db: Session, lesson_ids: list[int]
) -> list[dict]:
    """Bulk version — used by the CSV importer. Each lesson is wrapped
    in its own commit cycle so a failure on row N doesn't poison earlier
    rows."""
    return [add_lesson_to_open_solutions(db, lid) for lid in lesson_ids]


def sync_lesson_slot_count(db: Session, lesson_id: int) -> dict:
    """Reconcile each active solution so the number of slots for
    `lesson_id` matches the lesson's current `periods_per_week`.

    Called from PUT /lessons/{id} when the user changes hours/week on
    an existing lesson card. Without this hook the change wouldn't
    propagate to existing solutions — adding hours wouldn't show up
    in the parking lot, removing hours wouldn't reduce the schedule.

    Strategy:
      • If a solution has FEWER slots than `periods_per_week`, append
        the missing rows as `is_unplaced=True` so the user can drag
        them onto the grid manually.
      • If a solution has MORE slots, remove the excess but ONLY from
        the unplaced pool. We never delete a slot the user has
        already placed — that would silently destroy their work. If
        unplaced slots aren't enough, we leave the surplus alone and
        flag it in the response.

    Returns a per-solution summary: how many slots were added/removed
    and whether placed slots remain in surplus.
    """
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        return {"lesson_id": lesson_id, "synced": [], "skipped": []}

    target = int(lesson.periods_per_week)

    solutions = (
        db.query(TimetableSolution)
        .filter(TimetableSolution.status.in_(ACTIVE_STATUSES))
        .all()
    )
    synced: list[dict] = []
    skipped: list[dict] = []

    for sol in solutions:
        existing = (
            db.query(TimetableSlot)
            .filter(
                TimetableSlot.solution_id == sol.id,
                TimetableSlot.lesson_id == lesson.id,
            )
            .count()
        )
        if existing == 0:
            # The lesson isn't in this solution at all — `add` semantics
            # apply so the user can place all `target` hours manually.
            for _ in range(target):
                db.add(
                    TimetableSlot(
                        solution_id=sol.id,
                        lesson_id=lesson.id,
                        day_of_week=None,
                        period_id=None,
                        classroom_id=None,
                        is_unplaced=True,
                        unplaced_reason=UNPLACED_REASON,
                    )
                )
            synced.append(
                {"solution_id": sol.id, "added": target, "removed": 0, "surplus_placed": 0}
            )
            continue

        delta = target - existing
        if delta == 0:
            skipped.append({"solution_id": sol.id, "reason": "already_in_sync"})
            continue

        if delta > 0:
            # Need to add `delta` unplaced slots
            for _ in range(delta):
                db.add(
                    TimetableSlot(
                        solution_id=sol.id,
                        lesson_id=lesson.id,
                        day_of_week=None,
                        period_id=None,
                        classroom_id=None,
                        is_unplaced=True,
                        unplaced_reason=UNPLACED_REASON,
                    )
                )
            synced.append(
                {"solution_id": sol.id, "added": delta, "removed": 0, "surplus_placed": 0}
            )
        else:
            # Need to remove |delta| slots — only from the unplaced pool
            to_remove = -delta
            unplaced_slots = (
                db.query(TimetableSlot)
                .filter(
                    TimetableSlot.solution_id == sol.id,
                    TimetableSlot.lesson_id == lesson.id,
                    TimetableSlot.is_unplaced == True,  # noqa: E712
                )
                .order_by(TimetableSlot.id.desc())
                .limit(to_remove)
                .all()
            )
            removed = 0
            for s in unplaced_slots:
                db.delete(s)
                removed += 1
            surplus_placed = max(0, to_remove - removed)
            synced.append(
                {
                    "solution_id": sol.id,
                    "added": 0,
                    "removed": removed,
                    "surplus_placed": surplus_placed,
                }
            )

    db.commit()
    return {
        "lesson_id": lesson.id,
        "target_periods_per_week": target,
        "synced": synced,
        "skipped": skipped,
    }
