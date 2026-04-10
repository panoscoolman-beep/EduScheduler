"""
Classrooms API — CRUD operations.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Classroom
from backend.schemas import ClassroomCreate, ClassroomResponse

router = APIRouter()


@router.get("/", response_model=list[ClassroomResponse])
def list_classrooms(db: Session = Depends(get_db)):
    return db.query(Classroom).order_by(Classroom.name).all()


@router.get("/{classroom_id}", response_model=ClassroomResponse)
def get_classroom(classroom_id: int, db: Session = Depends(get_db)):
    classroom = db.query(Classroom).filter(Classroom.id == classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Η αίθουσα δεν βρέθηκε")
    return classroom


@router.post("/", response_model=ClassroomResponse, status_code=201)
def create_classroom(data: ClassroomCreate, db: Session = Depends(get_db)):
    existing = db.query(Classroom).filter(Classroom.short_name == data.short_name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Υπάρχει ήδη αίθουσα με συντομογραφία '{data.short_name}'")
    classroom = Classroom(**data.model_dump())
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return classroom


@router.put("/{classroom_id}", response_model=ClassroomResponse)
def update_classroom(classroom_id: int, data: ClassroomCreate, db: Session = Depends(get_db)):
    classroom = db.query(Classroom).filter(Classroom.id == classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Η αίθουσα δεν βρέθηκε")
    for key, value in data.model_dump().items():
        setattr(classroom, key, value)
    db.commit()
    db.refresh(classroom)
    return classroom


@router.delete("/{classroom_id}", status_code=204)
def delete_classroom(classroom_id: int, db: Session = Depends(get_db)):
    classroom = db.query(Classroom).filter(Classroom.id == classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Η αίθουσα δεν βρέθηκε")
    db.delete(classroom)
    db.commit()
