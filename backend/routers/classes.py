"""
Classes API — CRUD operations for school classes/sections + enrollments.

Η σύνθεση ενός τμήματος (ποιοι μαθητές) αλλάζει με δύο τρόπους:
  - ολόκληρη λίστα στο PUT (`student_ids`) — μόνο οι διαφορές γράφονται,
    ώστε οι μαθητές που μένουν να κρατούν το `enrolled_at` τους·
  - μεμονωμένα POST/DELETE `/{class_id}/students/{student_id}` (idempotent),
    για τον επιλογέα μαθητών και την καρτέλα Μαθητή.
Το `student_count` υπολογίζεται ΠΑΝΤΑ από τις εγγραφές — δεν το εμπιστευόμαστε
από το body.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import SchoolClass, Student, StudentClassEnrollment
from backend.schemas import (
    SchoolClassCreate,
    SchoolClassResponse,
    SchoolClassUpdate,
    StudentResponse,
)

router = APIRouter()


def _get_class_or_404(db: Session, class_id: int) -> SchoolClass:
    school_class = db.query(SchoolClass).filter(SchoolClass.id == class_id).first()
    if not school_class:
        raise HTTPException(status_code=404, detail="Η τάξη δεν βρέθηκε")
    return school_class


def _get_student_or_404(db: Session, student_id: int) -> Student:
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Ο μαθητής δεν βρέθηκε")
    return student


def _require_students_exist(db: Session, student_ids: list[int]) -> list[int]:
    """Dedup + έλεγχος ύπαρξης. Άγνωστο id → 400 (πριν: IntegrityError/500)."""
    wanted = list(dict.fromkeys(int(s) for s in student_ids))
    if not wanted:
        return []
    found = {sid for (sid,) in db.query(Student.id).filter(Student.id.in_(wanted)).all()}
    missing = [sid for sid in wanted if sid not in found]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Άγνωστοι μαθητές: {', '.join(str(m) for m in missing)}",
        )
    return wanted


def sync_student_count(school_class: SchoolClass) -> None:
    """Το student_count είναι παράγωγο των εγγραφών — ποτέ input."""
    school_class.student_count = len(school_class.enrollments)


def set_enrollments(db: Session, school_class: SchoolClass, student_ids: list[int]) -> None:
    """Φέρε τις εγγραφές του τμήματος στη λίστα `student_ids` γράφοντας
    μόνο τις διαφορές (κρατά enrolled_at όσων μένουν)."""
    wanted = set(_require_students_exist(db, student_ids))
    current = {e.student_id: e for e in school_class.enrollments}
    for sid, enrollment in current.items():
        if sid not in wanted:
            db.delete(enrollment)
    for sid in wanted - current.keys():
        db.add(StudentClassEnrollment(student_id=sid, class_id=school_class.id))
    db.flush()
    db.refresh(school_class)
    sync_student_count(school_class)


@router.get("/", response_model=list[SchoolClassResponse])
def list_classes(db: Session = Depends(get_db)):
    return db.query(SchoolClass).order_by(SchoolClass.grade_level, SchoolClass.name).all()


@router.get("/{class_id}", response_model=SchoolClassResponse)
def get_class(class_id: int, db: Session = Depends(get_db)):
    return _get_class_or_404(db, class_id)


@router.get("/{class_id}/students", response_model=list[StudentResponse])
def list_class_students(class_id: int, db: Session = Depends(get_db)):
    """Οι μαθητές του τμήματος, ταξινομημένοι κατά επώνυμο/όνομα."""
    school_class = _get_class_or_404(db, class_id)
    ids = [e.student_id for e in school_class.enrollments]
    if not ids:
        return []
    return (
        db.query(Student)
        .filter(Student.id.in_(ids))
        .order_by(Student.last_name, Student.first_name)
        .all()
    )


@router.post("/", response_model=SchoolClassResponse, status_code=201)
def create_class(data: SchoolClassCreate, db: Session = Depends(get_db)):
    existing = db.query(SchoolClass).filter(SchoolClass.short_name == data.short_name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Υπάρχει ήδη τάξη με συντομογραφία '{data.short_name}'")

    # Έλεγχος μαθητών ΠΡΙΝ γραφτεί οτιδήποτε — άγνωστο id = 400, καθαρό DB.
    student_ids = _require_students_exist(db, data.student_ids)
    class_data = data.model_dump(exclude={"student_ids", "student_count"})
    school_class = SchoolClass(**class_data)
    db.add(school_class)
    db.flush()  # για το school_class.id

    set_enrollments(db, school_class, student_ids)
    db.commit()
    db.refresh(school_class)
    return school_class


@router.put("/{class_id}", response_model=SchoolClassResponse)
def update_class(class_id: int, data: SchoolClassUpdate, db: Session = Depends(get_db)):
    school_class = _get_class_or_404(db, class_id)

    class_data = data.model_dump(exclude={"student_ids", "student_count"})
    for key, value in class_data.items():
        setattr(school_class, key, value)

    # `student_ids` απόν (None) = μην αγγίξεις τις εγγραφές. Πριν, το default
    # [] άδειαζε σιωπηλά το τμήμα σε κάθε PUT που το παρέλειπε.
    if data.student_ids is not None:
        set_enrollments(db, school_class, data.student_ids)
    else:
        sync_student_count(school_class)

    db.commit()
    db.refresh(school_class)
    return school_class


@router.post("/{class_id}/students/{student_id}", response_model=SchoolClassResponse)
def enroll_student(class_id: int, student_id: int, db: Session = Depends(get_db)):
    """Πρόσθεσε έναν μαθητή στο τμήμα (idempotent — ήδη μέσα = καμία αλλαγή)."""
    school_class = _get_class_or_404(db, class_id)
    _get_student_or_404(db, student_id)
    if student_id not in {e.student_id for e in school_class.enrollments}:
        db.add(StudentClassEnrollment(student_id=student_id, class_id=class_id))
        db.flush()
        db.refresh(school_class)
    sync_student_count(school_class)
    db.commit()
    db.refresh(school_class)
    return school_class


@router.delete("/{class_id}/students/{student_id}", response_model=SchoolClassResponse)
def unenroll_student(class_id: int, student_id: int, db: Session = Depends(get_db)):
    """Αφαίρεσε έναν μαθητή από το τμήμα (idempotent — δεν ήταν μέσα = 200)."""
    school_class = _get_class_or_404(db, class_id)
    _get_student_or_404(db, student_id)
    for enrollment in list(school_class.enrollments):
        if enrollment.student_id == student_id:
            db.delete(enrollment)
    db.flush()
    db.refresh(school_class)
    sync_student_count(school_class)
    db.commit()
    db.refresh(school_class)
    return school_class


@router.delete("/{class_id}", status_code=204)
def delete_class(class_id: int, db: Session = Depends(get_db)):
    school_class = _get_class_or_404(db, class_id)
    db.delete(school_class)
    db.commit()
