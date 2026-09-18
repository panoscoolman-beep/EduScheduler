"""📢 Δημοσίευση προγράμματος + ουρά μηνυμάτων για το Telegram bot του CRM."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import SolutionPublication, utcnow_naive
from backend.services import publication as pub_service
from backend.services.term_context import resolve_term_id

router = APIRouter()


class PublishRequest(BaseModel):
    note: str | None = Field(None, max_length=500)
    notify_telegram: bool = True


def _public(preview: dict) -> dict:
    return {k: v for k, v in preview.items() if not k.startswith("_")}


@router.get("")
def list_publications(term_id: int | None = None, db: Session = Depends(get_db)):
    tid = resolve_term_id(db, term_id)
    rows = (db.query(SolutionPublication)
            .filter(SolutionPublication.term_id == tid)
            .order_by(SolutionPublication.published_at.desc(), SolutionPublication.id.desc())
            .limit(20).all())
    return [pub_service.publication_summary(p) for p in rows]


@router.get("/pending-telegram")
def pending_telegram(db: Session = Depends(get_db)):
    return pub_service.pending_telegram(db)


@router.post("/{publication_id}/telegram-sent")
def mark_telegram_sent(publication_id: int, db: Session = Depends(get_db)):
    pub = db.query(SolutionPublication).filter(SolutionPublication.id == publication_id).first()
    if pub is None:
        raise HTTPException(404, "Η δημοσίευση δεν βρέθηκε.")
    if pub.telegram_sent_at is None:
        pub.telegram_sent_at = utcnow_naive()
        db.commit()
    return pub_service.publication_summary(pub)


@router.get("/preview/{solution_id}")
def preview(solution_id: int, db: Session = Depends(get_db)):
    try:
        return _public(pub_service.preview(db, solution_id))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except pub_service.PublishError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@router.post("/solutions/{solution_id}")
def publish(solution_id: int, body: PublishRequest, db: Session = Depends(get_db)):
    try:
        pub = pub_service.publish(db, solution_id, body.note, body.notify_telegram)
        db.commit()
    except LookupError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    except pub_service.PublishError as e:
        db.rollback()
        raise HTTPException(409, {"code": e.code, "message": str(e)})
    return pub_service.publication_summary(pub)
