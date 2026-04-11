"""
Periods API — CRUD for daily time slots / bell schedule.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Period
from backend.schemas import PeriodCreate, PeriodResponse

router = APIRouter()


@router.get("/", response_model=list[PeriodResponse])
def list_periods(db: Session = Depends(get_db)):
    return db.query(Period).order_by(Period.sort_order).all()


@router.get("/{period_id}", response_model=PeriodResponse)
def get_period(period_id: int, db: Session = Depends(get_db)):
    period = db.query(Period).filter(Period.id == period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="Η ώρα δεν βρέθηκε")
    return period


@router.post("/", response_model=PeriodResponse, status_code=201)
def create_period(data: PeriodCreate, db: Session = Depends(get_db)):
    period = Period(**data.model_dump())
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


@router.put("/{period_id}", response_model=PeriodResponse)
def update_period(period_id: int, data: PeriodCreate, db: Session = Depends(get_db)):
    period = db.query(Period).filter(Period.id == period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="Η ώρα δεν βρέθηκε")
    for key, value in data.model_dump().items():
        setattr(period, key, value)
    db.commit()
    db.refresh(period)
    return period


@router.delete("/{period_id}", status_code=204)
def delete_period(period_id: int, db: Session = Depends(get_db)):
    period = db.query(Period).filter(Period.id == period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="Η ώρα δεν βρέθηκε")
    db.delete(period)
    db.commit()


@router.post("/seed-defaults", response_model=list[PeriodResponse], status_code=201)
def seed_default_periods(db: Session = Depends(get_db)):
    """Populate with standard Greek school period schedule."""
    existing = db.query(Period).count()
    if existing > 0:
        raise HTTPException(status_code=409, detail="Υπάρχουν ήδη ώρες — διαγράψτε τις πρώτα")

    defaults = [
        ("1η Ώρα", "1", "14:00", "14:50", False, 1),
        ("2η Ώρα", "2", "15:00", "15:50", False, 2),
        ("3η Ώρα", "3", "16:00", "16:50", False, 3),
        ("4η Ώρα", "4", "17:00", "17:50", False, 4),
        ("5η Ώρα", "5", "18:00", "18:50", False, 5),
        ("6η Ώρα", "6", "19:00", "19:50", False, 6),
        ("7η Ώρα", "7", "20:00", "20:50", False, 7),
        ("8η Ώρα", "8", "21:00", "21:50", False, 8),
    ]

    periods = []
    for name, short, start, end, is_brk, order in defaults:
        period = Period(
            name=name, short_name=short,
            start_time=start, end_time=end,
            is_break=is_brk, sort_order=order,
        )
        db.add(period)
        periods.append(period)

    db.commit()
    for p in periods:
        db.refresh(p)
    return periods
