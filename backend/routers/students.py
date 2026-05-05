from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Student, StudentClassEnrollment
from backend.schemas import (
    StudentCreate, 
    StudentResponse,
    StudentAvailabilityResponse,
    StudentAvailabilityBulkUpdate
)

router = APIRouter()


@router.get("/", response_model=list[StudentResponse])
def get_students(db: Session = Depends(get_db)):
    return db.query(Student).all()


@router.get("/{student_id}", response_model=StudentResponse)
def get_student(student_id: int, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


@router.post("/", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
def create_student(student_in: StudentCreate, db: Session = Depends(get_db)):
    db_student = Student(**student_in.model_dump())
    db.add(db_student)
    db.commit()
    db.refresh(db_student)
    return db_student


@router.put("/{student_id}", response_model=StudentResponse)
def update_student(student_id: int, student_in: StudentCreate, db: Session = Depends(get_db)):
    db_student = db.query(Student).filter(Student.id == student_id).first()
    if not db_student:
        raise HTTPException(status_code=404, detail="Student not found")

    for key, value in student_in.model_dump().items():
        setattr(db_student, key, value)

    db.commit()
    db.refresh(db_student)
    return db_student


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student(student_id: int, db: Session = Depends(get_db)):
    db_student = db.query(Student).filter(Student.id == student_id).first()
    if not db_student:
        raise HTTPException(status_code=404, detail="Student not found")

    db.delete(db_student)
    db.commit()


# ─── Availability ───────────────────────────────────────

@router.get("/{student_id}/availability", response_model=list[StudentAvailabilityResponse])
def get_availability(student_id: int, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student.availabilities


@router.put("/{student_id}/availability", response_model=list[StudentAvailabilityResponse])
def update_availability(student_id: int, data: StudentAvailabilityBulkUpdate, db: Session = Depends(get_db)):
    """Replace entire availability matrix for a student."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    from backend.models import StudentAvailability

    # Delete existing availability
    db.query(StudentAvailability).filter(StudentAvailability.student_id == student_id).delete()

    # Insert new entries
    new_entries = []
    for avail in data.availabilities:
        entry = StudentAvailability(student_id=student_id, **avail.model_dump())
        db.add(entry)
        new_entries.append(entry)

    db.commit()
    for entry in new_entries:
        db.refresh(entry)
    return new_entries
