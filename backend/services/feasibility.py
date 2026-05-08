"""
Pre-solve feasibility check — fast arithmetic sanity tests προτού καλέσει
ο user τον CP-SAT solver που μπορεί να τρέξει 30+ δευτερόλεπτα.

Τα checks εδώ ΔΕΝ τρέχουν τον solver. Είναι O(N) αριθμητικές συγκρίσεις
ανάμεσα σε ζήτηση (πόσες ώρες χρειαζόμαστε) και προσφορά (πόσα slots έχουμε
διαθέσιμα μετά τις διαθεσιμότητες). Επιστρέφουν errors (σίγουρη αποτυχία)
και warnings (πιθανή αποτυχία ή tight schedule).
"""

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backend.models import (
    Classroom,
    Lesson,
    Period,
    SchoolClass,
    SchoolSettings,
    StudentAvailability,
    StudentClassEnrollment,
    Subject,
    Teacher,
    TeacherAvailability,
)


@dataclass
class FeasibilityReport:
    """Outcome of a pre-solve feasibility analysis."""

    feasible: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "feasible": self.feasible,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
        }


def _parse_distribution(lesson: Lesson) -> list[int]:
    """Mirror solver's _parse_distribution για consistent block counting."""
    if lesson.distribution:
        try:
            blocks = [int(v.strip()) for v in lesson.distribution.split(",") if v.strip()]
            if sum(blocks) == lesson.periods_per_week:
                return blocks
        except ValueError:
            pass
    return [1] * lesson.periods_per_week


def _lesson_label(lesson: Lesson) -> str:
    subj = lesson.subject.name if lesson.subject else "?"
    cls = lesson.school_class.name if lesson.school_class else "?"
    return f"{subj} ({cls})"


def check_feasibility(db: Session) -> FeasibilityReport:
    """Run all pre-solve checks against the current DB state."""
    report = FeasibilityReport()

    teachers = db.query(Teacher).all()
    classes = db.query(SchoolClass).all()
    classrooms = db.query(Classroom).all()
    lessons = db.query(Lesson).all()
    periods = (
        db.query(Period)
        .filter(Period.is_break == False)  # noqa: E712
        .order_by(Period.sort_order)
        .all()
    )
    subjects = db.query(Subject).all()
    settings = db.query(SchoolSettings).first()
    days_per_week = settings.days_per_week if settings else 5

    teacher_unavail = (
        db.query(TeacherAvailability)
        .filter(TeacherAvailability.status == "unavailable")
        .all()
    )
    student_unavail = (
        db.query(StudentAvailability)
        .filter(StudentAvailability.status == "unavailable")
        .all()
    )
    enrollments = db.query(StudentClassEnrollment).all()

    n_periods = len(periods)
    report.stats["days_per_week"] = days_per_week
    report.stats["periods_per_day"] = n_periods
    report.stats["total_lessons"] = len(lessons)
    report.stats["total_teachers"] = len(teachers)
    report.stats["total_classes"] = len(classes)
    report.stats["total_classrooms"] = len(classrooms)

    _check_minimal_data(report, teachers, classes, classrooms, lessons, periods)
    if report.errors:
        report.feasible = False
        return report

    _check_global_capacity(
        report,
        lessons=lessons,
        days_per_week=days_per_week,
        n_periods=n_periods,
        n_classrooms=len(classrooms),
    )
    _check_teacher_load(
        report,
        lessons=lessons,
        teachers=teachers,
        teacher_unavail=teacher_unavail,
        days_per_week=days_per_week,
        n_periods=n_periods,
    )
    _check_class_load(
        report,
        lessons=lessons,
        classes=classes,
        days_per_week=days_per_week,
        n_periods=n_periods,
    )
    _check_special_room_demand(
        report,
        lessons=lessons,
        classrooms=classrooms,
        days_per_week=days_per_week,
        n_periods=n_periods,
    )
    _check_block_lengths(report, lessons=lessons, n_periods=n_periods)
    _check_student_load(
        report,
        lessons=lessons,
        enrollments=enrollments,
        student_unavail=student_unavail,
        days_per_week=days_per_week,
        n_periods=n_periods,
    )

    report.feasible = not report.errors
    return report


def _check_minimal_data(
    report: FeasibilityReport,
    teachers: list[Teacher],
    classes: list[SchoolClass],
    classrooms: list[Classroom],
    lessons: list[Lesson],
    periods: list[Period],
) -> None:
    """Mirror engine's _validate_data minimal-existence checks."""
    if not teachers:
        report.errors.append("Δεν υπάρχουν καθηγητές")
    if not classes:
        report.errors.append("Δεν υπάρχουν τάξεις")
    if not lessons:
        report.errors.append("Δεν υπάρχουν μαθήματα-κάρτες")
    if not periods:
        report.errors.append("Δεν υπάρχουν ώρες διδασκαλίας")
    if not classrooms:
        report.errors.append("Δεν υπάρχουν αίθουσες")


def _check_global_capacity(
    report: FeasibilityReport,
    lessons: list[Lesson],
    days_per_week: int,
    n_periods: int,
    n_classrooms: int,
) -> None:
    """Total demand vs supply across all rooms/periods/days."""
    total_needed = sum(l.periods_per_week for l in lessons)
    total_available = days_per_week * n_periods * n_classrooms

    report.stats["total_periods_needed"] = total_needed
    report.stats["total_slots_available"] = total_available
    report.stats["load_factor"] = (
        round(total_needed / total_available, 3) if total_available else None
    )

    if total_needed > total_available:
        report.errors.append(
            f"Δεν επαρκούν τα slots: χρειάζονται {total_needed} αλλά "
            f"υπάρχουν μόνο {total_available} ({days_per_week} μέρες × "
            f"{n_periods} ώρες × {n_classrooms} αίθουσες)"
        )
        return

    if total_available > 0 and total_needed / total_available > 0.85:
        report.warnings.append(
            f"Υψηλή πληρότητα: {total_needed}/{total_available} slots σε χρήση "
            f"({round(100*total_needed/total_available)}%) — ο solver μπορεί "
            "να δυσκολευτεί ή να μην βρει βέλτιστη λύση γρήγορα"
        )


def _check_teacher_load(
    report: FeasibilityReport,
    lessons: list[Lesson],
    teachers: list[Teacher],
    teacher_unavail: list[TeacherAvailability],
    days_per_week: int,
    n_periods: int,
) -> None:
    """Per-teacher: hours-required vs available-periods after unavailability
    and max_periods_per_day caps."""
    by_teacher: dict[int, int] = defaultdict(int)
    for l in lessons:
        by_teacher[l.teacher_id] += l.periods_per_week

    unavail_by_teacher: dict[int, int] = defaultdict(int)
    for ua in teacher_unavail:
        unavail_by_teacher[ua.teacher_id] += 1

    teacher_overloads: list[dict] = []
    for t in teachers:
        required = by_teacher.get(t.id, 0)
        if required == 0:
            continue

        raw_capacity = days_per_week * n_periods
        unavail = unavail_by_teacher.get(t.id, 0)
        capacity = raw_capacity - unavail

        if t.max_periods_per_day and t.max_periods_per_day < n_periods:
            cap_by_max = t.max_periods_per_day * days_per_week
            capacity = min(capacity, cap_by_max)

        if t.max_periods_per_week and t.max_periods_per_week < capacity:
            capacity = t.max_periods_per_week

        if t.max_days_per_week and t.max_days_per_week < days_per_week:
            cap_by_days = t.max_days_per_week * (
                t.max_periods_per_day or n_periods
            )
            capacity = min(capacity, cap_by_days)

        teacher_overloads.append(
            {"teacher_id": t.id, "name": t.name, "required": required, "capacity": capacity}
        )
        if required > capacity:
            report.errors.append(
                f"Καθηγητής {t.name}: χρειάζεται {required} ώρες αλλά "
                f"η διαθεσιμότητά του επιτρέπει μόνο {capacity}"
            )
        elif required > capacity * 0.85 and capacity > 0:
            report.warnings.append(
                f"Καθηγητής {t.name}: φόρτος {required}/{capacity} "
                f"({round(100*required/capacity)}%) — οριακά"
            )

    report.stats["teacher_load"] = teacher_overloads


def _check_class_load(
    report: FeasibilityReport,
    lessons: list[Lesson],
    classes: list[SchoolClass],
    days_per_week: int,
    n_periods: int,
) -> None:
    """Per-class: total weekly hours can't exceed days × periods."""
    by_class: dict[int, int] = defaultdict(int)
    for l in lessons:
        by_class[l.class_id] += l.periods_per_week

    class_loads: list[dict] = []
    capacity = days_per_week * n_periods
    for c in classes:
        required = by_class.get(c.id, 0)
        if required == 0:
            continue
        class_loads.append(
            {"class_id": c.id, "name": c.name, "required": required, "capacity": capacity}
        )
        if required > capacity:
            report.errors.append(
                f"Τάξη {c.name}: χρειάζεται {required} ώρες αλλά η εβδομάδα "
                f"έχει μόνο {capacity} ({days_per_week}×{n_periods})"
            )
        elif required > capacity * 0.9:
            report.warnings.append(
                f"Τάξη {c.name}: φόρτος {required}/{capacity} "
                f"({round(100*required/capacity)}%) — πολύ γεμάτο πρόγραμμα"
            )

    report.stats["class_load"] = class_loads


def _check_special_room_demand(
    report: FeasibilityReport,
    lessons: list[Lesson],
    classrooms: list[Classroom],
    days_per_week: int,
    n_periods: int,
) -> None:
    """If subjects require lab/gym/etc., check that demand fits the rooms
    of that type."""
    rooms_by_type: dict[str, int] = defaultdict(int)
    for r in classrooms:
        rooms_by_type[r.room_type or "regular"] += 1

    demand_by_type: dict[str, int] = defaultdict(int)
    for l in lessons:
        sub = l.subject
        if l.classroom_id:
            continue
        if sub and sub.requires_special_room and sub.special_room_type:
            demand_by_type[sub.special_room_type] += l.periods_per_week

    special_summary: list[dict] = []
    for room_type, demand in demand_by_type.items():
        rooms = rooms_by_type.get(room_type, 0)
        capacity = rooms * days_per_week * n_periods
        special_summary.append(
            {
                "room_type": room_type,
                "rooms_available": rooms,
                "demand": demand,
                "capacity": capacity,
            }
        )
        if rooms == 0:
            report.errors.append(
                f"Απαιτείται αίθουσα τύπου '{room_type}' για {demand} ώρες "
                "αλλά δεν υπάρχει καμία τέτοια αίθουσα"
            )
        elif demand > capacity:
            report.errors.append(
                f"Αίθουσες τύπου '{room_type}': ζήτηση {demand} ώρες αλλά "
                f"χωρητικότητα μόνο {capacity} ({rooms} αίθουσες × "
                f"{days_per_week} μέρες × {n_periods} ώρες)"
            )

    report.stats["special_rooms"] = special_summary


def _check_block_lengths(
    report: FeasibilityReport, lessons: list[Lesson], n_periods: int
) -> None:
    """A block longer than the school day can never be placed."""
    for l in lessons:
        for length in _parse_distribution(l):
            if length > n_periods:
                report.errors.append(
                    f"{_lesson_label(l)}: ζητάει block {length} ωρών αλλά η "
                    f"μέρα έχει μόνο {n_periods} διαθέσιμες περιόδους"
                )
                break


def _check_student_load(
    report: FeasibilityReport,
    lessons: list[Lesson],
    enrollments: list[StudentClassEnrollment],
    student_unavail: list[StudentAvailability],
    days_per_week: int,
    n_periods: int,
) -> None:
    """Per-student: total weekly enrolled hours vs availability windows.
    Useful για φροντιστήριο όπου μαθητές γράφονται σε πολλά τμήματα."""
    lessons_by_class: dict[int, list[Lesson]] = defaultdict(list)
    for l in lessons:
        lessons_by_class[l.class_id].append(l)

    hours_by_student: dict[int, int] = defaultdict(int)
    for e in enrollments:
        for l in lessons_by_class.get(e.class_id, []):
            hours_by_student[e.student_id] += l.periods_per_week

    unavail_by_student: dict[int, int] = defaultdict(int)
    for ua in student_unavail:
        unavail_by_student[ua.student_id] += 1

    overloaded: list[dict] = []
    for student_id, required in hours_by_student.items():
        capacity = days_per_week * n_periods - unavail_by_student.get(student_id, 0)
        if required > capacity:
            overloaded.append(
                {"student_id": student_id, "required": required, "capacity": capacity}
            )
            report.errors.append(
                f"Μαθητής id={student_id}: εγγεγραμμένος σε {required} ώρες "
                f"αλλά η διαθεσιμότητά του επιτρέπει μόνο {capacity}"
            )
    report.stats["overloaded_students"] = overloaded
