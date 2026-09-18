"""
Lessons API — CRUD for lesson cards (the core link entity).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Lesson, Subject, Teacher, SchoolClass, Classroom
from backend.services.lesson_impact import lesson_impact, palette_review
from backend.schemas import (
    PaletteCleanupRequest,
    LessonCreate,
    LessonResponse,
    LessonTermImportRequest,
)
from backend.services.term_context import get_active_term_id
from backend.services.parking_lot_sync import (
    add_lesson_to_open_solutions,
    sync_lesson_slot_count,
)

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
def list_lessons(term_id: int | None = None, db: Session = Depends(get_db)):
    """Λίστα μαθημάτων-καρτών. Default: το ενεργό σενάριο· με ?term_id=X
    επιστρέφει τα μαθήματα ΑΛΛΟΥ σεναρίου (τροφοδοτεί τον picker της
    επιλεκτικής εισαγωγής)."""
    if term_id is not None:
        from backend.models import Term
        if not db.query(Term).filter(Term.id == term_id).first():
            raise HTTPException(status_code=404, detail="Το σενάριο δεν βρέθηκε")
    scope_term_id = term_id if term_id is not None else get_active_term_id(db)
    lessons = (
        db.query(Lesson)
        .filter(Lesson.term_id == scope_term_id)
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


@router.get("/palette-review")
def get_palette_review(term_id: int | None = None, db: Session = Depends(get_db)):
    """🧹 Όλα τα μαθήματα-κάρτες με ώρες στην Παλέτα + ασφαλής πρόταση για
    το καθένα (trim / delete / keep). Read-only. Default: το ενεργό σενάριο."""
    return palette_review(db, term_id if term_id is not None else get_active_term_id(db))


@router.post("/palette-cleanup")
def apply_palette_cleanup(data: PaletteCleanupRequest, db: Session = Depends(get_db)):
    """Εφαρμογή του καθαρίσματος. Κάθε μάθημα ΞΑΝΑΕΛΕΓΧΕΤΑΙ εδώ (τα δεδομένα
    μπορεί να άλλαξαν από την προεπισκόπηση):
      • trim: μόνο αν ακόμα περισσεύουν ώρες — ποτέ τοποθετημένη ώρα·
      • delete: μόνο αν δεν υπάρχει ΚΑΜΙΑ τοποθετημένη ώρα σε κανένα πρόγραμμα.
    Ό,τι δεν είναι ασφαλές παραλείπεται με αιτία."""
    trimmed, hours_removed, deleted, skipped = 0, 0, 0, []
    for lesson_id in dict.fromkeys(int(i) for i in data.trim_ids):
        report = lesson_impact(db, lesson_id)
        if report is None:
            skipped.append({"lesson_id": lesson_id, "reason": "Δεν βρέθηκε."})
        elif not report["trim"]["can_trim"]:
            skipped.append({"lesson_id": lesson_id, "reason": "Δεν περισσεύουν πια ώρες."})
        else:
            hours_removed += _apply_trim(db, lesson_id, report["trim"]["trim_to"])
            trimmed += 1
    for lesson_id in dict.fromkeys(int(i) for i in data.delete_ids):
        report = lesson_impact(db, lesson_id)
        if report is None:
            skipped.append({"lesson_id": lesson_id, "reason": "Δεν βρέθηκε."})
        elif report["delete"]["placed_total"]:
            skipped.append({"lesson_id": lesson_id,
                            "reason": "Έχει τοποθετημένες ώρες — διάγραψέ το από το 🔍 αν το θες."})
        else:
            db.delete(db.query(Lesson).filter(Lesson.id == lesson_id).first())
            db.commit()
            deleted += 1
    return {
        "trimmed": trimmed, "hours_removed": hours_removed, "deleted": deleted, "skipped": skipped,
        "message": (f"Αφαιρέθηκαν {hours_removed} ώρες από την Παλέτα ({trimmed} μαθήματα) και "
                    f"διαγράφηκαν {deleted} μαθήματα χωρίς τοποθετημένες ώρες. Καμία τοποθετημένη "
                    "ώρα δεν πειράχτηκε."),
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

    lesson = Lesson(term_id=get_active_term_id(db), **data.model_dump())
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    # Drop the new lesson into the parking lot of every active
    # (optimal/feasible) solution so the user can manually slot it
    # without re-running the solver and scrambling the schedule.
    add_lesson_to_open_solutions(db, lesson.id)

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

    # Reconcile each active solution's slot count with the (possibly
    # changed) periods_per_week. Adds unplaced rows for new hours,
    # trims excess unplaced rows for removed hours. Never deletes a
    # placed slot — surplus there is left for the user to clean up.
    sync_lesson_slot_count(db, lesson_id)

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


@router.get("/{lesson_id}/impact")
def lesson_impact_report(lesson_id: int, db: Session = Depends(get_db)):
    """Τι επηρεάζει αυτό το μάθημα-κάρτα: πού είναι τοποθετημένο, τι περιμένει
    στην Παλέτα και τι θα χαθεί σε καθάρισμα ή διαγραφή. Read-only."""
    report = lesson_impact(db, lesson_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Το μάθημα-κάρτα δεν βρέθηκε")
    return report


def _apply_trim(db: Session, lesson_id: int, trim_to: int) -> int:
    """Ώρες/εβδ. → trim_to και συγχρονισμός· σβήνονται ΜΟΝΟ ώρες Παλέτας."""
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    lesson.periods_per_week = trim_to
    db.commit()
    sync = sync_lesson_slot_count(db, lesson_id)
    return sum(int(s.get("removed", 0)) for s in sync.get("synced", []))


@router.post("/{lesson_id}/trim-unplaced")
def trim_unplaced_hours(lesson_id: int, db: Session = Depends(get_db)):
    """Κράτα μόνο τις ώρες που χρησιμοποιούνται: οι ώρες/εβδομάδα πέφτουν στις
    τοποθετημένες και σβήνονται ΜΟΝΟ ώρες της Παλέτας (ποτέ τοποθετημένη)."""
    report = lesson_impact(db, lesson_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Το μάθημα-κάρτα δεν βρέθηκε")

    trim = report["trim"]
    if not trim["can_trim"]:
        messages = {
            "no_placed_hours": ("Καμία ώρα αυτού του μαθήματος δεν είναι τοποθετημένη. "
                                "Αν δεν το χρειάζεσαι, διάγραψε ολόκληρο το μάθημα."),
            "nothing_to_trim": "Δεν υπάρχουν ώρες στην Παλέτα για αυτό το μάθημα.",
        }
        raise HTTPException(status_code=409, detail={
            "code": trim["blocked_reason"],
            "message": messages.get(trim["blocked_reason"], "Δεν υπάρχει τίποτα να αφαιρεθεί."),
            "impact": report,
        })

    removed = _apply_trim(db, lesson_id, trim["trim_to"])
    return {
        "lesson_id": lesson_id,
        "periods_per_week": trim["trim_to"],
        "removed": removed,
        "message": (f"Οι ώρες/εβδομάδα έγιναν {trim['trim_to']}. Αφαιρέθηκαν {removed} ώρες "
                    "από την Παλέτα — καμία τοποθετημένη ώρα δεν πειράχτηκε."),
    }


@router.delete("/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: int, force: bool = False, db: Session = Depends(get_db)):
    """Διαγραφή μαθήματος-κάρτας.

    ⚠️ Σβήνει ΚΑΙ τις τοποθετημένες ώρες του σε ΟΛΑ τα προγράμματα του
    σεναρίου (FK cascade). Γι' αυτό, όταν υπάρχουν τοποθετημένες ώρες,
    επιστρέφεται 409 με τα πλήθη και χρειάζεται ρητό `?force=true` — ίδιο
    μοτίβο με τις ώρες (periods) και τα σενάρια."""
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Το μάθημα-κάρτα δεν βρέθηκε")

    report = lesson_impact(db, lesson_id)
    info = report["delete"]
    if info["placed_total"] and not force:
        raise HTTPException(status_code=409, detail={
            "code": "lesson_has_placed_slots",
            "requires_force": True,
            "message": (f"Το μάθημα έχει {info['placed_total']} τοποθετημένες ώρες σε "
                        f"{info['solutions_with_placed']} πρόγραμμα(τα). Η διαγραφή θα τις "
                        "σβήσει οριστικά."),
            "impact": report,
        })

    db.delete(lesson)
    db.commit()


@router.post("/import-from-term")
def import_lessons_from_term(data: LessonTermImportRequest, db: Session = Depends(get_db)):
    """Επιλεκτική εισαγωγή μαθημάτων-καρτών από άλλο σενάριο στο ΕΝΕΡΓΟ.

    Το αντίθετο του all-or-nothing clone: ο χρήστης διαλέγει ποια
    μαθήματα «έρχονται». Αντιγράφονται τα ίδια πεδία με τον term cloner·
    διπλότυπα (ίδιο μάθημα+καθηγητής+τμήμα στο ενεργό) παραλείπονται με
    αναφορά. Οι ώρες των νέων μαθημάτων πάνε στην Παλέτα των ανοιχτών
    λύσεων του ενεργού σεναρίου (parking-lot sync).
    """
    from backend.models import Term

    active_term_id = get_active_term_id(db)
    if data.source_term_id == active_term_id:
        raise HTTPException(
            status_code=400,
            detail="Το σενάριο-πηγή είναι το ήδη ενεργό σενάριο.",
        )
    if not db.query(Term).filter(Term.id == data.source_term_id).first():
        raise HTTPException(status_code=404, detail="Το σενάριο-πηγή δεν βρέθηκε")

    existing_triples = {
        (l.subject_id, l.teacher_id, l.class_id)
        for l in db.query(Lesson)
        .filter(Lesson.term_id == active_term_id)
        .all()
    }

    created_ids: list[int] = []
    skipped: list[dict] = []
    for lid in data.lesson_ids:
        src = (
            db.query(Lesson)
            .filter(Lesson.id == lid, Lesson.term_id == data.source_term_id)
            .first()
        )
        if not src:
            skipped.append({"lesson_id": lid, "reason": "not_in_source_term"})
            continue
        triple = (src.subject_id, src.teacher_id, src.class_id)
        if triple in existing_triples:
            skipped.append({"lesson_id": lid, "reason": "already_exists"})
            continue
        new_lesson = Lesson(
            term_id=active_term_id,
            subject_id=src.subject_id,
            teacher_id=src.teacher_id,
            class_id=src.class_id,
            classroom_id=src.classroom_id,
            periods_per_week=src.periods_per_week,
            duration=src.duration,
            distribution=src.distribution,
            is_locked=src.is_locked,
        )
        db.add(new_lesson)
        db.flush()
        existing_triples.add(triple)
        created_ids.append(new_lesson.id)
    db.commit()

    # Οι νέες ώρες εμφανίζονται αμέσως στην Παλέτα των ενεργών λύσεων
    # (idempotent, term-scoped — αγγίζει μόνο λύσεις του ενεργού).
    for nid in created_ids:
        add_lesson_to_open_solutions(db, nid)

    return {
        "status": "ok",
        "created": len(created_ids),
        "created_ids": created_ids,
        "skipped": skipped,
        "message": (
            f"Εισήχθησαν {len(created_ids)} μαθήματα"
            + (f", παραλείφθηκαν {len(skipped)}" if skipped else "")
        ),
    }


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
