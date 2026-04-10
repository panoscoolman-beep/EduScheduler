"""
Teachers API — CRUD + Availability management.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Teacher, TeacherAvailability
from backend.schemas import (
    TeacherCreate,
    TeacherResponse,
    TeacherAvailabilityResponse,
    TeacherAvailabilityBulkUpdate,
)

router = APIRouter()


@router.get("/", response_model=list[TeacherResponse])
def list_teachers(db: Session = Depends(get_db)):
    return db.query(Teacher).order_by(Teacher.name).all()


@router.get("/{teacher_id}", response_model=TeacherResponse)
def get_teacher(teacher_id: int, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Ο καθηγητής δεν βρέθηκε")
    return teacher


@router.post("/", response_model=TeacherResponse, status_code=201)
def create_teacher(data: TeacherCreate, db: Session = Depends(get_db)):
    existing = db.query(Teacher).filter(Teacher.short_name == data.short_name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Υπάρχει ήδη καθηγητής με συντομογραφία '{data.short_name}'")
    teacher = Teacher(**data.model_dump())
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    return teacher


@router.put("/{teacher_id}", response_model=TeacherResponse)
def update_teacher(teacher_id: int, data: TeacherCreate, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Ο καθηγητής δεν βρέθηκε")
    for key, value in data.model_dump().items():
        setattr(teacher, key, value)
    db.commit()
    db.refresh(teacher)
    return teacher


@router.delete("/{teacher_id}", status_code=204)
def delete_teacher(teacher_id: int, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Ο καθηγητής δεν βρέθηκε")
    db.delete(teacher)
    db.commit()


# ─── Availability ───────────────────────────────────────

@router.get("/{teacher_id}/availability", response_model=list[TeacherAvailabilityResponse])
def get_availability(teacher_id: int, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Ο καθηγητής δεν βρέθηκε")
    return teacher.availabilities


@router.put("/{teacher_id}/availability", response_model=list[TeacherAvailabilityResponse])
def update_availability(teacher_id: int, data: TeacherAvailabilityBulkUpdate, db: Session = Depends(get_db)):
    """Replace entire availability matrix for a teacher."""
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Ο καθηγητής δεν βρέθηκε")

    # Delete existing availability
    db.query(TeacherAvailability).filter(TeacherAvailability.teacher_id == teacher_id).delete()

    # Insert new entries
    new_entries = []
    for avail in data.availabilities:
        entry = TeacherAvailability(teacher_id=teacher_id, **avail.model_dump())
        db.add(entry)
        new_entries.append(entry)

    db.commit()
    for entry in new_entries:
        db.refresh(entry)
    return new_entries
