"""
Solver API — Generate timetables and check status.
"""

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import (
    TimetableSolution, TimetableSlot, Lesson, Classroom,
    TeacherAvailability, StudentAvailability, StudentClassEnrollment,
    utcnow_naive,
)
from backend.services import slot_history as slot_history_svc
from backend.services.slot_placement import (
    build_placement_map,
    resolve_and_validate_target_room,
)
from backend.services.term_context import get_active_term_id
from backend.services.solver_jobs import (
    _guard_no_active_solve,
    _iso_utc,
    _run_generation_job,
)
from backend.services.substitute_finder import find_substitutes
from backend.schemas import (
    FeasibilityReportResponse,
    SlotSwapRequest,
    SolverRequest,
    SolverStatusResponse,
    TimetableSolutionResponse,
    TimetableSlotResponse,
    TimetableSlotUpdate,
)
from backend.services.feasibility import check_feasibility
from backend.services.solution_diff import compute_diff
from backend.services.violations_report import compute_violations

router = APIRouter()


# Classroom resolution + manual-move conflict checks now live in
# backend/services/slot_placement.py (extracted for readability).


@router.get("/diff")
def solution_diff(base_id: int, other_id: int, db: Session = Depends(get_db)):
    """Slot-level diff δύο λύσεων: moved/added/removed ανά μάθημα (από
    πού → πού) + μεταβολή φόρτου ανά καθηγητή. Το «τι άλλαξε;» μετά από
    ένα regenerate, ώστε να μη συγκρίνεις δύο grids με το μάτι."""
    diff = compute_diff(db, base_id, other_id)
    if diff is None:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")
    return diff


@router.get("/solutions/{solution_id}/violations")
def solution_violations(solution_id: int, db: Session = Depends(get_db)):
    """Ονομαστική αναφορά soft-constraint παραβιάσεων: ποιος καθηγητής έχει
    κενό πότε, ποια μαθήματα πέφτουν αργά, φόρτος ανά καθηγητή — το
    «γιατί αυτό το score;» πίσω από τον αριθμό της λύσης."""
    report = compute_violations(db, solution_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")
    return report


@router.get("/feasibility-check", response_model=FeasibilityReportResponse)
def feasibility_check(term_id: int | None = None, db: Session = Depends(get_db)):
    """Run a fast pre-solve feasibility analysis without invoking CP-SAT.

    Helps the user catch over-constrained problems (overloaded teachers,
    missing labs, blocks too long for the school day) in milliseconds
    instead of waiting 30+ seconds for the solver to fail.
    ?term_id= σκοπεύει συγκεκριμένο σενάριο (default: το ενεργό).
    """
    return check_feasibility(db, term_id=term_id).to_dict()


@router.post("/generate", response_model=SolverStatusResponse)
def generate_timetable(
    request: SolverRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Kick off timetable generation in the background.

    Returns immediately with status='generating'; the UI polls
    GET /solver/status/{solution_id} until it flips. This keeps 10-minute
    solver runs out of HTTP request handlers (no held worker, no timeout).
    """
    _guard_no_active_solve(db)

    # Validate the warm-start source BEFORE creating the solution row —
    # the old order leaked an orphan 'generating' record on 404.
    warm_start_assignments: list[dict] = []
    if request.warm_start_from_solution_id:
        source = (
            db.query(TimetableSolution)
            .filter(TimetableSolution.id == request.warm_start_from_solution_id)
            .first()
        )
        if not source:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Δεν βρέθηκε λύση id={request.warm_start_from_solution_id} "
                    "για warm start"
                ),
            )
        prior_slots = (
            db.query(TimetableSlot)
            .filter(
                TimetableSlot.solution_id == source.id,
                TimetableSlot.is_unplaced == False,  # noqa: E712
            )
            .all()
        )
        warm_start_assignments = [
            {
                "lesson_id": s.lesson_id,
                "day_of_week": s.day_of_week,
                "period_id": s.period_id,
                "classroom_id": s.classroom_id,
            }
            for s in prior_slots
        ]

    solution = TimetableSolution(
        name=request.name,
        status="generating",
        created_at=utcnow_naive(),
        term_id=get_active_term_id(db),
    )
    db.add(solution)
    db.commit()
    db.refresh(solution)

    background_tasks.add_task(
        _run_generation_job,
        solution.id,
        request.max_time_seconds,
        request.mode,
        warm_start_assignments,
    )

    return SolverStatusResponse(
        solution_id=solution.id,
        status="generating",
        message="Η δημιουργία ξεκίνησε — ο solver τρέχει στο παρασκήνιο.",
        score=None,
        placed_count=0,
        unplaced_count=0,
    )


@router.get("/status/{solution_id}", response_model=SolverStatusResponse)
def solver_status(solution_id: int, db: Session = Depends(get_db)):
    """Polling endpoint for a generation kicked off by POST /generate."""
    solution = (
        db.query(TimetableSolution)
        .filter(TimetableSolution.id == solution_id)
        .first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")

    placed = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == solution_id,
                TimetableSlot.is_unplaced == False)  # noqa: E712
        .count()
    )
    unplaced = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == solution_id,
                TimetableSlot.is_unplaced == True)  # noqa: E712
        .count()
    )

    if solution.status == "generating":
        message = "Ο solver τρέχει..."
    elif solution.status in ("optimal", "feasible"):
        message = f"Ολοκληρώθηκε ({solution.status}) — {placed} μαθήματα τοποθετήθηκαν."
        if unplaced:
            message += f" {unplaced} στο parking lot."
    else:
        meta = {}
        try:
            meta = json.loads(solution.metadata_json or "{}")
        except ValueError:
            pass
        message = meta.get("message", f"Κατάσταση: {solution.status}")
        # Surface concrete infeasibility reasons when we have them.
        reasons = meta.get("feasibility_errors") or []
        if solution.status == "infeasible" and reasons:
            message = "Αδύνατο πρόγραμμα. Αιτίες:\n• " + "\n• ".join(reasons[:6])

    return SolverStatusResponse(
        solution_id=solution.id,
        status=solution.status,
        message=message,
        score=solution.score,
        placed_count=placed,
        unplaced_count=unplaced,
    )


@router.post("/regenerate/{source_solution_id}", response_model=SolverStatusResponse)
def regenerate_with_locks(
    source_solution_id: int,
    request: SolverRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Run the solver again, keeping every is_locked=TRUE slot from a
    source solution as hard fixed points. The unlocked slots are
    redistributed.

    The result is a NEW solution (we don't mutate the source) so
    history is preserved and the user can compare the two.
    """
    _guard_no_active_solve(db)

    source = db.query(TimetableSolution).filter(
        TimetableSolution.id == source_solution_id
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Η λύση πηγή δεν βρέθηκε")

    locked_slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.solution_id == source_solution_id,
            TimetableSlot.is_locked == True,  # noqa: E712
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .all()
    )

    if not locked_slots:
        raise HTTPException(
            status_code=400,
            detail=(
                "Δεν έχει κλειδωθεί κανένα μάθημα. Πάτησε το 🔒 σε "
                "όσα θες να διατηρήσεις και ξανατρέξε."
            ),
        )

    locked_assignments = [
        {
            "lesson_id": s.lesson_id,
            "day_of_week": s.day_of_week,
            "period_id": s.period_id,
            "classroom_id": s.classroom_id,
        }
        for s in locked_slots
    ]

    # Create the new solution record and run the solver in the background
    # (same pattern as /generate) so Lock & Regenerate no longer holds an
    # HTTP worker for the full solve and survives a mid-run deploy. The UI
    # polls GET /solver/status/{id}.
    solution = TimetableSolution(
        name=request.name or f"{source.name} (regenerated)",
        status="generating",
        created_at=utcnow_naive(),
        term_id=source.term_id,  # stay in the same scenario as the source
    )
    db.add(solution)
    db.commit()
    db.refresh(solution)

    background_tasks.add_task(
        _run_generation_job,
        solution.id,
        request.max_time_seconds,
        request.mode,
        None,  # no warm-start
        locked_assignments,
        {"locked_from_solution": source_solution_id,
         "locked_count": len(locked_assignments)},
    )

    return SolverStatusResponse(
        solution_id=solution.id,
        status="generating",
        message="Η αναδημιουργία ξεκίνησε — ο solver τρέχει στο παρασκήνιο.",
        score=None,
        placed_count=0,
        unplaced_count=0,
    )


@router.get("/solutions", response_model=list[TimetableSolutionResponse])
def list_solutions(db: Session = Depends(get_db)):
    """List generated timetable solutions for the ACTIVE scenario."""
    solutions = (
        db.query(TimetableSolution)
        .filter(TimetableSolution.term_id == get_active_term_id(db))
        .order_by(TimetableSolution.created_at.desc())
        .all()
    )
    return [
        TimetableSolutionResponse(
            id=s.id,
            name=s.name,
            created_at=_iso_utc(s.created_at),
            status=s.status,
            score=s.score,
        )
        for s in solutions
    ]


@router.get("/solutions/{solution_id}", response_model=TimetableSolutionResponse)
def get_solution(solution_id: int, db: Session = Depends(get_db)):
    """Get a specific timetable solution with all its slots."""
    solution = db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")

    # Load slots with related data
    slots = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == solution_id)
        .options(
            joinedload(TimetableSlot.lesson).joinedload(Lesson.subject),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.teacher),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.school_class),
            joinedload(TimetableSlot.classroom),
        )
        .all()
    )

    enriched_slots = []
    for slot in slots:
        lesson = slot.lesson
        enriched_slots.append(TimetableSlotResponse(
            id=slot.id,
            lesson_id=slot.lesson_id,
            day_of_week=slot.day_of_week,
            period_id=slot.period_id,
            classroom_id=slot.classroom_id,
            is_locked=slot.is_locked,
            is_unplaced=slot.is_unplaced,
            unplaced_reason=slot.unplaced_reason,
            subject_id=lesson.subject_id,
            subject_name=lesson.subject.name if lesson.subject else None,
            subject_short=lesson.subject.short_name if lesson.subject else None,
            subject_color=lesson.subject.color if lesson.subject else None,
            teacher_id=lesson.teacher_id,
            teacher_name=lesson.teacher.name if lesson.teacher else None,
            teacher_short=lesson.teacher.short_name if lesson.teacher else None,
            teacher_color=lesson.teacher.color if lesson.teacher else None,
            class_id=lesson.class_id,
            class_name=lesson.school_class.name if lesson.school_class else None,
            class_short=lesson.school_class.short_name if lesson.school_class else None,
            classroom_name=slot.classroom.name if slot.classroom else None,
        ))

    return TimetableSolutionResponse(
        id=solution.id,
        name=solution.name,
        created_at=_iso_utc(solution.created_at),
        status=solution.status,
        score=solution.score,
        slots=enriched_slots,
    )


@router.get("/compare")
def compare_solutions(ids: str, db: Session = Depends(get_db)):
    """Side-by-side comparison of 2+ solutions.

    Query: GET /api/solver/compare?ids=1,2,3
    Returns: {metrics: [...], winners: {metric_name: solution_id}}
    Lower is better for everything except placed_count.
    """
    from backend.services.solution_metrics import compare as svc_compare

    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, detail="ids must be a comma-separated list of integers")
    if len(id_list) < 1:
        raise HTTPException(400, detail="At least one solution_id is required")

    return svc_compare(id_list, db)


@router.delete("/solutions/{solution_id}", status_code=204)
def delete_solution(solution_id: int, db: Session = Depends(get_db)):
    """Delete a timetable solution."""
    solution = db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")
    db.delete(solution)
    db.commit()


@router.put("/solutions/{solution_id}/slots/{slot_id}", response_model=dict)
def update_solution_slot(
    solution_id: int,
    slot_id: int,
    data: TimetableSlotUpdate,
    db: Session = Depends(get_db),
):
    """Manually update a single slot (Drag and Drop override)."""
    slot = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.id == slot_id,
            TimetableSlot.solution_id == solution_id
        )
        .first()
    )
    if not slot:
        raise HTTPException(status_code=404, detail="Το slot δεν βρέθηκε")

    target_room = resolve_and_validate_target_room(db, slot, data)

    prev_state = {
        "day_of_week": slot.day_of_week,
        "period_id": slot.period_id,
        "classroom_id": slot.classroom_id,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": bool(slot.is_unplaced),
    }

    slot.day_of_week = data.day_of_week
    slot.period_id = data.period_id
    slot.classroom_id = target_room

    if data.is_locked is not None:
        slot.is_locked = data.is_locked

    if slot.is_unplaced:
        slot.is_unplaced = False
        slot.unplaced_reason = None

    new_state = {
        "day_of_week": slot.day_of_week,
        "period_id": slot.period_id,
        "classroom_id": slot.classroom_id,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": bool(slot.is_unplaced),
    }
    operation = "lock" if (
        prev_state["is_locked"] != new_state["is_locked"]
        and prev_state["day_of_week"] == new_state["day_of_week"]
        and prev_state["period_id"] == new_state["period_id"]
    ) else "move"
    slot_history_svc.record_edit(db, slot, prev_state, new_state, operation)
    db.commit()
    # Return the new state so the frontend can keep its in-memory copy in sync
    # (esp. classroom_id, which the server may have auto-reassigned on conflict).
    # classroom_name included so the card/toast can show the new room without
    # a full re-fetch.
    room_name = None
    if slot.classroom_id is not None:
        room = db.query(Classroom).filter(Classroom.id == slot.classroom_id).first()
        room_name = room.name if room else None
    return {
        "status": "ok",
        "message": "Το slot ενημερώθηκε",
        "slot": {"id": slot.id, **new_state, "classroom_name": room_name},
    }


@router.post("/solutions/{solution_id}/slots/swap")
def swap_slots(
    solution_id: int,
    data: SlotSwapRequest,
    db: Session = Depends(get_db),
):
    """Ανταλλαγή θέσεων δύο τοποθετημένων slots (κάρτα πάνω σε κάρτα).

    Ο Α ελέγχεται στο κελί του Β αγνοώντας τον Β (αδειάζει ταυτόχρονα)
    και αντίστροφα — ίδιοι έλεγχοι με το μεμονωμένο drop (καθηγητής/
    τμήμα/αίθουσες/κωλύματα/H7). Οι αίθουσες διατηρούνται αν χωράνε,
    αλλιώς επιλέγεται αυτόματα άλλη ελεύθερη. Ατομικό: ή γίνονται και
    οι δύο μετακινήσεις ή καμία. Καταγράφονται δύο βήματα undo.
    """
    if data.slot_a_id == data.slot_b_id:
        raise HTTPException(status_code=400, detail="Ίδιο slot — τίποτα να ανταλλάξω.")

    def _load(slot_id: int) -> TimetableSlot:
        s = (
            db.query(TimetableSlot)
            .filter(
                TimetableSlot.id == slot_id,
                TimetableSlot.solution_id == solution_id,
            )
            .first()
        )
        if not s:
            raise HTTPException(status_code=404, detail="Το slot δεν βρέθηκε")
        return s

    slot_a = _load(data.slot_a_id)
    slot_b = _load(data.slot_b_id)

    if slot_a.is_unplaced or slot_b.is_unplaced:
        raise HTTPException(
            status_code=400,
            detail="Ανταλλαγή γίνεται μόνο μεταξύ τοποθετημένων καρτών — "
                   "για κάρτα της παλέτας κάνε απλό drop στο κελί.",
        )
    if slot_a.is_locked or slot_b.is_locked:
        raise HTTPException(
            status_code=400,
            detail="Μία από τις δύο κάρτες είναι κλειδωμένη 🔒 — ξεκλείδωσέ την πρώτα.",
        )
    if (slot_a.day_of_week, slot_a.period_id) == (slot_b.day_of_week, slot_b.period_id):
        raise HTTPException(
            status_code=400,
            detail="Οι κάρτες είναι ήδη στην ίδια μέρα/ώρα — τίποτα να ανταλλάξω.",
        )

    # Στόχος του καθενός: το κελί του άλλου. Χωρίς ρητή αίθουσα — κρατά
    # τη δική του αν είναι ελεύθερη εκεί, αλλιώς auto-εναλλακτική.
    target_a = TimetableSlotUpdate(
        day_of_week=slot_b.day_of_week, period_id=slot_b.period_id
    )
    target_b = TimetableSlotUpdate(
        day_of_week=slot_a.day_of_week, period_id=slot_a.period_id
    )
    room_a = resolve_and_validate_target_room(
        db, slot_a, target_a, extra_exclude_slot_id=slot_b.id
    )
    room_b = resolve_and_validate_target_room(
        db, slot_b, target_b, extra_exclude_slot_id=slot_a.id
    )

    def _state(s: TimetableSlot) -> dict:
        return {
            "day_of_week": s.day_of_week,
            "period_id": s.period_id,
            "classroom_id": s.classroom_id,
            "is_locked": bool(s.is_locked),
            "is_unplaced": bool(s.is_unplaced),
        }

    prev_a, prev_b = _state(slot_a), _state(slot_b)
    slot_a.day_of_week, slot_a.period_id, slot_a.classroom_id = (
        target_a.day_of_week, target_a.period_id, room_a,
    )
    slot_b.day_of_week, slot_b.period_id, slot_b.classroom_id = (
        target_b.day_of_week, target_b.period_id, room_b,
    )
    # Το history CHECK επιτρέπει move/lock/unlock/place/unplace — ένα swap
    # καταγράφεται ως δύο "move" (δύο βήματα undo, χωρίς schema migration).
    slot_history_svc.record_edit(db, slot_a, prev_a, _state(slot_a), "move")
    slot_history_svc.record_edit(db, slot_b, prev_b, _state(slot_b), "move")
    db.commit()

    room_names = {
        r.id: r.name
        for r in db.query(Classroom)
        .filter(Classroom.id.in_([room_a, room_b]))
        .all()
    }
    return {
        "status": "ok",
        "message": "Οι κάρτες αντάλλαξαν θέσεις",
        "slot_a": {"id": slot_a.id, **_state(slot_a),
                   "classroom_name": room_names.get(room_a)},
        "slot_b": {"id": slot_b.id, **_state(slot_b),
                   "classroom_name": room_names.get(room_b)},
    }


MANUAL_UNPLACE_REASON = "Αφαιρέθηκε χειροκίνητα από το πρόγραμμα"


@router.post("/solutions/{solution_id}/slots/{slot_id}/unplace")
def unplace_slot(
    solution_id: int,
    slot_id: int,
    db: Session = Depends(get_db),
):
    """Αφαίρεση τοποθετημένης ώρας πίσω στην Παλέτα (parking).

    Το αντίστροφο της τοποθέτησης: day/period/room γίνονται NULL και
    is_unplaced=True — η κάρτα ξαναγίνεται διαθέσιμη ώρα στην Παλέτα.
    Καταγράφεται ως 'unplace' στο ιστορικό, άρα πλήρως αναιρέσιμο
    (το undo επαναφέρει την ώρα ακριβώς εκεί που ήταν).
    """
    slot = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.id == slot_id,
            TimetableSlot.solution_id == solution_id,
        )
        .first()
    )
    if not slot:
        raise HTTPException(status_code=404, detail="Το slot δεν βρέθηκε")
    if slot.is_unplaced:
        raise HTTPException(
            status_code=400, detail="Η ώρα είναι ήδη στην Παλέτα."
        )
    if slot.is_locked:
        raise HTTPException(
            status_code=400,
            detail="Η κάρτα είναι κλειδωμένη 🔒 — ξεκλείδωσέ την πρώτα.",
        )

    prev_state = {
        "day_of_week": slot.day_of_week,
        "period_id": slot.period_id,
        "classroom_id": slot.classroom_id,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": False,
    }
    slot.day_of_week = None
    slot.period_id = None
    slot.classroom_id = None
    slot.is_unplaced = True
    slot.unplaced_reason = MANUAL_UNPLACE_REASON
    new_state = {
        "day_of_week": None,
        "period_id": None,
        "classroom_id": None,
        "is_locked": bool(slot.is_locked),
        "is_unplaced": True,
    }
    slot_history_svc.record_edit(db, slot, prev_state, new_state, "unplace")
    db.commit()
    return {
        "status": "ok",
        "message": "Η ώρα επέστρεψε στην Παλέτα",
        "slot": {"id": slot.id, **new_state},
    }


@router.get("/solutions/{solution_id}/slots/{slot_id}/placement-map")
def get_placement_map(
    solution_id: int,
    slot_id: int,
    db: Session = Depends(get_db),
):
    """Per-cell legality map για το σύρσιμο μιας κάρτας.

    Το frontend το φορτώνει στο dragstart και γκριζάρει τα κελιά όπου η
    κάρτα δεν μπορεί να πέσει (με αιτία σε tooltip). Καθαρά advisory —
    ο enforcer παραμένει το PUT του slot· εδώ τίποτα δεν αλλάζει.
    """
    slot = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.id == slot_id,
            TimetableSlot.solution_id == solution_id,
        )
        .first()
    )
    if not slot:
        raise HTTPException(status_code=404, detail="Το slot δεν βρέθηκε")
    return build_placement_map(db, slot)


@router.post("/solutions/{solution_id}/lessons/{lesson_id}/sync-slots")
def sync_solution_lesson_slots(
    solution_id: int,
    lesson_id: int,
    db: Session = Depends(get_db),
):
    """Συμπλήρωσε τις ώρες που λείπουν από ένα μάθημα ως parking-lot slots.

    Η Παλέτα Μαθημάτων δείχνει «λείπουν N ώρες» όταν μια λύση έχει
    λιγότερα slots από το periods_per_week του μαθήματος (π.χ. λύση
    παλαιότερη από το parking-lot sync, ή μάθημα που δεν είχε ποτέ slots
    σε αυτήν). Το endpoint τα υλοποιεί ως is_unplaced ώστε να γίνουν
    draggable κάρτες. Idempotent — αν δεν λείπει τίποτα, added=0.
    """
    from backend.services.parking_lot_sync import sync_lesson_slot_count

    solution = (
        db.query(TimetableSolution)
        .filter(TimetableSolution.id == solution_id)
        .first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Το μάθημα-κάρτα δεν βρέθηκε")
    if lesson.term_id != solution.term_id:
        raise HTTPException(
            status_code=400,
            detail="Το μάθημα ανήκει σε άλλο σενάριο από αυτή τη λύση.",
        )
    if solution.status not in ("optimal", "feasible"):
        raise HTTPException(
            status_code=409,
            detail="Η λύση δεν είναι ενεργή (optimal/feasible) — δεν συγχρονίζεται.",
        )

    result = sync_lesson_slot_count(db, lesson_id)
    mine = next(
        (s for s in result.get("synced", []) if s["solution_id"] == solution_id),
        None,
    )
    added = mine["added"] if mine else 0
    return {
        "status": "ok",
        "solution_id": solution_id,
        "lesson_id": lesson_id,
        "added": added,
        "message": (
            f"Προστέθηκαν {added} ώρες στην παλέτα"
            if added else "Δεν έλειπε καμία ώρα — καμία αλλαγή"
        ),
    }


@router.post("/solutions/{solution_id}/undo")
def undo_last_edit(solution_id: int, db: Session = Depends(get_db)):
    """Roll back the most recent manual edit to this solution."""
    solution = (
        db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")

    entry = slot_history_svc.undo(db, solution_id)
    if not entry:
        raise HTTPException(
            status_code=400, detail="Δεν υπάρχει αλλαγή προς αναίρεση"
        )
    db.commit()
    summary = slot_history_svc.history_summary(db, solution_id)
    return {
        "status": "ok",
        "message": "Η αλλαγή αναιρέθηκε",
        "slot_id": entry.slot_id,
        "history": summary,
    }


@router.post("/solutions/{solution_id}/redo")
def redo_last_undo(solution_id: int, db: Session = Depends(get_db)):
    """Re-apply the most recent undone edit."""
    solution = (
        db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")

    entry = slot_history_svc.redo(db, solution_id)
    if not entry:
        raise HTTPException(
            status_code=400, detail="Δεν υπάρχει αλλαγή προς επανάληψη"
        )
    db.commit()
    summary = slot_history_svc.history_summary(db, solution_id)
    return {
        "status": "ok",
        "message": "Η αλλαγή επαναλήφθηκε",
        "slot_id": entry.slot_id,
        "history": summary,
    }


@router.get("/solutions/{solution_id}/history-summary")
def get_history_summary(solution_id: int, db: Session = Depends(get_db)):
    """Return how many undo / redo steps are currently available."""
    solution = (
        db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")
    return slot_history_svc.history_summary(db, solution_id)


@router.get("/solutions/{solution_id}/substitute-suggestions")
def substitute_suggestions(
    solution_id: int,
    teacher_id: int,
    day_of_week: int,
    db: Session = Depends(get_db),
):
    """Find substitute teachers + reschedule slots for an absent teacher.

    Read-only — does not modify the solution. The user reviews the
    suggestions and applies any change manually through the existing
    drag-drop UI.
    """
    solution = (
        db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")
    if day_of_week < 0 or day_of_week > 6:
        raise HTTPException(
            status_code=400, detail="day_of_week πρέπει να είναι 0-6"
        )
    try:
        return find_substitutes(db, solution_id, teacher_id, day_of_week)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
