"""Manual slot-placement helpers: classroom resolution + conflict checks.

Extracted verbatim from routers/solver.py to keep the update_solution_slot
endpoint thin and readable. Behaviour is unchanged — these are the same
checks the drag-drop editor has always run (teacher / class / room /
availability / H7 shared-student), covered by the solver test-suite.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import (
    Classroom,
    Lesson,
    Period,
    SchoolSettings,
    StudentAvailability,
    StudentClassEnrollment,
    TeacherAvailability,
    TimetableSlot,
)


def pick_default_classroom(
    db: Session,
    lesson: Lesson,
    exclude_room_ids: set[int] | None = None,
) -> int | None:
    """Choose a sensible classroom for a manual placement when the
    drag-drop UI didn't supply one.

    Order of preference:
      1. The lesson's own classroom_id, if set
      2. First room whose type matches the subject's special_room_type
         (lab / gym / computer_lab) when the subject requires one
      3. First "regular" room
      4. First room of any type

    Rooms in `exclude_room_ids` are skipped (used when retrying after a
    classroom conflict).
    """
    excluded = exclude_room_ids or set()

    # 1) Lesson-pinned room
    if lesson.classroom_id and lesson.classroom_id not in excluded:
        return lesson.classroom_id

    rooms = db.query(Classroom).all()

    # 2) Special-room match (lab/gym/etc.)
    if lesson.subject and lesson.subject.requires_special_room:
        special = lesson.subject.special_room_type
        for r in rooms:
            if r.id in excluded:
                continue
            if r.room_type == special:
                return r.id
        return None  # subject demands special room — no fallback

    # 3) Regular room
    for r in rooms:
        if r.id in excluded:
            continue
        if (r.room_type or "regular") == "regular":
            return r.id

    # 4) Any room
    for r in rooms:
        if r.id not in excluded:
            return r.id

    return None


def busy_room_ids(
    db: Session,
    solution_id: int,
    day_of_week: int,
    period_id: int,
    exclude_slot_id: int,
) -> set[int]:
    """Set of classroom_ids already occupied at this exact (day, period)
    in this solution, excluding the slot being moved."""
    rows = (
        db.query(TimetableSlot.classroom_id)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.day_of_week == day_of_week,
            TimetableSlot.period_id == period_id,
            TimetableSlot.id != exclude_slot_id,
            TimetableSlot.classroom_id.isnot(None),
        )
        .all()
    )
    return {r[0] for r in rows}


def resolve_and_validate_target_room(db: Session, slot: TimetableSlot, data) -> int:
    """Resolve the target classroom and run every conflict check for a
    manual slot move. Returns the chosen classroom_id, or raises
    HTTPException(400) on the first conflict.

    `data` is a TimetableSlotUpdate (day_of_week, period_id, classroom_id).
    """
    solution_id = slot.solution_id
    slot_id = slot.id
    # Η διαθεσιμότητα είναι scenario-scoped (Terms Phase 1): οι έλεγχοι 4/5
    # πρέπει να κοιτούν ΜΟΝΟ το σενάριο της λύσης, αλλιώς κώλυμα δηλωμένο σε
    # άλλο σενάριο μπλοκάρει λάθος τη μετακίνηση (ψευδές 400 στο drag&drop).
    solution_term_id = slot.solution.term_id if slot.solution else None

    # Resolve a target classroom up front. Parking-lot slots have
    # classroom_id=NULL; if the caller didn't provide one in the body
    # (the drag-drop UI doesn't ask the user), fall back to the lesson's
    # preferred classroom_id, then to the first room of the required type,
    # then to any room. Avoids the dead end where a parking-lot drop 400s.
    if data.classroom_id is not None:
        target_room = data.classroom_id
    elif slot.classroom_id is not None:
        target_room = slot.classroom_id
    else:
        target_room = pick_default_classroom(db, slot.lesson)

    if target_room is None:
        raise HTTPException(
            status_code=400,
            detail="Δεν υπάρχει διαθέσιμη αίθουσα για αυτό το μάθημα.",
        )

    conflict_query = (
        db.query(TimetableSlot)
        .join(Lesson)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.day_of_week == data.day_of_week,
            TimetableSlot.period_id == data.period_id,
            TimetableSlot.id != slot_id,
        )
    )

    # 1. Teacher conflict
    if slot.lesson.teacher_id:
        if conflict_query.filter(Lesson.teacher_id == slot.lesson.teacher_id).first():
            raise HTTPException(status_code=400, detail="Ο καθηγητής διδάσκει ήδη σε άλλη τάξη αυτή τη μέρα/ώρα.")

    # 2. Class conflict
    if slot.lesson.class_id:
        if conflict_query.filter(Lesson.class_id == slot.lesson.class_id).first():
            raise HTTPException(status_code=400, detail="Η συγκεκριμένη τάξη κάνει ήδη άλλο μάθημα αυτή τη μέρα/ώρα.")

    # 3. Classroom conflict. Ρητό classroom_id στο body σημαίνει «θέλω ΑΥΤΗ
    # την αίθουσα», οπότε το conflict παραμένει σκληρό σφάλμα. Χωρίς ρητή
    # επιλογή (το drag&drop στέλνει μόνο μέρα/ώρα) η κατειλημμένη αίθουσα δεν
    # είναι αδιέξοδο: δοκιμάζουμε οποιαδήποτε άλλη ελεύθερη — ισχύει και για
    # ήδη τοποθετημένες κάρτες, όχι μόνο για parking-lot (classroom_id NULL).
    room_conflict = conflict_query.filter(TimetableSlot.classroom_id == target_room).first()
    if room_conflict and data.classroom_id is not None:
        raise HTTPException(status_code=400, detail="Η αίθουσα είναι κατειλημμένη αυτή τη μέρα/ώρα.")
    if room_conflict:
        target_room = pick_default_classroom(
            db, slot.lesson,
            exclude_room_ids=busy_room_ids(db, solution_id, data.day_of_week, data.period_id, slot_id),
        )
        if target_room is None:
            raise HTTPException(status_code=400, detail="Όλες οι αίθουσες είναι κατειλημμένες αυτή τη μέρα/ώρα.")

    # 4. Teacher availability (scoped στο σενάριο της λύσης)
    if slot.lesson.teacher_id:
        teacher_unav_q = (
            db.query(TeacherAvailability)
            .filter(
                TeacherAvailability.teacher_id == slot.lesson.teacher_id,
                TeacherAvailability.day_of_week == data.day_of_week,
                TeacherAvailability.period_id == data.period_id,
                TeacherAvailability.status == "unavailable",
            )
        )
        if solution_term_id is not None:
            teacher_unav_q = teacher_unav_q.filter(
                TeacherAvailability.term_id == solution_term_id
            )
        teacher_unav = teacher_unav_q.first()
        if teacher_unav:
            raise HTTPException(status_code=400, detail="Ο καθηγητής έχει δηλώσει κώλυμα (Μη Διαθέσιμος) αυτή τη μέρα και ώρα.")

    # 5. Student availability
    enrolled_student_ids: list[int] = []
    if slot.lesson.class_id:
        enrolled_student_ids = [
            e.student_id for e in db.query(StudentClassEnrollment.student_id)
            .filter(StudentClassEnrollment.class_id == slot.lesson.class_id)
            .all()
        ]
        if enrolled_student_ids:
            student_unav_q = (
                db.query(StudentAvailability)
                .filter(
                    StudentAvailability.student_id.in_(enrolled_student_ids),
                    StudentAvailability.day_of_week == data.day_of_week,
                    StudentAvailability.period_id == data.period_id,
                    StudentAvailability.status == "unavailable",
                )
            )
            if solution_term_id is not None:
                student_unav_q = student_unav_q.filter(
                    StudentAvailability.term_id == solution_term_id
                )
            student_unav = student_unav_q.first()
            if student_unav:
                raise HTTPException(status_code=400, detail="Ένας ή περισσότεροι μαθητές του τμήματος έχουν δηλώσει κώλυμα αυτή τη μέρα και ώρα.")

    # 6. Shared-student conflict (H7) — two different classes that share a
    # student must not run at the same (day, period). The solver enforces
    # this when generating; the manual editor bypasses the solver, so we
    # re-check it here (different teacher AND room would pass every other
    # check). ΣΥΓΧΡΟΝΙΣΜΟΣ: το build_placement_map παρακάτω καθρεφτίζει
    # ΟΛΟΥΣ αυτούς τους ελέγχους σε bulk — αν προστεθεί έλεγχος εδώ,
    # πρόσθεσέ τον και εκεί (τα agreement tests το κλειδώνουν).
    if enrolled_student_ids:
        other_class_ids = {
            cid for (cid,) in conflict_query
            .with_entities(Lesson.class_id)
            .filter(Lesson.class_id.isnot(None), Lesson.class_id != slot.lesson.class_id)
            .all()
        }
        if other_class_ids:
            clash = (
                db.query(StudentClassEnrollment.student_id)
                .filter(
                    StudentClassEnrollment.class_id.in_(other_class_ids),
                    StudentClassEnrollment.student_id.in_(enrolled_student_ids),
                )
                .first()
            )
            if clash:
                raise HTTPException(
                    status_code=400,
                    detail="Κοινός μαθητής με άλλο μάθημα αυτή τη μέρα/ώρα "
                           "(θα έπρεπε να είναι σε δύο τμήματα ταυτόχρονα).",
                )

    return target_room


def build_placement_map(db: Session, slot: TimetableSlot) -> dict:
    """Advisory per-cell legality map for dragging `slot` across the grid.

    Για κάθε (μέρα, διδακτική ώρα) απαντά αν το slot μπορεί να πέσει εκεί
    και γιατί όχι — ίδιοι έλεγχοι με το resolve_and_validate_target_room
    (τον enforcer του drop), υπολογισμένοι μαζικά με προφορτωμένο context
    αντί για per-cell queries. Read-only: δεν αγγίζει τίποτα.

    Συμφωνία με τον enforcer: κλειδωμένη από τα agreement tests στο
    tests/test_placement_map.py — κάθε «ok» κελί δέχεται το PUT, κάθε
    «μπλοκαρισμένο» απορρίπτεται. Αν αλλάξεις έλεγχο στο ένα, άλλαξε
    και το άλλο.
    """
    lesson = slot.lesson
    solution_id = slot.solution_id
    term_id = slot.solution.term_id if slot.solution else None

    settings = db.query(SchoolSettings).first()
    days_count = settings.days_per_week if settings else 5
    periods = (
        db.query(Period)
        .filter(Period.is_break == False)  # noqa: E712
        .order_by(Period.sort_order)
        .all()
    )

    # Όλα τα ΑΛΛΑ τοποθετημένα slots της λύσης, με ταυτότητα μαθήματος.
    others = (
        db.query(
            TimetableSlot.day_of_week,
            TimetableSlot.period_id,
            TimetableSlot.classroom_id,
            Lesson.teacher_id,
            Lesson.class_id,
        )
        .join(Lesson)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.id != slot.id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .all()
    )

    teacher_busy: set = set()
    class_busy: set = set()
    rooms_busy: dict = {}
    classes_at: dict = {}
    for day, pid, room_id, t_id, c_id in others:
        cell = (day, pid)
        if lesson.teacher_id and t_id == lesson.teacher_id:
            teacher_busy.add(cell)
        if lesson.class_id and c_id == lesson.class_id:
            class_busy.add(cell)
        if room_id is not None:
            rooms_busy.setdefault(cell, set()).add(room_id)
        if c_id is not None and c_id != lesson.class_id:
            classes_at.setdefault(cell, set()).add(c_id)

    # Κώλυμα καθηγητή (scoped στο σενάριο της λύσης — βλ. check 4).
    teacher_unav: set = set()
    if lesson.teacher_id:
        q = db.query(
            TeacherAvailability.day_of_week, TeacherAvailability.period_id
        ).filter(
            TeacherAvailability.teacher_id == lesson.teacher_id,
            TeacherAvailability.status == "unavailable",
        )
        if term_id is not None:
            q = q.filter(TeacherAvailability.term_id == term_id)
        teacher_unav = {(d, p) for d, p in q.all()}

    # Κωλύματα εγγεγραμμένων μαθητών (check 5) + κοινοί μαθητές για H7.
    enrolled_student_ids: list[int] = []
    if lesson.class_id:
        enrolled_student_ids = [
            sid for (sid,) in db.query(StudentClassEnrollment.student_id)
            .filter(StudentClassEnrollment.class_id == lesson.class_id)
            .all()
        ]
    student_unav: set = set()
    if enrolled_student_ids:
        q = db.query(
            StudentAvailability.day_of_week, StudentAvailability.period_id
        ).filter(
            StudentAvailability.student_id.in_(enrolled_student_ids),
            StudentAvailability.status == "unavailable",
        )
        if term_id is not None:
            q = q.filter(StudentAvailability.term_id == term_id)
        student_unav = {(d, p) for d, p in q.all()}

    shared_classes: set = set()
    if enrolled_student_ids and classes_at:
        all_other_class_ids = set().union(*classes_at.values())
        rows = (
            db.query(StudentClassEnrollment.class_id)
            .filter(
                StudentClassEnrollment.class_id.in_(all_other_class_ids),
                StudentClassEnrollment.student_id.in_(enrolled_student_ids),
            )
            .distinct()
            .all()
        )
        shared_classes = {cid for (cid,) in rows}

    # Αποδεκτές αίθουσες — καθρέφτης του pick_default_classroom:
    # μάθημα με special room απαιτεί αίθουσα του τύπου (ή τη δική του
    # καρφωμένη)· αλλιώς κάνει οποιαδήποτε (fallback «any room»).
    rooms = db.query(Classroom).all()
    if lesson.subject and lesson.subject.requires_special_room:
        acceptable_rooms = {
            r.id for r in rooms
            if r.room_type == lesson.subject.special_room_type
        }
        if lesson.classroom_id:
            acceptable_rooms.add(lesson.classroom_id)
    else:
        acceptable_rooms = {r.id for r in rooms}

    cells = []
    for day in range(days_count):
        for p in periods:
            cell = (day, p.id)
            reason = None
            if cell in teacher_busy:
                reason = "Ο καθηγητής διδάσκει ήδη εκείνη την ώρα"
            elif cell in class_busy:
                reason = "Το τμήμα έχει ήδη μάθημα εκείνη την ώρα"
            elif cell in teacher_unav:
                reason = "Κώλυμα καθηγητή"
            elif cell in student_unav:
                reason = "Κώλυμα μαθητή του τμήματος"
            elif shared_classes and (classes_at.get(cell, set()) & shared_classes):
                reason = "Κοινός μαθητής με άλλο τμήμα εκείνη την ώρα"
            elif not (acceptable_rooms - rooms_busy.get(cell, set())):
                reason = "Καμία κατάλληλη αίθουσα ελεύθερη"
            cells.append({
                "day": day,
                "period_id": p.id,
                "ok": reason is None,
                "reason": reason,
            })

    return {"slot_id": slot.id, "days": days_count, "cells": cells}
