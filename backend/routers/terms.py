"""Terms / scenarios API — CRUD + activate + clone.

A "term" (σενάριο) scopes the input data (lessons, availability, solutions) so
multiple scheduling scenarios can coexist independently. Exactly one term is
active at a time; scoped endpoints default to it.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Term, Lesson, TimetableSolution
from backend.schemas import TermCreate, TermUpdate, TermResponse, TermCloneRequest, TermShiftRequest
from backend.services.term_context import get_active_term_id
from backend.services import term_cloner, term_time_shift

router = APIRouter()


@router.get("/", response_model=list[TermResponse])
def list_terms(db: Session = Depends(get_db)):
    return db.query(Term).order_by(Term.id).all()


@router.get("/active", response_model=TermResponse)
def get_active(db: Session = Depends(get_db)):
    tid = get_active_term_id(db)
    term = db.query(Term).filter(Term.id == tid).first() if tid else None
    if not term:
        raise HTTPException(status_code=404, detail="Δεν υπάρχει ενεργό σενάριο")
    return term


@router.post("/", response_model=TermResponse, status_code=201)
def create_term(data: TermCreate, db: Session = Depends(get_db)):
    """Create an EMPTY new scenario (no lessons/availability)."""
    term = Term(**data.model_dump())
    # First-ever term becomes active automatically.
    if db.query(Term).count() == 0:
        term.is_active = True
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


@router.put("/{term_id}", response_model=TermResponse)
def update_term(term_id: int, data: TermUpdate, db: Session = Depends(get_db)):
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Το σενάριο δεν βρέθηκε")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(term, key, value)
    db.commit()
    db.refresh(term)
    return term


@router.post("/{term_id}/activate", response_model=TermResponse)
def activate_term(term_id: int, db: Session = Depends(get_db)):
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Το σενάριο δεν βρέθηκε")
    db.query(Term).update({Term.is_active: False})
    term.is_active = True
    db.commit()
    db.refresh(term)
    return term


@router.post("/{term_id}/clone", response_model=TermResponse, status_code=201)
def clone_term(term_id: int, data: TermCloneRequest, db: Session = Depends(get_db)):
    """Create a new scenario by deep-copying an existing one's inputs
    (lessons + availability). Generated programs are NOT copied."""
    source = db.query(Term).filter(Term.id == term_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Το σενάριο-πηγή δεν βρέθηκε")

    new_term = Term(name=data.name, short_name=data.short_name, notes=data.notes, is_active=False)
    db.add(new_term)
    db.flush()  # assign id without committing yet

    term_cloner.clone_term_inputs(db, term_id, new_term)

    if data.activate:
        db.query(Term).filter(Term.id != new_term.id).update({Term.is_active: False})
        new_term.is_active = True

    db.commit()
    db.refresh(new_term)
    return new_term


@router.post("/{term_id}/shift-times")
def shift_times(term_id: int, data: TermShiftRequest, db: Session = Depends(get_db)):
    """Uniformly shift this scenario's hours (availability + its programs'
    slots) by `offset` teaching periods — e.g. morning → afternoon."""
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Το σενάριο δεν βρέθηκε")
    if data.offset == 0:
        raise HTTPException(status_code=400, detail="Η μετατόπιση δεν μπορεί να είναι 0.")
    res = term_time_shift.shift_term_times(db, term_id, data.offset, data.shift_solutions)
    db.commit()
    return {"status": "ok", **res}


@router.delete("/{term_id}", status_code=204)
def delete_term(
    term_id: int,
    force: bool = Query(False, description="Confirm destructive cascade delete"),
    db: Session = Depends(get_db),
):
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Το σενάριο δεν βρέθηκε")

    if db.query(Term).count() <= 1:
        raise HTTPException(status_code=400, detail="Δεν μπορείς να διαγράψεις το μοναδικό σενάριο.")

    # Safety guard: deleting a term CASCADE-deletes its lessons, availability
    # and generated programs. Require explicit confirmation.
    if not force:
        lessons = db.query(Lesson).filter(Lesson.term_id == term_id).count()
        sols = db.query(TimetableSolution).filter(TimetableSolution.term_id == term_id).count()
        if lessons or sols:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "term_in_use",
                    "requires_force": True,
                    "message": (
                        f"Το σενάριο «{term.name}» θα διαγραφεί ΟΡΙΣΤΙΚΑ μαζί με "
                        f"{lessons} μαθήματα και {sols} προγράμματα. Θέλεις σίγουρα;"
                    ),
                    "lessons": lessons,
                    "solutions": sols,
                },
            )

    was_active = term.is_active
    db.delete(term)
    db.flush()
    if was_active:
        nxt = db.query(Term).order_by(Term.id).first()
        if nxt:
            nxt.is_active = True
    db.commit()
