"""Substitute teacher finder.

Use case: ένας καθηγητής δηλώνει απουσία για μια συγκεκριμένη μέρα.
Το service γυρίζει για κάθε slot του:
  - candidate substitutes (άλλοι καθηγητές που είναι ελεύθεροι ΚΑΙ
    διαθέσιμοι αυτή την ώρα), με score που ευνοεί όσους ήδη διδάσκουν
    το ίδιο μάθημα ή σε αυτή την τάξη
  - reschedule options: ελεύθερα (day, period, room) τριπλέτες στην
    ίδια εβδομάδα όπου ο ίδιος καθηγητής μπορεί να μετακινήσει το
    μάθημα (αν επιστρέψει)

Read-only — δεν μεταλλάσσει λύσεις. Ο user βλέπει τις προτάσεις και
αποφασίζει αν θα εφαρμόσει αλλαγή μέσω του υπάρχοντος drag-drop /
PUT-slot endpoint.
"""

from collections import defaultdict

from sqlalchemy.orm import Session, joinedload

from backend.models import (
    Lesson,
    Period,
    SchoolSettings,
    StudentClassEnrollment,
    Teacher,
    TeacherAvailability,
    TimetableSlot,
)


def find_substitutes(
    db: Session,
    solution_id: int,
    teacher_id: int,
    day_of_week: int,
) -> dict:
    """Build the substitute suggestion bundle for one teacher on one day.

    Returns:
        {
            "affected_slots": [
                {
                    "slot_id": int,
                    "period_id": int,
                    "period_name": str,
                    "lesson_id": int,
                    "subject_name": str,
                    "class_name": str,
                    "classroom_name": str,
                    "candidates": [
                        {"teacher_id", "name", "score", "reasons": [...]}
                    ],
                    "reschedule_options": [
                        {"day_of_week", "period_id", "period_name", "classroom_id"}
                    ],
                },
                ...
            ],
            "stats": {"affected_count": int, "with_candidates": int}
        }
    """
    target = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not target:
        raise ValueError(f"Δεν βρέθηκε καθηγητής id={teacher_id}")

    settings = db.query(SchoolSettings).first()
    days_per_week = settings.days_per_week if settings else 5

    affected = (
        db.query(TimetableSlot)
        .options(
            joinedload(TimetableSlot.lesson).joinedload(Lesson.subject),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.school_class),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.teacher),
            joinedload(TimetableSlot.classroom),
            joinedload(TimetableSlot.period),
        )
        .join(Lesson)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.day_of_week == day_of_week,
            TimetableSlot.is_unplaced == False,  # noqa: E712
            Lesson.teacher_id == teacher_id,
        )
        .all()
    )

    if not affected:
        return {
            "affected_slots": [],
            "stats": {"affected_count": 0, "with_candidates": 0},
        }

    # Pre-load auxiliary data once
    all_solution_slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .all()
    )
    all_teachers = db.query(Teacher).filter(Teacher.id != teacher_id).all()
    all_lessons = db.query(Lesson).all()
    teacher_unavail = (
        db.query(TeacherAvailability)
        .filter(TeacherAvailability.status == "unavailable")
        .all()
    )
    periods = (
        db.query(Period)
        .filter(Period.is_break == False)  # noqa: E712
        .order_by(Period.sort_order)
        .all()
    )

    unavail_by_teacher: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for ua in teacher_unavail:
        unavail_by_teacher[ua.teacher_id].add((ua.day_of_week, ua.period_id))

    # Map (day, period_id, teacher_id) → True if teaching elsewhere
    busy_teacher: set[tuple[int, int, int]] = set()
    busy_class: set[tuple[int, int, int]] = set()
    busy_room: set[tuple[int, int, int]] = set()
    for s in all_solution_slots:
        busy_teacher.add((s.day_of_week, s.period_id, s.lesson.teacher_id))
        busy_class.add((s.day_of_week, s.period_id, s.lesson.class_id))
        busy_room.add((s.day_of_week, s.period_id, s.classroom_id))

    # Same-subject and same-class teaching profile of every other teacher
    teaches_subject: dict[int, set[int]] = defaultdict(set)
    teaches_class: dict[int, set[int]] = defaultdict(set)
    for l in all_lessons:
        teaches_subject[l.teacher_id].add(l.subject_id)
        teaches_class[l.teacher_id].add(l.class_id)

    affected_payload: list[dict] = []
    with_candidates = 0
    for slot in affected:
        lesson = slot.lesson
        candidates = _candidates_for_slot(
            slot=slot,
            other_teachers=all_teachers,
            day=day_of_week,
            unavail_by_teacher=unavail_by_teacher,
            busy_teacher=busy_teacher,
            teaches_subject=teaches_subject,
            teaches_class=teaches_class,
        )
        reschedule = _reschedule_options(
            slot=slot,
            lesson=lesson,
            absent_teacher_id=teacher_id,
            day_to_skip=day_of_week,
            days_per_week=days_per_week,
            periods=periods,
            unavail_by_teacher=unavail_by_teacher,
            busy_teacher=busy_teacher,
            busy_class=busy_class,
            busy_room=busy_room,
        )

        if candidates:
            with_candidates += 1

        affected_payload.append(
            {
                "slot_id": slot.id,
                "period_id": slot.period_id,
                "period_name": slot.period.name if slot.period else None,
                "lesson_id": lesson.id,
                "subject_name": lesson.subject.name if lesson.subject else None,
                "class_name": lesson.school_class.name if lesson.school_class else None,
                "classroom_name": slot.classroom.name if slot.classroom else None,
                "candidates": candidates,
                "reschedule_options": reschedule,
            }
        )

    return {
        "affected_slots": affected_payload,
        "stats": {
            "affected_count": len(affected),
            "with_candidates": with_candidates,
        },
    }


def _candidates_for_slot(
    slot: TimetableSlot,
    other_teachers: list[Teacher],
    day: int,
    unavail_by_teacher: dict[int, set[tuple[int, int]]],
    busy_teacher: set[tuple[int, int, int]],
    teaches_subject: dict[int, set[int]],
    teaches_class: dict[int, set[int]],
) -> list[dict]:
    """Rank teachers eligible to step in for this exact slot.

    Score:
      +50 already teaches this subject
      +30 already teaches this class
      +10 has the same max-periods-per-day cap or higher
    """
    p_id = slot.period_id
    subject_id = slot.lesson.subject_id
    class_id = slot.lesson.class_id

    out: list[dict] = []
    for t in other_teachers:
        # Hard skips
        if (day, p_id) in unavail_by_teacher.get(t.id, set()):
            continue
        if (day, p_id, t.id) in busy_teacher:
            continue

        score = 0
        reasons: list[str] = []

        if subject_id in teaches_subject.get(t.id, set()):
            score += 50
            reasons.append("διδάσκει το ίδιο μάθημα")
        if class_id in teaches_class.get(t.id, set()):
            score += 30
            reasons.append("διδάσκει στο ίδιο τμήμα")

        if not reasons:
            reasons.append("ελεύθερος εκείνη την ώρα")

        out.append(
            {
                "teacher_id": t.id,
                "name": t.name,
                "short_name": t.short_name,
                "score": score,
                "reasons": reasons,
            }
        )

    out.sort(key=lambda c: (-c["score"], c["name"]))
    return out


def _reschedule_options(
    slot: TimetableSlot,
    lesson: Lesson,
    absent_teacher_id: int,
    day_to_skip: int,
    days_per_week: int,
    periods: list[Period],
    unavail_by_teacher: dict[int, set[tuple[int, int]]],
    busy_teacher: set[tuple[int, int, int]],
    busy_class: set[tuple[int, int, int]],
    busy_room: set[tuple[int, int, int]],
) -> list[dict]:
    """Find day/period combos in the same week where the original
    teacher could host the lesson if they return another day."""
    options: list[dict] = []
    classroom_id = slot.classroom_id

    for d in range(days_per_week):
        if d == day_to_skip:
            continue
        for p in periods:
            # Teacher availability
            if (d, p.id) in unavail_by_teacher.get(absent_teacher_id, set()):
                continue
            # Conflicts on the original room/class/teacher (excluding the
            # current slot which we're imagining moved)
            if (d, p.id, absent_teacher_id) in busy_teacher:
                continue
            if (d, p.id, lesson.class_id) in busy_class:
                continue
            if classroom_id and (d, p.id, classroom_id) in busy_room:
                continue
            options.append(
                {
                    "day_of_week": d,
                    "period_id": p.id,
                    "period_name": p.name,
                    "classroom_id": classroom_id,
                }
            )

    return options
