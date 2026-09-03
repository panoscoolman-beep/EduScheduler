"""Manual slot-placement helpers: classroom resolution + conflict checks.

Extracted verbatim from routers/solver.py to keep the update_solution_slot
endpoint thin and readable. Behaviour is unchanged — these are the same
checks the drag-drop editor has always run (teacher / class / room /
availability / H7 shared-student), covered by the solver test-suite.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.models import (
    Classroom,
    Lesson,
    Period,
    SchoolClass,
    SchoolSettings,
    Student,
    StudentAvailability,
    StudentClassEnrollment,
    Subject,
    Teacher,
    TeacherAvailability,
    TimetableSlot,
)
from backend.services import placement_conflicts as pc
from backend.services.placement_conflicts import PlacementConflict


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
    extra_exclude_slot_id: int | None = None,
) -> set[int]:
    """Set of classroom_ids already occupied at this exact (day, period)
    in this solution, excluding the slot being moved — and, on a swap,
    the counterpart slot that is vacating the cell at the same time."""
    q = (
        db.query(TimetableSlot.classroom_id)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.day_of_week == day_of_week,
            TimetableSlot.period_id == period_id,
            TimetableSlot.id != exclude_slot_id,
            TimetableSlot.classroom_id.isnot(None),
        )
    )
    if extra_exclude_slot_id is not None:
        q = q.filter(TimetableSlot.id != extra_exclude_slot_id)
    return {r[0] for r in q.all()}


def resolve_and_validate_target_room(
    db: Session,
    slot: TimetableSlot,
    data,
    extra_exclude_slot_id: int | None = None,
) -> int:
    """Resolve the target classroom and run every conflict check for a
    manual slot move. Returns the chosen classroom_id, or raises
    HTTPException(400) on the first conflict.

    `data` is a TimetableSlotUpdate (day_of_week, period_id, classroom_id).
    `extra_exclude_slot_id`: σε ανταλλαγή (swap) ο έλεγχος του Α στο κελί
    του Β πρέπει να αγνοήσει τον Β (αδειάζει ταυτόχρονα) — και αντίστροφα.
    """
    solution_id = slot.solution_id
    slot_id = slot.id
    # Η διαθεσιμότητα είναι scenario-scoped (Terms Phase 1): οι έλεγχοι 4/5
    # πρέπει να κοιτούν ΜΟΝΟ το σενάριο της λύσης, αλλιώς κώλυμα δηλωμένο σε
    # άλλο σενάριο μπλοκάρει λάθος τη μετακίνηση (ψευδές 400 στο drag&drop).
    solution_term_id = slot.solution.term_id if slot.solution else None

    # Ονομαστικά μηνύματα: πού (μέρα/ώρα) και ποιος/τι μπλοκάρει. Το period
    # φορτώνεται μία φορά· τα ονόματα του slot που φταίει από describe_slot.
    period = db.query(Period).filter(Period.id == data.period_id).first()
    where = pc.cell_label(data.day_of_week, period)
    me = pc.describe_slot(db, slot)
    base = {
        "day_of_week": data.day_of_week,
        "period_id": data.period_id,
        "where": where,
        "moving_slot_id": slot_id,
    }

    def blocked_by(code: str, message: str, other: TimetableSlot | None = None, **extra):
        info = pc.describe_slot(db, other) if other is not None else {}
        return PlacementConflict(
            code, message,
            blocking_slot_id=info.get("slot_id"),
            blocking=info or None,
            **base, **extra,
        )

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
        raise blocked_by(
            pc.NO_ROOM,
            "Δεν υπάρχει διαθέσιμη αίθουσα για αυτό το μάθημα"
            + (f" (χρειάζεται αίθουσα τύπου «{slot.lesson.subject.special_room_type}»)."
               if slot.lesson.subject and slot.lesson.subject.requires_special_room else "."),
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
    if extra_exclude_slot_id is not None:
        conflict_query = conflict_query.filter(
            TimetableSlot.id != extra_exclude_slot_id
        )

    # 1. Teacher conflict
    if slot.lesson.teacher_id:
        other = conflict_query.filter(Lesson.teacher_id == slot.lesson.teacher_id).first()
        if other:
            info = pc.describe_slot(db, other)
            raise blocked_by(
                pc.TEACHER_BUSY,
                f"Ο καθηγητής {me['teacher'] or ''} διδάσκει ήδη "
                f"{pc.lesson_phrase(info)} — {where}.",
                other,
            )

    # 2. Class conflict
    if slot.lesson.class_id:
        other = conflict_query.filter(Lesson.class_id == slot.lesson.class_id).first()
        if other:
            info = pc.describe_slot(db, other)
            raise blocked_by(
                pc.CLASS_BUSY,
                f"Το τμήμα {me['class_name'] or ''} κάνει ήδη {info['subject'] or 'άλλο μάθημα'}"
                + (f" με {info['teacher']}" if info['teacher'] else "")
                + (f" (αίθ. {info['classroom']})" if info['classroom'] else "")
                + f" — {where}.",
                other,
            )

    # 3. Classroom conflict. Ρητό classroom_id στο body σημαίνει «θέλω ΑΥΤΗ
    # την αίθουσα», οπότε το conflict παραμένει σκληρό σφάλμα. Χωρίς ρητή
    # επιλογή (το drag&drop στέλνει μόνο μέρα/ώρα) η κατειλημμένη αίθουσα δεν
    # είναι αδιέξοδο: δοκιμάζουμε οποιαδήποτε άλλη ελεύθερη — ισχύει και για
    # ήδη τοποθετημένες κάρτες, όχι μόνο για parking-lot (classroom_id NULL).
    room_conflict = conflict_query.filter(TimetableSlot.classroom_id == target_room).first()
    if room_conflict and data.classroom_id is not None:
        info = pc.describe_slot(db, room_conflict)
        raise blocked_by(
            pc.ROOM_BUSY,
            f"Η αίθουσα {info['classroom'] or ''} είναι κατειλημμένη — "
            f"{info['subject']}"
            + (f" στο {info['class_name']}" if info['class_name'] else "")
            + (f" με {info['teacher']}" if info['teacher'] else "")
            + f", {where}.",
            room_conflict,
        )
    if room_conflict:
        busy = busy_room_ids(
            db, solution_id, data.day_of_week, data.period_id,
            slot_id, extra_exclude_slot_id,
        )
        target_room = pick_default_classroom(db, slot.lesson, exclude_room_ids=busy)
        if target_room is None:
            occupants = _room_occupants(db, conflict_query)
            raise blocked_by(
                pc.ROOMS_EXHAUSTED,
                f"Όλες οι αίθουσες είναι κατειλημμένες {where}"
                + (f": {pc.join_names(occupants)}" if occupants else "")
                + ".",
                room_conflict,
            )

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
        if teacher_unav_q.first():
            raise blocked_by(
                pc.TEACHER_UNAVAILABLE,
                f"Ο καθηγητής {me['teacher'] or ''} έχει δηλώσει κώλυμα "
                f"(Μη Διαθέσιμος) {where}.",
                teacher_id=slot.lesson.teacher_id,
            )

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
                db.query(StudentAvailability.student_id)
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
            unav_ids = [sid for (sid,) in student_unav_q.all()]
            if unav_ids:
                names = _student_names(db, unav_ids)
                many = len(names) > 1
                raise blocked_by(
                    pc.STUDENT_UNAVAILABLE,
                    (f"Οι μαθητές {pc.join_names(names)} του τμήματος {me['class_name']} έχουν"
                     if many else
                     f"Ο μαθητής {pc.join_names(names)} του τμήματος {me['class_name']} έχει")
                    + f" δηλώσει κώλυμα {where}.",
                    student_ids=unav_ids,
                )

    # 6. Shared-student conflict (H7) — two different classes that share a
    # student must not run at the same (day, period). The solver enforces
    # this when generating; the manual editor bypasses the solver, so we
    # re-check it here (different teacher AND room would pass every other
    # check). ΣΥΓΧΡΟΝΙΣΜΟΣ: το build_placement_map παρακάτω καθρεφτίζει
    # ΟΛΟΥΣ αυτούς τους ελέγχους σε bulk — αν προστεθεί έλεγχος εδώ,
    # πρόσθεσέ τον και εκεί (τα agreement tests το κλειδώνουν).
    if enrolled_student_ids:
        other_slots_by_class = {
            s.lesson.class_id: s
            for s in conflict_query
            .filter(Lesson.class_id.isnot(None), Lesson.class_id != slot.lesson.class_id)
            .all()
        }
        if other_slots_by_class:
            clash = (
                db.query(StudentClassEnrollment.student_id, StudentClassEnrollment.class_id)
                .filter(
                    StudentClassEnrollment.class_id.in_(other_slots_by_class.keys()),
                    StudentClassEnrollment.student_id.in_(enrolled_student_ids),
                )
                .first()
            )
            if clash:
                student_id, other_class_id = clash
                other = other_slots_by_class[other_class_id]
                info = pc.describe_slot(db, other)
                student = db.query(Student).filter(Student.id == student_id).first()
                raise blocked_by(
                    pc.SHARED_STUDENT,
                    f"Κοινός μαθητής: ο/η {pc.student_display(student)} είναι και στο "
                    f"{info['class_name']}, που έχει {info['subject']}"
                    + (f" με {info['teacher']}" if info['teacher'] else "")
                    + f" {where} (θα έπρεπε να είναι σε δύο τμήματα ταυτόχρονα).",
                    other,
                    student_id=student_id,
                )

    return target_room


def _student_names(db: Session, student_ids: list[int]) -> list[str]:
    rows = (
        db.query(Student)
        .filter(Student.id.in_(student_ids))
        .order_by(Student.last_name, Student.first_name)
        .all()
    )
    return [pc.student_display(s) for s in rows]


def _room_occupants(db: Session, conflict_query) -> list[str]:
    """«R1: Β2, L1: Γ3» — ποιος κρατά κάθε αίθουσα στο κελί-στόχο."""
    out = []
    for s in conflict_query.filter(TimetableSlot.classroom_id.isnot(None)).all():
        info = pc.describe_slot(db, s)
        who = info["class_name"] or info["subject"] or "μάθημα"
        out.append(f"{info['classroom']}: {who}")
    return out


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

    # Ονόματα για ονομαστικές αιτίες — 4 μικρά bulk queries, όχι per-cell.
    teacher_names = {t.id: t.name for t in db.query(Teacher.id, Teacher.name).all()}
    class_names = {c.id: c.short_name for c in db.query(SchoolClass.id, SchoolClass.short_name).all()}
    subject_names = {x.id: x.name for x in db.query(Subject.id, Subject.name).all()}
    rooms = db.query(Classroom).all()
    room_names = {r.id: r.name for r in rooms}
    my_teacher = teacher_names.get(lesson.teacher_id, "")
    my_class = class_names.get(lesson.class_id, "")

    # Όλα τα ΑΛΛΑ τοποθετημένα slots της λύσης, με ταυτότητα μαθήματος.
    others = (
        db.query(
            TimetableSlot.id,
            TimetableSlot.day_of_week,
            TimetableSlot.period_id,
            TimetableSlot.classroom_id,
            Lesson.teacher_id,
            Lesson.class_id,
            Lesson.subject_id,
        )
        .join(Lesson)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.id != slot.id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .all()
    )

    def _who(sid, room_id, t_id, c_id, subj_id) -> dict:
        return {
            "slot_id": sid,
            "subject": subject_names.get(subj_id, ""),
            "teacher": teacher_names.get(t_id, ""),
            "class_name": class_names.get(c_id, ""),
            "classroom": room_names.get(room_id, "") if room_id is not None else "",
        }

    teacher_busy: dict = {}   # cell -> describe dict of the blocking slot
    class_busy: dict = {}
    rooms_busy: dict = {}     # cell -> {room_id}
    room_holder: dict = {}    # cell -> {room_id: class short_name}
    classes_at: dict = {}     # cell -> {class_id}
    slot_of_class_at: dict = {}  # (cell, class_id) -> describe dict
    for sid, day, pid, room_id, t_id, c_id, subj_id in others:
        cell = (day, pid)
        info = _who(sid, room_id, t_id, c_id, subj_id)
        if lesson.teacher_id and t_id == lesson.teacher_id:
            teacher_busy.setdefault(cell, info)
        if lesson.class_id and c_id == lesson.class_id:
            class_busy.setdefault(cell, info)
        if room_id is not None:
            rooms_busy.setdefault(cell, set()).add(room_id)
            room_holder.setdefault(cell, {})[room_id] = info["class_name"] or info["subject"]
        if c_id is not None and c_id != lesson.class_id:
            classes_at.setdefault(cell, set()).add(c_id)
            slot_of_class_at.setdefault((cell, c_id), info)

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
    student_names: dict = {}
    if enrolled_student_ids:
        student_names = {
            st.id: pc.student_display(st)
            for st in db.query(Student).filter(Student.id.in_(enrolled_student_ids)).all()
        }
    student_unav: dict = {}   # cell -> [student_id]
    if enrolled_student_ids:
        q = db.query(
            StudentAvailability.day_of_week,
            StudentAvailability.period_id,
            StudentAvailability.student_id,
        ).filter(
            StudentAvailability.student_id.in_(enrolled_student_ids),
            StudentAvailability.status == "unavailable",
        )
        if term_id is not None:
            q = q.filter(StudentAvailability.term_id == term_id)
        for d, p, sid in q.all():
            student_unav.setdefault((d, p), []).append(sid)

    shared_by_class: dict = {}  # other class_id -> [student_id] κοινοί
    if enrolled_student_ids and classes_at:
        all_other_class_ids = set().union(*classes_at.values())
        rows = (
            db.query(StudentClassEnrollment.class_id, StudentClassEnrollment.student_id)
            .filter(
                StudentClassEnrollment.class_id.in_(all_other_class_ids),
                StudentClassEnrollment.student_id.in_(enrolled_student_ids),
            )
            .all()
        )
        for cid, sid in rows:
            shared_by_class.setdefault(cid, []).append(sid)

    # Αποδεκτές αίθουσες — καθρέφτης του pick_default_classroom:
    # μάθημα με special room απαιτεί αίθουσα του τύπου (ή τη δική του
    # καρφωμένη)· αλλιώς κάνει οποιαδήποτε (fallback «any room»).
    if lesson.subject and lesson.subject.requires_special_room:
        acceptable_rooms = {
            r.id for r in rooms
            if r.room_type == lesson.subject.special_room_type
        }
        if lesson.classroom_id:
            acceptable_rooms.add(lesson.classroom_id)
    else:
        acceptable_rooms = {r.id for r in rooms}

    def _names(ids: list[int]) -> str:
        return pc.join_names([student_names.get(i, "") for i in ids])

    cells = []
    for day in range(days_count):
        for p in periods:
            cell = (day, p.id)
            code = reason = short = None
            blocking = None
            if cell in teacher_busy:
                b = teacher_busy[cell]
                code, blocking = pc.TEACHER_BUSY, b
                reason = f"Ο καθηγητής {my_teacher} διδάσκει ήδη {pc.lesson_phrase(b)}"
                short = f"👤 {b['class_name'] or b['subject']}"
            elif cell in class_busy:
                b = class_busy[cell]
                code, blocking = pc.CLASS_BUSY, b
                reason = f"Το τμήμα {my_class} έχει ήδη {b['subject']}" + (
                    f" με {b['teacher']}" if b['teacher'] else "")
                short = f"🏫 {b['subject']}"
            elif cell in teacher_unav:
                code = pc.TEACHER_UNAVAILABLE
                reason = f"Κώλυμα καθηγητή {my_teacher}"
                short = f"⛔ {my_teacher}"
            elif cell in student_unav:
                code = pc.STUDENT_UNAVAILABLE
                ids = student_unav[cell]
                reason = f"Κώλυμα μαθητή: {_names(ids)}"
                short = f"🎓 {_names(ids[:1])}" + (f" +{len(ids) - 1}" if len(ids) > 1 else "")
            elif shared_by_class and (classes_at.get(cell, set()) & shared_by_class.keys()):
                other_cid = next(iter(classes_at[cell] & shared_by_class.keys()))
                b = slot_of_class_at.get((cell, other_cid), {})
                sids = shared_by_class[other_cid]
                code, blocking = pc.SHARED_STUDENT, b or None
                reason = (f"Κοινός μαθητής {_names(sids)} με το {class_names.get(other_cid, '')}"
                          + (f" ({b['subject']}" + (f", {b['teacher']}" if b.get('teacher') else "") + ")"
                             if b else ""))
                short = f"👥 {class_names.get(other_cid, '')}"
            elif not (acceptable_rooms - rooms_busy.get(cell, set())):
                code = pc.ROOMS_EXHAUSTED
                holders = room_holder.get(cell, {})
                occ = [f"{room_names.get(rid, '')}: {who}" for rid, who in holders.items()
                       if rid in acceptable_rooms]
                reason = "Καμία κατάλληλη αίθουσα ελεύθερη" + (
                    f" ({pc.join_names(occ)})" if occ else "")
                short = "🚪 πλήρες"
            cells.append({
                "day": day,
                "period_id": p.id,
                "ok": reason is None,
                "reason": reason,
                "code": code,
                "short": short,
                "blocking_slot_id": blocking["slot_id"] if blocking else None,
            })

    return {"slot_id": slot.id, "days": days_count, "cells": cells}
