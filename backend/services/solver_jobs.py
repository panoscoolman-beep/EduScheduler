"""Solver background-job helpers (extracted from routers/solver.py).

The /generate and /regenerate routes are intentionally thin: they validate,
create a `generating` solution row, then hand off to `_run_generation_job` as a
FastAPI background task. That worker — plus its result-persistence, the
one-solve-at-a-time concurrency guard, and the explicit-UTC serializer the
response models use — lives here so solver.py stays a routing layer.
"""

import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import TimetableSolution, TimetableSlot
from backend.services.feasibility import check_feasibility
from backend.solver.engine import TimetableSolver


def _iso_utc(dt: datetime | None) -> str | None:
    """Serialize a stored naive-UTC datetime as an explicit-UTC ISO string
    (…+00:00) so the frontend's new Date() reads it as UTC and renders the
    correct local time, instead of mistaking naive-UTC for local."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _persist_solver_result(
    db: Session,
    solution: TimetableSolution,
    result,
    locked_assignments: list[dict] | None = None,
    extra_stats: dict | None = None,
) -> None:
    """Write a solver result onto its solution row + slots.

    When `locked_assignments` is given (regenerate flow), placed slots that
    match a locked assignment keep is_locked=True so the user's pins survive
    into the new solution."""
    solution.status = result.status
    solution.score = result.score
    stats = dict(result.stats)
    if extra_stats:
        stats.update(extra_stats)

    # When the solve is infeasible, attach the per-entity feasibility
    # reasons (overloaded teacher, missing lab, …) so the UI can explain
    # *why* instead of a generic "infeasible" — closing the loop the user
    # otherwise only gets from a manual "Έλεγχος Εφικτότητας".
    if result.status == "infeasible":
        try:
            report = check_feasibility(db).to_dict()
            stats["feasibility_errors"] = report.get("errors", [])
            stats["feasibility_warnings"] = report.get("warnings", [])
        except Exception:  # noqa: BLE001 — diagnostics must never break persistence
            pass

    solution.metadata_json = json.dumps(stats, default=str)

    locked_keys = {
        (la["lesson_id"], la["day_of_week"], la["period_id"], la["classroom_id"])
        for la in (locked_assignments or [])
    }

    if result.status in ("optimal", "feasible"):
        for slot_data in result.slots:
            key = (
                slot_data["lesson_id"], slot_data["day_of_week"],
                slot_data["period_id"], slot_data["classroom_id"],
            )
            db.add(TimetableSlot(
                solution_id=solution.id,
                lesson_id=slot_data["lesson_id"],
                day_of_week=slot_data["day_of_week"],
                period_id=slot_data["period_id"],
                classroom_id=slot_data["classroom_id"],
                is_unplaced=False,
                is_locked=key in locked_keys,
            ))
        # Unplaced rows feed the parking lot (permissive mode only)
        for entry in result.unplaced:
            db.add(TimetableSlot(
                solution_id=solution.id,
                lesson_id=entry["lesson_id"],
                day_of_week=None,
                period_id=None,
                classroom_id=None,
                is_unplaced=True,
                unplaced_reason=entry.get("reason"),
            ))
    db.commit()


def _guard_no_active_solve(db: Session) -> None:
    """Reject a new solve if one is already running. Each CP-SAT run uses
    4 workers and up to 1g; two concurrent solves on a 1g-limited container
    risk an OOM kill. One active solve at a time is plenty for this app."""
    active = (
        db.query(TimetableSolution)
        .filter(TimetableSolution.status == "generating")
        .first()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail="Τρέχει ήδη μια δημιουργία προγράμματος. Περίμενε να ολοκληρωθεί.",
        )


def _run_generation_job(
    solution_id: int,
    max_time_seconds: int,
    mode: str,
    warm_start_assignments: list[dict] | None = None,
    locked_assignments: list[dict] | None = None,
    extra_stats: dict | None = None,
) -> None:
    """Background worker: runs CP-SAT with its OWN session (the request
    session is closed by the time this executes) and persists the result.
    Handles both /generate (warm-start) and /regenerate (locked) flows.
    Any crash marks the solution 'error' so the UI never sees a phantom
    'generating' row."""
    db = SessionLocal()
    try:
        solution = (
            db.query(TimetableSolution)
            .filter(TimetableSolution.id == solution_id)
            .first()
        )
        if not solution:
            return
        solver = TimetableSolver(
            db,
            max_time_seconds=max_time_seconds,
            mode=mode,
            warm_start_assignments=warm_start_assignments or [],
            locked_assignments=locked_assignments or [],
            term_id=solution.term_id,
        )
        result = solver.solve()
        _persist_solver_result(db, solution, result, locked_assignments, extra_stats)
    except Exception as exc:  # noqa: BLE001 — background job must not die silently
        db.rollback()
        solution = (
            db.query(TimetableSolution)
            .filter(TimetableSolution.id == solution_id)
            .first()
        )
        if solution:
            solution.status = "error"
            solution.metadata_json = json.dumps({"message": f"Solver crashed: {exc}"})
            db.commit()
    finally:
        db.close()
