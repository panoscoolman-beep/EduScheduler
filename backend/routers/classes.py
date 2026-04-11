"""
Classes API — CRUD operations for school classes/sections.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import SchoolClass, StudentClassEnrollment
from backend.schemas import SchoolClassCreate, SchoolClassUpdate, SchoolClassResponse

router = APIRouter()


@router.get("/", response_model=list[SchoolClassResponse])
def list_classes(db: Session = Depends(get_db)):
    return db.query(SchoolClass).order_by(SchoolClass.grade_level, SchoolClass.name).all()


@router.get("/{class_id}", response_model=SchoolClassResponse)
def get_class(class_id: int, db: Session = Depends(get_db)):
    school_class = db.query(SchoolClass).filter(SchoolClass.id == class_id).first()
    if not school_class:
        raise HTTPException(status_code=404, detail="Η τάξη δεν βρέθηκε")
    return school_class


@router.post("/", response_model=SchoolClassResponse, status_code=201)
def create_class(data: SchoolClassCreate, db: Session = Depends(get_db)):
    existing = db.query(SchoolClass).filter(SchoolClass.short_name == data.short_name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Υπάρχει ήδη τάξη με συντομογραφία '{data.short_name}'")
    
    # Extract student_ids before dumping
    class_data = data.model_dump(exclude={"student_ids"})
    school_class = SchoolClass(**class_data)
    school_class.student_count = len(data.student_ids)
    db.add(school_class)
    db.flush() # Flush to get school_class.id

    # Create enrollments
    for sid in data.student_ids:
        enroll = StudentClassEnrollment(student_id=sid, class_id=school_class.id)
        db.add(enroll)

    db.commit()
    db.refresh(school_class)
    return school_class


@router.put("/{class_id}", response_model=SchoolClassResponse)
def update_class(class_id: int, data: SchoolClassUpdate, db: Session = Depends(get_db)):
    school_class = db.query(SchoolClass).filter(SchoolClass.id == class_id).first()
    if not school_class:
        raise HTTPException(status_code=404, detail="Η τάξη δεν βρέθηκε")
    
    # Update primitive fields
    class_data = data.model_dump(exclude={"student_ids"})
    for key, value in class_data.items():
        setattr(school_class, key, value)
    
    # Update student_count automatically
    school_class.student_count = len(data.student_ids)

    # Sync enrollments: remove old ones, add new ones
    db.query(StudentClassEnrollment).filter(StudentClassEnrollment.class_id == class_id).delete()
    db.flush()
    for sid in data.student_ids:
        enroll = StudentClassEnrollment(student_id=sid, class_id=school_class.id)
        db.add(enroll)

    db.commit()
    db.refresh(school_class)
    return school_class


@router.delete("/{class_id}", status_code=204)
def delete_class(class_id: int, db: Session = Depends(get_db)):
    school_class = db.query(SchoolClass).filter(SchoolClass.id == class_id).first()
    if not school_class:
        raise HTTPException(status_code=404, detail="Η τάξη δεν βρέθηκε")
    db.delete(school_class)
    db.commit()
