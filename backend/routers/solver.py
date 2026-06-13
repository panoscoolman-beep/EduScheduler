"""
Solver API — Generate timetables and check status.
"""

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import (
    TimetableSolution, TimetableSlot, Lesson, Classroom,
    TeacherAvailability, StudentAvailability, StudentClassEnrollment,
    utcnow_naive,
)
from backend.services import slot_history as slot_history_svc
from backend.services.slot_placement import resolve_and_validate_target_room
from backend.services.solver_jobs import (
    _guard_no_active_solve,
    _iso_utc,
    _run_generation_job,
)
from backend.services.substitute_finder import find_substitutes
from backend.schemas import (
    FeasibilityReportResponse,
    SolverRequest,
    SolverStatusResponse,
    TimetableSolutionResponse,
    TimetableSlotResponse,
    TimetableSlotUpdate,
)
from backend.services.feasibility import check_feasibility

router = APIRouter()


# Classroom resolution + manual-move conflict checks now live in
# backend/services/slot_placement.py (extracted for readability).


@router.get("/feasibility-check", response_model=FeasibilityReportResponse)
def feasibility_check(db: Session = Depends(get_db)):
    """Run a fast pre-solve feasibility analysis without invoking CP-SAT.

    Helps the user catch over-constrained problems (overloaded teachers,
    missing labs, blocks too long for the school day) in milliseconds
    instead of waiting 30+ seconds for the solver to fail.
    """
    return check_feasibility(db).to_dict()


@router.post("/generate", response_model=SolverStatusResponse)
def generate_timetable(
    request: SolverRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Kick off timetable generation in the background.

    Returns immediately with status='generating'; the UI polls
    GET /solver/status/{solution_id} until it flips. This keeps 10-minute
    solver runs out of HTTP request handlers (no held worker, no timeout).
    """
    _guard_no_active_solve(db)

    # Validate the warm-start source BEFORE creating the solution row —
    # the old order leaked an orphan 'generating' record on 404.
    warm_start_assignments: list[dict] = []
    if request.warm_start_from_solution_id:
        source = (
            db.query(TimetableSolution)
            .filter(TimetableSolution.id == request.warm_start_from_solution_id)
            .first()
        )
        if not source:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Δεν βρέθηκε λύση id={request.warm_start_from_solution_id} "
                    "για warm start"
                ),
            )
        prior_slots = (
            db.query(TimetableSlot)
            .filter(
                TimetableSlot.solution_id == source.id,
                TimetableSlot.is_unplaced == False,  # noqa: E712
            )
            .all()
        )
        warm_start_assignments = [
            {
                "lesson_id": s.lesson_id,
                "day_of_week": s.day_of_week,
                "period_id": s.period_id,
                "classroom_id": s.classroom_id,
            }
            for s in prior_slots
        ]

    solution = TimetableSolution(
        name=request.name,
        status="generating",
        created_at=utcnow_naive(),
    )
    db.add(solution)
    db.commit()
    db.refresh(solution)

    background_tasks.add_task(
        _run_generation_job,
        solution.id,
        request.max_time_seconds,
        request.mode,
        warm_start_assignments,
    )

    return SolverStatusResponse(
        solution_id=solution.id,
        status="generating",
        message="Η δημιουργία ξεκίνησε — ο solver τρέχει στο παρασκήνιο.",
        score=None,
        placed_count=0,
        unplaced_count=0,
    )


@router.get("/status/{solution_id}", response_model=SolverStatusResponse)
def solver_status(solution_id: int, db: Session = Depends(get_db)):
    """Polling endpoint for a generation kicked off by POST /generate."""
    solution = (
        db.query(TimetableSolution)
        .filter(TimetableSolution.id == solution_id)
        .first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")

    placed = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == solution_id,
                TimetableSlot.is_unplaced == False)  # noqa: E712
        .count()
    )
    unplaced = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == solution_id,
                TimetableSlot.is_unplaced == True)  # noqa: E712
        .count()
    )

    if solution.status == "generating":
        message = "Ο solver τρέχει..."
    elif solution.status in ("optimal", "feasible"):
        message = f"Ολοκληρώθηκε ({solution.status}) — {placed} μαθήματα τοποθετήθηκαν."
        if unplaced:
            message += f" {unplaced} στο parking lot."
    else:
        meta = {}
        try:
            meta = json.loads(solution.metadata_json or "{}")
        except ValueError:
            pass
        message = meta.get("message", f"Κατάσταση: {solution.status}")
        # Surface concrete infeasibility reasons when we have them.
        reasons = meta.get("feasibility_errors") or []
        if solution.status == "infeasible" and reasons:
            message = "Αδύνατο πρόγραμμα. Αιτίες:\n• " + "\n• ".join(reasons[:6])

    return SolverStatusResponse(
        solution_id=solution.id,
        status=solution.status,
        message=message,
        score=solution.score,
        placed_count=placed,
        unplaced_count=unplaced,
    )


@router.post("/regenerate/{source_solution_id}", response_model=SolverStatusResponse)
def regenerate_with_locks(
    source_solution_id: int,
    request: SolverRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Run the solver again, keeping every is_locked=TRUE slot from a
    source solution as hard fixed points. The unlocked slots are
    redistributed.

    The result is a NEW solution (we don't mutate the source) so
    history is preserved and the user can compare the two.
    """
    _guard_no_active_solve(db)

    source = db.query(TimetableSolution).filter(
        TimetableSolution.id == source_solution_id
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Η λύση πηγή δεν βρέθηκε")

    locked_slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.solution_id == source_solution_id,
            TimetableSlot.is_locked == True,  # noqa: E712
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .all()
    )

    if not locked_slots:
        raise HTTPException(
            status_code=400,
            detail=(
                "Δεν έχει κλειδωθεί κανένα μάθημα. Πάτησε το 🔒 σε "
                "όσα θες να διατηρήσεις και ξανατρέξε."
            ),
        )

    locked_assignments = [
        {
            "lesson_id": s.lesson_id,
            "day_of_week": s.day_of_week,
            "period_id": s.period_id,
            "classroom_id": s.classroom_id,
        }
        for s in locked_slots
    ]

    # Create the new solution record and run the solver in the background
    # (same pattern as /generate) so Lock & Regenerate no longer holds an
    # HTTP worker for the full solve and survives a mid-run deploy. The UI
    # polls GET /solver/status/{id}.
    solution = TimetableSolution(
        name=request.name or f"{source.name} (regenerated)",
        status="generating",
        created_at=utcnow_naive(),
    )
    db.add(solution)
    db.commit()
    db.refresh(solution)

    background_tasks.add_task(
        _run_generation_job,
        solution.id,
        request.max_time_seconds,
        request.mode,
        None,  # no warm-start
        locked_assignments,
        {"locked_from_solution": source_solution_id,
         "locked_count": len(locked_assignments)},
    )

    return SolverStatusResponse(
        solution_id=solution.id,
        status="generating",
        message="Η αναδημιουργία ξεκίνησε — ο solver τρέχει στο παρασκήνιο.",
        score=None,
        placed_count=0,
        unplaced_count=0,
    )


@router.get("/solutions", response_model=list[TimetableSolutionResponse])
def list_solutions(db: Session = Depends(get_db)):
    """List all generated timetable solutions."""
    solutions = (
        db.query(TimetableSolution)
        .order_by(TimetableSolution.created_at.desc())
        .all()
    )
    return [
        TimetableSolutionResponse(
            id=s.id,
            name=s.name,
            created_at=_iso_utc(s.created_at),
            status=s.status,
            score=s.score,
        )
        for s in solutions
    ]


@router.get("/solutions/{solution_id}", response_model=TimetableSolutionResponse)
def get_solution(solution_id: int, db: Session = Depends(get_db)):
    """Get a specific timetable solution with all its slots."""
    solution = db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")

    # Load slots with related data
    slots = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == solution_id)
        .options(
            joinedload(TimetableSlot.lesson).joinedload(Lesson.subject),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.teacher),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.school_class),
            joinedload(TimetableSlot.classroom),
        )
        .all()
    )

    enriched_slots = []
    for slot in slots:
        lesson = slot.lesson
        enriched_slots.append(TimetableSlotResponse(
            id=slot.id,
            lesson_id=slot.lesson_id,
            day_of_week=slot.day_of_week,
            period_id=slot.period_id,
            classroom_id=slot.classroom_id,
            is_locked=slot.is_locked,
            is_unplaced=slot.is_unplaced,
            unplaced_reason=slot.unplaced_reason,
            subject_id=lesson.subject_id,
            subject_name=lesson.subject.name if lesson.subject else None,
            subject_short=lesson.subject.short_name if lesson.subject else None,
            subject_color=lesson.subject.color if lesson.subject else None,
            teacher_id=lesson.teacher_id,
            teacher_name=lesson.teacher.name if lesson.teacher else None,
            teacher_short=lesson.teacher.short_name if lesson.teacher else None,
            teacher_color=lesson.teacher.color if lesson.teacher else None,
            class_id=lesson.class_id,
            class_name=lesson.school_class.name if lesson.school_class else None,
            class_short=lesson.school_class.short_name if lesson.school_class else None,
            classroom_name=slot.classroom.name if slot.classroom else None,
        ))

    return TimetableSolutionResponse(
        id=solution.id,
        name=solution.name,
        created_at=_iso_utc(solution.created_at),
        status=solution.status,
        score=solution.score,
        slots=enriched_slots,
    )


@router.get("/compare")
def compare_solutions(ids: str, db: Session = Depends(get_db)):
    """Side-by-side comparison of 2+ solutions.

    Query: GET /api/solver/compare?ids=1,2,3
    Returns: {metrics: [...], winners: {metric_name: solution_id}}
    Lower is better for everything except placed_count.
    """
    from backend.services.solution_metrics import compare as svc_compare

    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, detail="ids must be a comma-separated list of integers")
    if len(id_list) < 1:
        raise HTTPException(400, detail="At least one solution_id is required")

    return svc_compare(id_list, db)


@router.delete("/solutions/{solution_id}", status_code=204)
def delete_solution(solution_id: int, db: Session = Depends(get_db)):
    """Delete a timetable solution."""
    solution = db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")
    db.delete(solution)
    db.commit()


@router.put("/solutions/{solution_id}/slots/{slot_id}", response_model=dict)
def update_solution_slot(
    solution_id: int,
    slot_id: int,
    data: TimetableSlotUpdate,
    db: Session = Depends(get_db),
):
    """Manually update a single slot (Drag and Drop override)."""
    slot = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.id == slot_id,
            TimetableSlot.solution_id == solution_id
        )
        .first()
    )
    if not slot:
        raise HTTPException(status_code=404, detail="Το slot δεν βρέθηκε")

    target_room = resolve_and_validate_target_room(db, slot, data)

    prev_state = {
        "day_of_week": slot.day_of_week,
        "period_id": slot.period_id,
        "classroom_id": slot.classroom_id,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": bool(slot.is_unplaced),
    }

    slot.day_of_week = data.day_of_week
    slot.period_id = data.period_id
    slot.classroom_id = target_room

    if data.is_locked is not None:
        slot.is_locked = data.is_locked

    if slot.is_unplaced:
        slot.is_unplaced = False
        slot.unplaced_reason = None

    new_state = {
        "day_of_week": slot.day_of_week,
        "period_id": slot.period_id,
        "classroom_id": slot.classroom_id,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": bool(slot.is_unplaced),
    }
    operation = "lock" if (
        prev_state["is_locked"] != new_state["is_locked"]
        and prev_state["day_of_week"] == new_state["day_of_week"]
        and prev_state["period_id"] == new_state["period_id"]
    ) else "move"
    slot_history_svc.record_edit(db, slot, prev_state, new_state, operation)
    db.commit()
    return {"status": "ok", "message": "Το slot ενημερώθηκε"}


@router.post("/solutions/{solution_id}/undo")
def undo_last_edit(solution_id: int, db: Session = Depends(get_db)):
    """Roll back the most recent manual edit to this solution."""
    solution = (
        db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")

    entry = slot_history_svc.undo(db, solution_id)
    if not entry:
        raise HTTPException(
            status_code=400, detail="Δεν υπάρχει αλλαγή προς αναίρεση"
        )
    db.commit()
    summary = slot_history_svc.history_summary(db, solution_id)
    return {
        "status": "ok",
        "message": "Η αλλαγή αναιρέθηκε",
        "slot_id": entry.slot_id,
        "history": summary,
    }


@router.post("/solutions/{solution_id}/redo")
def redo_last_undo(solution_id: int, db: Session = Depends(get_db)):
    """Re-apply the most recent undone edit."""
    solution = (
        db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")

    entry = slot_history_svc.redo(db, solution_id)
    if not entry:
        raise HTTPException(
            status_code=400, detail="Δεν υπάρχει αλλαγή προς επανάληψη"
        )
    db.commit()
    summary = slot_history_svc.history_summary(db, solution_id)
    return {
        "status": "ok",
        "message": "Η αλλαγή επαναλήφθηκε",
        "slot_id": entry.slot_id,
        "history": summary,
    }


@router.get("/solutions/{solution_id}/history-summary")
def get_history_summary(solution_id: int, db: Session = Depends(get_db)):
    """Return how many undo / redo steps are currently available."""
    solution = (
        db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")
    return slot_history_svc.history_summary(db, solution_id)


@router.get("/solutions/{solution_id}/substitute-suggestions")
def substitute_suggestions(
    solution_id: int,
    teacher_id: int,
    day_of_week: int,
    db: Session = Depends(get_db),
):
    """Find substitute teachers + reschedule slots for an absent teacher.

    Read-only — does not modify the solution. The user reviews the
    suggestions and applies any change manually through the existing
    drag-drop UI.
    """
    solution = (
        db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")
    if day_of_week < 0 or day_of_week > 6:
        raise HTTPException(
            status_code=400, detail="day_of_week πρέπει να είναι 0-6"
        )
    try:
        return find_substitutes(db, solution_id, teacher_id, day_of_week)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
