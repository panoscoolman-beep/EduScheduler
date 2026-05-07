"""
Lessons API — CRUD for lesson cards (the core link entity).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Lesson, Subject, Teacher, SchoolClass, Classroom
from backend.schemas import LessonCreate, LessonResponse

router = APIRouter()


def _enrich_lesson(lesson: Lesson) -> dict:
    """Add human-readable names from related entities."""
    data = {
        "id": lesson.id,
        "subject_id": lesson.subject_id,
        "teacher_id": lesson.teacher_id,
        "class_id": lesson.class_id,
        "classroom_id": lesson.classroom_id,
        "periods_per_week": lesson.periods_per_week,
        "duration": lesson.duration,
        "is_locked": lesson.is_locked,
        "subject_name": lesson.subject.name if lesson.subject else None,
        "teacher_name": lesson.teacher.name if lesson.teacher else None,
        "class_name": lesson.school_class.name if lesson.school_class else None,
        "classroom_name": lesson.classroom.name if lesson.classroom else None,
    }
    return data


@router.get("/", response_model=list[LessonResponse])
def list_lessons(db: Session = Depends(get_db)):
    lessons = (
        db.query(Lesson)
        .options(
            joinedload(Lesson.subject),
            joinedload(Lesson.teacher),
            joinedload(Lesson.school_class),
            joinedload(Lesson.classroom),
        )
        .all()
    )
    return [_enrich_lesson(l) for l in lessons]


# IMPORTANT: This route must be declared BEFORE `/{lesson_id}` so
# FastAPI doesn't try to parse 'distribution-suggestions' as an int.
@router.get("/distribution-suggestions")
def distribution_suggestions(
    ppw: int,
    db: Session = Depends(get_db),
):
    """User-friendly suggestions για το πώς να σπάσει `ppw` ώρες
    σε blocks. Διαβάζει το max_block από `Period` rows (μη-break)."""
    from backend.services.distribution_helper import common_distributions, label
    from backend.models import Period

    teaching_periods = (
        db.query(Period).filter(Period.is_break == False).count()  # noqa: E712
    )
    max_block = teaching_periods if teaching_periods > 0 else 8

    splits = common_distributions(ppw, max_block=max_block)
    return {
        "ppw": ppw,
        "max_block": max_block,
        "options": [
            {
                "blocks": s,
                "label": label(s),
                "value": ",".join(str(x) for x in s),
            }
            for s in splits
        ],
    }


@router.get("/{lesson_id}", response_model=LessonResponse)
def get_lesson(lesson_id: int, db: Session = Depends(get_db)):
    lesson = (
        db.query(Lesson)
        .options(
            joinedload(Lesson.subject),
            joinedload(Lesson.teacher),
            joinedload(Lesson.school_class),
            joinedload(Lesson.classroom),
        )
        .filter(Lesson.id == lesson_id)
        .first()
    )
    if not lesson:
        raise HTTPException(status_code=404, detail="Το μάθημα-κάρτα δεν βρέθηκε")
    return _enrich_lesson(lesson)


@router.post("/", response_model=LessonResponse, status_code=201)
def create_lesson(data: LessonCreate, db: Session = Depends(get_db)):
    # Validate foreign keys
    if not db.query(Subject).filter(Subject.id == data.subject_id).first():
        raise HTTPException(status_code=404, detail="Το μάθημα δεν βρέθηκε")
    if not db.query(Teacher).filter(Teacher.id == data.teacher_id).first():
        raise HTTPException(status_code=404, detail="Ο καθηγητής δεν βρέθηκε")
    if not db.query(SchoolClass).filter(SchoolClass.id == data.class_id).first():
        raise HTTPException(status_code=404, detail="Η τάξη δεν βρέθηκε")
    if data.classroom_id and not db.query(Classroom).filter(Classroom.id == data.classroom_id).first():
        raise HTTPException(status_code=404, detail="Η αίθουσα δεν βρέθηκε")

    lesson = Lesson(**data.model_dump())
    db.add(lesson)
    db.commit()

    # Reload with relationships
    lesson = (
        db.query(Lesson)
        .options(
            joinedload(Lesson.subject),
            joinedload(Lesson.teacher),
            joinedload(Lesson.school_class),
            joinedload(Lesson.classroom),
        )
        .filter(Lesson.id == lesson.id)
        .first()
    )
    return _enrich_lesson(lesson)


@router.put("/{lesson_id}", response_model=LessonResponse)
def update_lesson(lesson_id: int, data: LessonCreate, db: Session = Depends(get_db)):
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Το μάθημα-κάρτα δεν βρέθηκε")
    for key, value in data.model_dump().items():
        setattr(lesson, key, value)
    db.commit()

    lesson = (
        db.query(Lesson)
        .options(
            joinedload(Lesson.subject),
            joinedload(Lesson.teacher),
            joinedload(Lesson.school_class),
            joinedload(Lesson.classroom),
        )
        .filter(Lesson.id == lesson_id)
        .first()
    )
    return _enrich_lesson(lesson)


@router.delete("/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: int, db: Session = Depends(get_db)):
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Το μάθημα-κάρτα δεν βρέθηκε")
    db.delete(lesson)
    db.commit()


@router.post("/bulk-import/preview")
def bulk_import_preview(
    payload: dict,
    db: Session = Depends(get_db),
):
    """Parse CSV text and return per-row validation. Read-only — no
    rows are inserted yet. The user reviews, then calls /commit.

    Body: {"csv": "<header line>\\n<data...>"}
    """
    from backend.services.lesson_importer import preview as svc_preview

    csv_text = payload.get("csv", "")
    result = svc_preview(csv_text, db)
    return {
        "fatal_error": result.fatal_error,
        "valid_count": result.valid_count,
        "error_count": result.error_count,
        "rows": [
            {
                "line_number": r.line_number,
                "raw": r.raw,
                "is_valid": r.is_valid,
                "errors": r.errors,
                "subject_id": r.subject_id,
                "teacher_id": r.teacher_id,
                "class_id": r.class_id,
                "classroom_id": r.classroom_id,
                "periods_per_week": r.periods_per_week,
                "distribution": r.distribution,
            }
            for r in result.rows
        ],
    }


@router.post("/bulk-import/commit")
def bulk_import_commit(
    payload: dict,
    db: Session = Depends(get_db),
):
    """Commit a previously-previewed import. Body must echo the same
    CSV text — we re-parse and re-validate server-side to defend
    against tampering between preview and commit."""
    from backend.services.lesson_importer import (
        preview as svc_preview,
        commit as svc_commit,
    )

    csv_text = payload.get("csv", "")
    result = svc_preview(csv_text, db)
    if result.fatal_error:
        return {"status": "error", "message": result.fatal_error, "created": 0}

    return svc_commit(result.rows, db)
