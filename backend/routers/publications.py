"""📢 Δημοσίευση προγράμματος + ουρά μηνυμάτων για το Telegram bot του CRM."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend.services import crm_mail
from backend.models import SolutionPublication, utcnow_naive
from backend.services import publication as pub_service
from backend.services.term_context import resolve_term_id

router = APIRouter()


class PublishRequest(BaseModel):
    note: str | None = Field(None, max_length=500)
    notify_telegram: bool = True
    email_teacher_ids: list[int] = Field(default_factory=list, max_length=100)


class EmailRequest(BaseModel):
    teacher_ids: list[int] = Field(..., min_length=1, max_length=100)


class TestEmailRequest(BaseModel):
    teacher_id: int
    to: str = Field(..., min_length=5, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _send_emails_job(publication_id: int) -> None:
    """Background: δική του session (η session του request έχει κλείσει)."""
    db = SessionLocal()
    try:
        pub_service.send_emails(db, publication_id, crm_mail.send_teacher_schedule)
    finally:
        db.close()


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


@router.get("/{publication_id}")
def publication_detail(publication_id: int, db: Session = Depends(get_db)):
    detail = pub_service.publication_detail(db, publication_id)
    if detail is None:
        raise HTTPException(404, "Η δημοσίευση δεν βρέθηκε.")
    return detail


@router.post("/{publication_id}/emails")
def send_publication_emails(publication_id: int, body: EmailRequest, background: BackgroundTasks,
                            db: Session = Depends(get_db)):
    """✉️ Email στους επιλεγμένους για την ΤΕΛΕΥΤΑΙΑ δημοσίευση (χωρίς νέα δημοσίευση)."""
    try:
        pub = pub_service.request_emails(db, publication_id, body.teacher_ids)
        db.commit()
    except LookupError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    except pub_service.PublishError as e:
        db.rollback()
        raise HTTPException(409, {"code": e.code, "message": str(e)})
    background.add_task(_send_emails_job, pub.id)
    return pub_service.publication_summary(pub)


@router.post("/preview/{solution_id}/test-email")
def test_email(solution_id: int, body: TestEmailRequest, db: Session = Depends(get_db)):
    """✉️ Δοκιμαστικό email ενός καθηγητή σε ΔΙΚΗ σου διεύθυνση — δεν δημοσιεύει τίποτα."""
    try:
        ok, error = pub_service.send_test_email(db, solution_id, body.teacher_id, body.to,
                                                crm_mail.send_teacher_schedule)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except pub_service.PublishError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})
    if not ok:
        raise HTTPException(502, f"Δεν στάλθηκε: {error}")
    return {"status": "sent", "to": body.to}


@router.get("/preview/{solution_id}")
def preview(solution_id: int, db: Session = Depends(get_db)):
    try:
        return _public(pub_service.preview(db, solution_id))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except pub_service.PublishError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@router.post("/solutions/{solution_id}")
def publish(solution_id: int, body: PublishRequest, background: BackgroundTasks,
            db: Session = Depends(get_db)):
    try:
        pub = pub_service.publish(db, solution_id, body.note, body.notify_telegram,
                                  body.email_teacher_ids)
        db.commit()
    except LookupError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    except pub_service.PublishError as e:
        db.rollback()
        raise HTTPException(409, {"code": e.code, "message": str(e)})
    if pub.email_state == "sending":
        background.add_task(_send_emails_job, pub.id)
    return pub_service.publication_summary(pub)
