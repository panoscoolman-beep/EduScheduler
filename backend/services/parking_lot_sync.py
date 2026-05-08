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
