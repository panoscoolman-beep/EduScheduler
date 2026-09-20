"""👥 Ποιοι μαθητές παρακολουθούν ΚΑΘΕ κάρτα μαθήματος.

Βάση είναι το τμήμα· από πάνω μπαίνουν οι εξαιρέσεις/προσθήκες
(`lesson_student_overrides`): «ο Χ κάνει το ένα δίωρο Φυσικής στο άλλο τμήμα».
Ό,τι ρωτά «ποιος είναι πού» (solver, συγκρούσεις στο σύρσιμο, κενά,
εκτυπώσεις, ICS) περνά από εδώ, ώστε να υπάρχει ΜΙΑ αλήθεια.

Χωρίς overrides το αποτέλεσμα είναι ακριβώς οι εγγραφές των τμημάτων.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from backend.models import Lesson, LessonStudentOverride, StudentClassEnrollment

ADD = "add"
REMOVE = "remove"


def roster_map(db: Session, lessons: list[Lesson]) -> dict[int, set[int]]:
    """{lesson_id: {student_id}} για τις δοσμένες κάρτες."""
    if not lessons:
        return {}
    class_ids = {l.class_id for l in lessons}
    by_class: dict[int, set[int]] = defaultdict(set)
    for cid, sid in (db.query(StudentClassEnrollment.class_id, StudentClassEnrollment.student_id)
                     .filter(StudentClassEnrollment.class_id.in_(class_ids)).all()):
        by_class[cid].add(sid)
    lesson_ids = [l.id for l in lessons]
    adds: dict[int, set[int]] = defaultdict(set)
    removes: dict[int, set[int]] = defaultdict(set)
    for lid, sid, mode in (db.query(LessonStudentOverride.lesson_id, LessonStudentOverride.student_id,
                                    LessonStudentOverride.mode)
                           .filter(LessonStudentOverride.lesson_id.in_(lesson_ids)).all()):
        (adds if mode == ADD else removes)[lid].add(sid)
    return {l.id: (set(by_class.get(l.class_id, ())) | adds.get(l.id, set())) - removes.get(l.id, set())
            for l in lessons}


def short_name(first_name: str, last_name: str) -> str:
    """«Ιγνάτης Μ.» — όνομα + αρχικό επιθέτου: χωράει στο πλέγμα και ξεχωρίζει
    τους συνονόματους."""
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if not first:
        return last            # χωρίς μικρό όνομα δείχνουμε το επώνυμο ολόκληρο
    return f"{first} {last[0]}." if last else first


def display_names(db: Session, lessons: list[Lesson]) -> dict[int, list[str]]:
    """{lesson_id: ["Ιγνάτης Μ.", …]} — αλφαβητικά (επώνυμο, όνομα).

    Παράγονται ΑΥΤΟΜΑΤΑ από τη λίστα της κάρτας, ώστε να μη γράφονται
    ονόματα στο χέρι στο όνομα του τμήματος."""
    from backend.models import Student

    rosters = roster_map(db, lessons)
    ids = set().union(*rosters.values()) if rosters else set()
    students = (db.query(Student).filter(Student.id.in_(ids))
                .order_by(Student.last_name, Student.first_name).all()) if ids else []
    order = {s.id: i for i, s in enumerate(students)}
    label = {s.id: short_name(s.first_name, s.last_name) for s in students}
    return {lid: [label[sid] for sid in sorted(sids & set(label), key=lambda x: order[x])]
            for lid, sids in rosters.items()}


def students_of(db: Session, lesson: Lesson) -> set[int]:
    return roster_map(db, [lesson]).get(lesson.id, set())


def lessons_by_student(db: Session, lessons: list[Lesson]) -> dict[int, list[Lesson]]:
    """Αντίστροφος χάρτης: {student_id: [κάρτες που παρακολουθεί]}."""
    rosters = roster_map(db, lessons)
    out: dict[int, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        for sid in rosters.get(lesson.id, ()):
            out[sid].append(lesson)
    return out


def lesson_ids_for_student(db: Session, student_id: int, lessons: list[Lesson]) -> set[int]:
    return {lid for lid, students in roster_map(db, lessons).items() if student_id in students}


def roster_detail(db: Session, lesson: Lesson) -> list[dict]:
    """Η λίστα της κάρτας για το UI: μαθητές τμήματος (με/χωρίς εξαίρεση) +
    πρόσθετοι από αλλού, αλφαβητικά."""
    from backend.models import Student

    class_students = {sid for (sid,) in db.query(StudentClassEnrollment.student_id)
                      .filter(StudentClassEnrollment.class_id == lesson.class_id).all()}
    overrides = {sid: mode for sid, mode in
                 db.query(LessonStudentOverride.student_id, LessonStudentOverride.mode)
                 .filter(LessonStudentOverride.lesson_id == lesson.id).all()}
    ids = class_students | set(overrides)
    rows = db.query(Student).filter(Student.id.in_(ids)).all() if ids else []
    out = []
    for s in rows:
        in_class = s.id in class_students
        mode = overrides.get(s.id)
        out.append({
            "student_id": s.id,
            "name": f"{s.last_name} {s.first_name}".strip(),
            "grade": s.grade or "",
            "from_class": in_class,
            "attends": (mode != REMOVE) if in_class else (mode == ADD),
            "source": "τμήμα" if in_class else "άλλο τμήμα",
        })
    return sorted(out, key=lambda r: r["name"])


def set_roster(db: Session, lesson: Lesson, attending: list[int]) -> dict:
    """Ορίζει ΠΟΙΟΙ παρακολουθούν την κάρτα (χωρίς commit).

    Ό,τι λείπει από τους μαθητές του τμήματος γίνεται 'remove', ό,τι είναι
    εκτός τμήματος γίνεται 'add'. Αν η λίστα ταυτίζεται με το τμήμα, οι
    εξαιρέσεις καθαρίζονται εντελώς."""
    class_students = {sid for (sid,) in db.query(StudentClassEnrollment.student_id)
                      .filter(StudentClassEnrollment.class_id == lesson.class_id).all()}
    wanted = set(attending)
    removes = class_students - wanted
    adds = wanted - class_students
    db.query(LessonStudentOverride).filter(LessonStudentOverride.lesson_id == lesson.id).delete()
    for sid in sorted(removes):
        db.add(LessonStudentOverride(lesson_id=lesson.id, student_id=sid, mode=REMOVE))
    for sid in sorted(adds):
        db.add(LessonStudentOverride(lesson_id=lesson.id, student_id=sid, mode=ADD))
    db.flush()
    return {"attending": len(wanted), "excluded": len(removes), "added": len(adds)}


def roster_conflicts(db: Session, lesson: Lesson, attending: list[int]) -> list[dict]:
    """Ποιοι από τους νέους μαθητές έχουν ήδη άλλο μάθημα στις ώρες της κάρτας.

    Δεν μπλοκάρει: ο χρήστης μπορεί να ξέρει κάτι που δεν ξέρει το σύστημα
    (π.χ. θα μετακινήσει την ώρα αμέσως μετά) — ο router ζητά επιβεβαίωση."""
    from backend.models import Period, Student, TimetableSlot, TimetableSolution
    from backend.services import placement_conflicts as pc

    newcomers = set(attending) - students_of(db, lesson)
    if not newcomers:
        return []
    solutions = {s.id: s.name for s in db.query(TimetableSolution).filter(
        TimetableSolution.term_id == lesson.term_id, TimetableSolution.archived_at.is_(None)).all()}
    if not solutions:
        return []
    mine = db.query(TimetableSlot).filter(
        TimetableSlot.lesson_id == lesson.id, TimetableSlot.solution_id.in_(solutions),
        TimetableSlot.is_unplaced == False).all()  # noqa: E712
    if not mine:
        return []
    cells = {(s.solution_id, s.day_of_week, s.period_id) for s in mine}
    others = (db.query(TimetableSlot, Lesson)
              .join(Lesson, Lesson.id == TimetableSlot.lesson_id)
              .filter(TimetableSlot.solution_id.in_(solutions),
                      TimetableSlot.lesson_id != lesson.id,
                      TimetableSlot.is_unplaced == False).all())  # noqa: E712
    rosters = roster_map(db, [l for _s, l in others])
    periods = {p.id: p for p in db.query(Period).all()}
    names = {s.id: pc.student_display(s) for s in db.query(Student).filter(Student.id.in_(newcomers)).all()}
    out = []
    for slot, other in others:
        if (slot.solution_id, slot.day_of_week, slot.period_id) not in cells:
            continue
        for sid in sorted(newcomers & rosters.get(other.id, set())):
            subject = other.subject.name if other.subject else "μάθημα"
            klass = other.school_class.name if other.school_class else ""
            out.append({
                "student_id": sid,
                "student": names.get(sid, "μαθητής"),
                "when": pc.cell_label(slot.day_of_week, periods.get(slot.period_id)),
                "solution": solutions.get(slot.solution_id, ""),
                "clash": f"{subject} ({klass})" if klass else subject,
            })
    return out


def conflicts_message(conflicts: list[dict]) -> str:
    first = "; ".join(f"{c['student']} — {c['when']}: {c['clash']}" for c in conflicts[:4])
    more = f" και άλλα {len(conflicts) - 4}" if len(conflicts) > 4 else ""
    return (f"{len(conflicts)} επικαλύψεις με ώρες που ήδη έχουν οι μαθητές: {first}{more}. "
            "Αν συνεχίσεις, μπαίνουν έτσι κι αλλιώς (θα φαίνονται ως σύγκρουση στο πρόγραμμα).")
