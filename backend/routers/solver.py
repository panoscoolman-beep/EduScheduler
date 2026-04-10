"""
Solver API — Generate timetables and check status.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import TimetableSolution, TimetableSlot, Lesson
from backend.schemas import (
    SolverRequest,
    SolverStatusResponse,
    TimetableSolutionResponse,
    TimetableSlotResponse,
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
    solver = TimetableSolver(db, max_time_seconds=request.max_time_seconds)
    result = solver.solve()

    # Update solution record
    solution.status = result.status
    solution.score = result.score
    solution.metadata_json = json.dumps(result.stats, default=str)

    if result.status in ("optimal", "feasible"):
        # Save slots
        for slot_data in result.slots:
            slot = TimetableSlot(
                solution_id=solution.id,
                lesson_id=slot_data["lesson_id"],
                day_of_week=slot_data["day_of_week"],
                period_id=slot_data["period_id"],
                classroom_id=slot_data["classroom_id"],
            )
            db.add(slot)

    db.commit()
    db.refresh(solution)

    return SolverStatusResponse(
        solution_id=solution.id,
        status=result.status,
        message=result.message,
        score=result.score,
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
            subject_name=lesson.subject.name if lesson.subject else None,
            subject_short=lesson.subject.short_name if lesson.subject else None,
            subject_color=lesson.subject.color if lesson.subject else None,
            teacher_name=lesson.teacher.name if lesson.teacher else None,
            teacher_short=lesson.teacher.short_name if lesson.teacher else None,
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
