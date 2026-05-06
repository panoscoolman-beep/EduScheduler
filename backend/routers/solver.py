"""
Solver API — Generate timetables and check status.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import (
    TimetableSolution, TimetableSlot, Lesson,
    TeacherAvailability, StudentAvailability, StudentClassEnrollment
)
from backend.schemas import (
    SolverRequest,
    SolverStatusResponse,
    TimetableSolutionResponse,
    TimetableSlotResponse,
    TimetableSlotUpdate,
)
from backend.solver.engine import TimetableSolver

router = APIRouter()


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

    # Run solver
    solver = TimetableSolver(
        db,
        max_time_seconds=request.max_time_seconds,
        mode=request.mode,
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

    # 3. Classroom Conflict
    target_room = data.classroom_id if data.classroom_id is not None else slot.classroom_id
    if target_room:
        room_conflict = conflict_query.filter(TimetableSlot.classroom_id == target_room).first()
        if room_conflict:
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

    slot.day_of_week = data.day_of_week
    slot.period_id = data.period_id

    if data.classroom_id is not None:
        slot.classroom_id = data.classroom_id

    if data.is_locked is not None:
        slot.is_locked = data.is_locked

    # If we're moving a parking-lot slot onto the grid, flip is_unplaced.
    # Required: classroom_id must be present (otherwise the constraint
    # ck_slot_placement_consistent would be violated).
    if slot.is_unplaced:
        if not slot.classroom_id:
            raise HTTPException(
                status_code=400,
                detail="Πρέπει να ορίσεις αίθουσα όταν τοποθετείς μάθημα από το parking lot.",
            )
        slot.is_unplaced = False
        slot.unplaced_reason = None

    db.commit()
    return {"status": "ok", "message": "Το slot ενημερώθηκε"}
