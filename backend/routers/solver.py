"""
Solver API — Generate timetables and check status.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import (
    TimetableSolution, TimetableSlot, Lesson, Classroom,
    TeacherAvailability, StudentAvailability, StudentClassEnrollment
)
from backend.services import slot_history as slot_history_svc
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
from backend.solver.engine import TimetableSolver

router = APIRouter()


def _pick_default_classroom(
    db: Session,
    lesson: Lesson,
    exclude_room_ids: set[int] | None = None,
) -> int | None:
    """Choose a sensible classroom for a manual placement when the
    drag-drop UI didn't supply one.

    Order of preference:
      1. The lesson's own classroom_id, if set
      2. First room whose type matches the subject's special_room_type
         (lab / gym / computer_lab) when the subject requires one
      3. First "regular" room
      4. First room of any type

    Rooms in `exclude_room_ids` are skipped (used when retrying after a
    classroom conflict).
    """
    excluded = exclude_room_ids or set()

    # 1) Lesson-pinned room
    if lesson.classroom_id and lesson.classroom_id not in excluded:
        return lesson.classroom_id

    rooms = db.query(Classroom).all()

    # 2) Special-room match (lab/gym/etc.)
    if lesson.subject and lesson.subject.requires_special_room:
        special = lesson.subject.special_room_type
        for r in rooms:
            if r.id in excluded:
                continue
            if r.room_type == special:
                return r.id
        return None  # subject demands special room — no fallback

    # 3) Regular room
    for r in rooms:
        if r.id in excluded:
            continue
        if (r.room_type or "regular") == "regular":
            return r.id

    # 4) Any room
    for r in rooms:
        if r.id not in excluded:
            return r.id

    return None


def _busy_room_ids(
    db: Session,
    solution_id: int,
    day_of_week: int,
    period_id: int,
    exclude_slot_id: int,
) -> set[int]:
    """Set of classroom_ids already occupied at this exact (day, period)
    in this solution, excluding the slot being moved."""
    rows = (
        db.query(TimetableSlot.classroom_id)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.day_of_week == day_of_week,
            TimetableSlot.period_id == period_id,
            TimetableSlot.id != exclude_slot_id,
            TimetableSlot.classroom_id.isnot(None),
        )
        .all()
    )
    return {r[0] for r in rows}


@router.get("/feasibility-check", response_model=FeasibilityReportResponse)
def feasibility_check(db: Session = Depends(get_db)):
    """Run a fast pre-solve feasibility analysis without invoking CP-SAT.

    Helps the user catch over-constrained problems (overloaded teachers,
    missing labs, blocks too long for the school day) in milliseconds
    instead of waiting 30+ seconds for the solver to fail.
    """
    return check_feasibility(db).to_dict()


@router.post("/generate", response_model=SolverStatusResponse)
def generate_timetable(request: SolverRequest, db: Session = Depends(get_db)):
    """Run the solver to generate a new timetable."""
    # Create solution record
    solution = TimetableSolution(
        name=request.name,
        status="generating",
        created_at=datetime.utcnow(),
    )
    db.add(solution)
    db.commit()
    db.refresh(solution)

    # Optionally fetch warm-start hints from a prior solution
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

    # Run solver
    solver = TimetableSolver(
        db,
        max_time_seconds=request.max_time_seconds,
        mode=request.mode,
        warm_start_assignments=warm_start_assignments,
    )
    result = solver.solve()

    # Update solution record
    solution.status = result.status
    solution.score = result.score
    solution.metadata_json = json.dumps(result.stats, default=str)

    if result.status in ("optimal", "feasible"):
        # Save placed slots
        for slot_data in result.slots:
            slot = TimetableSlot(
                solution_id=solution.id,
                lesson_id=slot_data["lesson_id"],
                day_of_week=slot_data["day_of_week"],
                period_id=slot_data["period_id"],
                classroom_id=slot_data["classroom_id"],
                is_unplaced=False,
            )
            db.add(slot)

        # Save unplaced rows for the parking lot (permissive mode only)
        for entry in result.unplaced:
            slot = TimetableSlot(
                solution_id=solution.id,
                lesson_id=entry["lesson_id"],
                day_of_week=None,
                period_id=None,
                classroom_id=None,
                is_unplaced=True,
                unplaced_reason=entry.get("reason"),
            )
            db.add(slot)

    db.commit()
    db.refresh(solution)

    return SolverStatusResponse(
        solution_id=solution.id,
        status=result.status,
        message=result.message,
        score=result.score,
        placed_count=len(result.slots),
        unplaced_count=len(result.unplaced),
    )


@router.post("/regenerate/{source_solution_id}", response_model=SolverStatusResponse)
def regenerate_with_locks(
    source_solution_id: int,
    request: SolverRequest,
    db: Session = Depends(get_db),
):
    """Run the solver again, keeping every is_locked=TRUE slot from a
    source solution as hard fixed points. The unlocked slots are
    redistributed.

    The result is a NEW solution (we don't mutate the source) so
    history is preserved and the user can compare the two.
    """
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

    # Create the new solution record
    solution = TimetableSolution(
        name=request.name or f"{source.name} (regenerated)",
        status="generating",
        created_at=datetime.utcnow(),
    )
    db.add(solution)
    db.commit()
    db.refresh(solution)

    solver = TimetableSolver(
        db,
        max_time_seconds=request.max_time_seconds,
        mode=request.mode,
        locked_assignments=locked_assignments,
    )
    result = solver.solve()

    solution.status = result.status
    solution.score = result.score
    stats = dict(result.stats)
    stats["locked_from_solution"] = source_solution_id
    stats["locked_count"] = len(locked_assignments)
    solution.metadata_json = json.dumps(stats, default=str)

    if result.status in ("optimal", "feasible"):
        # Determine which placed slots correspond to the original locks
        # so we can preserve their is_locked flag in the new solution.
        locked_keys = {
            (la["lesson_id"], la["day_of_week"], la["period_id"], la["classroom_id"])
            for la in locked_assignments
        }
        for slot_data in result.slots:
            key = (
                slot_data["lesson_id"],
                slot_data["day_of_week"],
                slot_data["period_id"],
                slot_data["classroom_id"],
            )
            slot = TimetableSlot(
                solution_id=solution.id,
                lesson_id=slot_data["lesson_id"],
                day_of_week=slot_data["day_of_week"],
                period_id=slot_data["period_id"],
                classroom_id=slot_data["classroom_id"],
                is_unplaced=False,
                is_locked=key in locked_keys,
            )
            db.add(slot)

        for entry in result.unplaced:
            slot = TimetableSlot(
                solution_id=solution.id,
                lesson_id=entry["lesson_id"],
                day_of_week=None,
                period_id=None,
                classroom_id=None,
                is_unplaced=True,
                unplaced_reason=entry.get("reason"),
            )
            db.add(slot)

    db.commit()
    db.refresh(solution)

    return SolverStatusResponse(
        solution_id=solution.id,
        status=result.status,
        message=result.message,
        score=result.score,
        placed_count=len(result.slots),
        unplaced_count=len(result.unplaced),
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
            created_at=s.created_at.isoformat() if s.created_at else None,
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
            subject_name=lesson.subject.name if lesson.subject else None,
            subject_short=lesson.subject.short_name if lesson.subject else None,
            subject_color=lesson.subject.color if lesson.subject else None,
            teacher_name=lesson.teacher.name if lesson.teacher else None,
            teacher_short=lesson.teacher.short_name if lesson.teacher else None,
            teacher_color=lesson.teacher.color if lesson.teacher else None,
            class_name=lesson.school_class.name if lesson.school_class else None,
            class_short=lesson.school_class.short_name if lesson.school_class else None,
            classroom_name=slot.classroom.name if slot.classroom else None,
        ))

    return TimetableSolutionResponse(
        id=solution.id,
        name=solution.name,
        created_at=solution.created_at.isoformat() if solution.created_at else None,
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

    # Resolve a target classroom up front. Parking-lot slots have
    # classroom_id=NULL; if the caller didn't provide one in the body
    # (the drag-drop UI doesn't ask the user), fall back to the
    # lesson's preferred classroom_id, then to the first room of the
    # lesson's required type, then to any room. This avoids the dead
    # end where a parking-lot drop always 400s.
    if data.classroom_id is not None:
        target_room = data.classroom_id
    elif slot.classroom_id is not None:
        target_room = slot.classroom_id
    else:
        target_room = _pick_default_classroom(db, slot.lesson)

    if target_room is None:
        raise HTTPException(
            status_code=400,
            detail="Δεν υπάρχει διαθέσιμη αίθουσα για αυτό το μάθημα.",
        )

    # Conflict Validations
    conflict_query = (
        db.query(TimetableSlot)
        .join(Lesson)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.day_of_week == data.day_of_week,
            TimetableSlot.period_id == data.period_id,
            TimetableSlot.id != slot_id
        )
    )

    # 1. Teacher Conflict
    if slot.lesson.teacher_id:
        teacher_conflict = conflict_query.filter(Lesson.teacher_id == slot.lesson.teacher_id).first()
        if teacher_conflict:
            raise HTTPException(status_code=400, detail="Ο καθηγητής διδάσκει ήδη σε άλλη τάξη αυτή τη μέρα/ώρα.")

    # 2. Class Conflict
    if slot.lesson.class_id:
        class_conflict = conflict_query.filter(Lesson.class_id == slot.lesson.class_id).first()
        if class_conflict:
            raise HTTPException(status_code=400, detail="Η συγκεκριμένη τάξη κάνει ήδη άλλο μάθημα αυτή τη μέρα/ώρα.")

    # 3. Classroom Conflict — try to fall back to another room if the
    # auto-picked one is busy
    room_conflict = (
        conflict_query.filter(TimetableSlot.classroom_id == target_room).first()
    )
    if room_conflict and data.classroom_id is None and slot.classroom_id is None:
        # Auto-picked room is taken — try every other compatible room
        target_room = _pick_default_classroom(
            db, slot.lesson,
            exclude_room_ids=_busy_room_ids(db, solution_id, data.day_of_week, data.period_id, slot_id),
        )
        if target_room is None:
            raise HTTPException(
                status_code=400,
                detail="Όλες οι αίθουσες είναι κατειλημμένες αυτή τη μέρα/ώρα.",
            )
    elif room_conflict:
        raise HTTPException(status_code=400, detail="Η αίθουσα είναι κατειλημμένη αυτή τη μέρα/ώρα.")

    # 4. Teacher Availability constraints
    if slot.lesson.teacher_id:
        teacher_unav = (
            db.query(TeacherAvailability)
            .filter(
                TeacherAvailability.teacher_id == slot.lesson.teacher_id,
                TeacherAvailability.day_of_week == data.day_of_week,
                TeacherAvailability.period_id == data.period_id,
                TeacherAvailability.status == "unavailable"
            )
            .first()
        )
        if teacher_unav:
            raise HTTPException(status_code=400, detail="Ο καθηγητής έχει δηλώσει κώλυμα (Μη Διαθέσιμος) αυτή τη μέρα και ώρα.")

    # 5. Student Availability constraints
    if slot.lesson.class_id:
        # Get all students in this class
        enrolled_student_ids = [
            e.student_id for e in db.query(StudentClassEnrollment.student_id)
            .filter(StudentClassEnrollment.class_id == slot.lesson.class_id)
            .all()
        ]
        if enrolled_student_ids:
            student_unav = (
                db.query(StudentAvailability)
                .filter(
                    StudentAvailability.student_id.in_(enrolled_student_ids),
                    StudentAvailability.day_of_week == data.day_of_week,
                    StudentAvailability.period_id == data.period_id,
                    StudentAvailability.status == "unavailable"
                )
                .first()
            )
            if student_unav:
                raise HTTPException(status_code=400, detail="Ένας ή περισσότεροι μαθητές του τμήματος έχουν δηλώσει κώλυμα αυτή τη μέρα και ώρα.")

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
