"""
Subjects API — CRUD operations.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Subject
from backend.schemas import SubjectCreate, SubjectResponse

router = APIRouter()


@router.get("/", response_model=list[SubjectResponse])
def list_subjects(db: Session = Depends(get_db)):
    return db.query(Subject).order_by(Subject.name).all()


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(subject_id: int, db: Session = Depends(get_db)):
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Το μάθημα δεν βρέθηκε")
    return subject


@router.post("/", response_model=SubjectResponse, status_code=201)
def create_subject(data: SubjectCreate, db: Session = Depends(get_db)):
    existing = db.query(Subject).filter(Subject.short_name == data.short_name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Υπάρχει ήδη μάθημα με συντομογραφία '{data.short_name}'")
    subject = Subject(**data.model_dump())
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


@router.put("/{subject_id}", response_model=SubjectResponse)
def update_subject(subject_id: int, data: SubjectCreate, db: Session = Depends(get_db)):
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Το μάθημα δεν βρέθηκε")
    for key, value in data.model_dump().items():
        setattr(subject, key, value)
    db.commit()
    db.refresh(subject)
    return subject


@router.delete("/{subject_id}", status_code=204)
def delete_subject(subject_id: int, db: Session = Depends(get_db)):
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Το μάθημα δεν βρέθηκε")
    db.delete(subject)
    db.commit()
