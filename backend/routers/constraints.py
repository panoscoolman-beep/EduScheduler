"""
Constraints API — CRUD for scheduling constraints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Constraint
from backend.schemas import ConstraintCreate, ConstraintResponse

router = APIRouter()


@router.get("/", response_model=list[ConstraintResponse])
def list_constraints(db: Session = Depends(get_db)):
    return db.query(Constraint).order_by(Constraint.constraint_type, Constraint.name).all()


@router.get("/{constraint_id}", response_model=ConstraintResponse)
def get_constraint(constraint_id: int, db: Session = Depends(get_db)):
    constraint = db.query(Constraint).filter(Constraint.id == constraint_id).first()
    if not constraint:
        raise HTTPException(status_code=404, detail="Ο περιορισμός δεν βρέθηκε")
    return constraint


@router.post("/", response_model=ConstraintResponse, status_code=201)
def create_constraint(data: ConstraintCreate, db: Session = Depends(get_db)):
    constraint = Constraint(**data.model_dump())
    db.add(constraint)
    db.commit()
    db.refresh(constraint)
    return constraint


@router.put("/{constraint_id}", response_model=ConstraintResponse)
def update_constraint(constraint_id: int, data: ConstraintCreate, db: Session = Depends(get_db)):
    constraint = db.query(Constraint).filter(Constraint.id == constraint_id).first()
    if not constraint:
        raise HTTPException(status_code=404, detail="Ο περιορισμός δεν βρέθηκε")
    for key, value in data.model_dump().items():
        setattr(constraint, key, value)
    db.commit()
    db.refresh(constraint)
    return constraint


@router.delete("/{constraint_id}", status_code=204)
def delete_constraint(constraint_id: int, db: Session = Depends(get_db)):
    constraint = db.query(Constraint).filter(Constraint.id == constraint_id).first()
    if not constraint:
        raise HTTPException(status_code=404, detail="Ο περιορισμός δεν βρέθηκε")
    db.delete(constraint)
    db.commit()


@router.post("/seed-defaults", response_model=list[ConstraintResponse], status_code=201)
def seed_default_constraints(db: Session = Depends(get_db)):
    """Create default hard and soft constraints."""
    existing = db.query(Constraint).count()
    if existing > 0:
        raise HTTPException(status_code=409, detail="Υπάρχουν ήδη περιορισμοί")

    defaults = [
        # Hard constraints
        ("Χωρίς σύγκρουση καθηγητή", "hard", "teacher",
         '{"type": "no_teacher_clash"}', 100),
        ("Χωρίς σύγκρουση τάξης", "hard", "class",
         '{"type": "no_class_clash"}', 100),
        ("Χωρίς σύγκρουση αίθουσας", "hard", "room",
         '{"type": "no_room_clash"}', 100),
        ("Τήρηση ωρών/εβδομάδα", "hard", "general",
         '{"type": "curriculum_fulfillment"}', 100),
        ("Διαθεσιμότητα καθηγητή", "hard", "teacher",
         '{"type": "teacher_availability"}', 100),

        # Soft constraints
        ("Ελαχιστοποίηση κενών καθηγητών", "soft", "teacher",
         '{"type": "min_teacher_gaps"}', 80),
        ("Ελαχιστοποίηση κενών τάξεων", "soft", "class",
         '{"type": "min_class_gaps"}', 90),
        ("Ισοκατανομή μαθημάτων", "soft", "subject",
         '{"type": "subject_distribution"}', 70),
        ("Αποφυγή πολλών συνεχόμενων", "soft", "general",
         '{"type": "max_consecutive"}', 60),
        ("Ισοκατανομή φόρτου καθηγητή", "soft", "teacher",
         '{"type": "teacher_day_balance"}', 50),
    ]

    constraints = []
    for name, ctype, category, rule, weight in defaults:
        c = Constraint(
            name=name, constraint_type=ctype,
            category=category, rule=rule,
            weight=weight, is_active=True,
        )
        db.add(c)
        constraints.append(c)

    db.commit()
    for c in constraints:
        db.refresh(c)
    return constraints
