"""
Classrooms API — CRUD operations.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services import archive as archive_svc
from backend.services import delete_guards as guards
from backend.models import Classroom
from backend.schemas import ClassroomCreate, ClassroomResponse

router = APIRouter()


@router.get("/", response_model=list[ClassroomResponse])
def list_classrooms(include_archived: bool = False, db: Session = Depends(get_db)):
    """Τα αρχειοθετημένα μένουν έξω εκτός αν ζητηθούν (επαναφορά)."""
    query = db.query(Classroom)
    if not include_archived:
        query = query.filter(Classroom.archived_at.is_(None))
    return query.order_by(Classroom.name).all()


@router.post("/{classroom_id}/archive")
def archive_classroom(classroom_id: int, db: Session = Depends(get_db)):
    """📦 Κρύψε τον/την από τις λίστες χωρίς να σβηστεί τίποτα (409 αν
    χρησιμοποιείται στο ενεργό σενάριο)."""
    return archive_svc.set_archived(db, "classroom", classroom_id, True)


@router.post("/{classroom_id}/unarchive")
def unarchive_classroom(classroom_id: int, db: Session = Depends(get_db)):
    return archive_svc.set_archived(db, "classroom", classroom_id, False)


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
def delete_classroom(classroom_id: int, force: bool = False, db: Session = Depends(get_db)):
    """Οι ώρες που είναι τοποθετημένες εδώ θα έμεναν «τοποθετημένες χωρίς
    αίθουσα». Χωρίς `?force=true` → 409 + πλήθη· με force → γυρίζουν στην
    Παλέτα πριν σβηστεί η αίθουσα (δεν χάνεται ώρα)."""
    classroom = db.query(Classroom).filter(Classroom.id == classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Η αίθουσα δεν βρέθηκε")
    guards.guard_classroom(guards.classroom_usage(db, classroom_id), force=force,
                           name=classroom.name)
    guards.unplace_room_slots(db, classroom_id, classroom.name)
    db.delete(classroom)
    db.commit()
