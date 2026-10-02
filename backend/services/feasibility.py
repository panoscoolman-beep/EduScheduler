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
    Constraint,
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
)
from backend.services import lesson_roster
from backend.services.operating_hours import closed_cells
from backend.services.term_context import get_active_term_id
from backend.solver.hard_rules import parse_constraints, phrase as rules_phrase


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
            "suggestions": suggest_fixes(self.errors, self.warnings),
        }


_HARD_RULE_ADVICE = ("Χαλάρωσε τον σκληρό (υποχρεωτικό) κανόνα στους Περιορισμούς ή κάν' τον "
                     "Μαλακό, ή μείωσε/μοίρασε ώρες.")

# Χαρτογράφηση κατηγορίας προβλήματος → συγκεκριμένη ενέργεια διόρθωσης.
# Το «γιατί δεν βγαίνει» χωρίς πρόταση δράσης αφήνει τον χρήστη να ψάχνει
# στα τυφλά — εδώ μετατρέπουμε κάθε αιτία σε «τι να κάνεις».
_SUGGESTION_RULES = [
    ("Δεν επαρκούν τα slots",
     "Λιγόστεψε ώρες/εβδομάδα σε κάποια μαθήματα, πρόσθεσε αίθουσα, ή άνοιξε 6ήμερο/περισσότερες διδακτικές ώρες στις Ρυθμίσεις."),
    ("η διαθεσιμότητά του επιτρέπει μόνο",
     "Ο καθηγητής έχει δηλωμένα πολλά κωλύματα σε σχέση με τις ώρες του — χαλάρωσε τη διαθεσιμότητά του ή μοίρασε ώρες σε άλλον καθηγητή."),
    ("χρειάζεται", "Ξαναδές τον φόρτο: μείωσε ώρες ή μοίρασέ τες σε περισσότερες μέρες/καθηγητές."),
    ("δεν υπάρχει καμία τέτοια αίθουσα",
     "Πρόσθεσε αίθουσα του σωστού τύπου (π.χ. εργαστήριο) ή βγάλε την απαίτηση ειδικής αίθουσας από το μάθημα."),
    ("χωρητικότητα μόνο",
     "Οι ειδικές αίθουσες δεν φτάνουν — πρόσθεσε μία ή μείωσε τα μαθήματα που τις απαιτούν."),
    ("block", "Μείωσε το μέγεθος του block στην «Κατανομή» του μαθήματος ή αύξησε τις διδακτικές ώρες/μέρα."),
    ("εγγεγραμμένος σε", "Ο μαθητής είναι σε πολλά τμήματα με λίγη διαθεσιμότητα — μείωσε εγγραφές ή χαλάρωσε τα κωλύματά του."),
    ("Δεν υπάρχουν", "Συμπλήρωσε τα βασικά δεδομένα (καθηγητές/τάξεις/μαθήματα/αίθουσες/ώρες) πριν τρέξεις τον solver."),
    ("ωράριο λειτουργίας",
     "Το ωράριο λειτουργίας (Ρυθμίσεις) αφήνει λιγότερες ώρες απ' όσες χρειάζονται — άνοιξέ το ή μείωσε/μοίρασε ώρες."),
    ("«Max/Εβδ.»",
     "Αύξησε το «Max/Εβδ.» του καθηγητή (Καθηγητές) ή δώσε κάποιες ώρες του σε άλλον καθηγητή."),
    ("με τον σκληρό κανόνα", _HARD_RULE_ADVICE),
    ("με τους σκληρούς κανόνες", _HARD_RULE_ADVICE),
]


def suggest_fixes(errors: list[str], warnings: list[str]) -> list[str]:
    """Προτάσεις δράσης βάσει των errors/warnings — pure, unit-testable.
    Χωρίς διπλά, με σταθερή σειρά (όπως εμφανίζονται οι κανόνες)."""
    text = " ".join(errors + warnings)
    out, seen = [], set()
    for needle, advice in _SUGGESTION_RULES:
        if needle in text and advice not in seen:
            seen.add(advice)
            out.append(advice)
    return out


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


class _Cells:
    """Ποια κελιά (μέρα, ώρα) μπορεί να πάρει κάθε κάρτα — όπως ο solver:
    όλο το πλέγμα (μέρες × διδακτικές ώρες), μείον όσα είναι εκτός ωραρίου
    λειτουργίας (H0), μείον όσα απαγορεύουν σκληροί κανόνες χρήστη.

    Χωρίς ωράριο και χωρίς σκληρούς κανόνες όλα είναι ακριβώς όπως πριν
    (ίδια νούμερα, ίδια μηνύματα)."""

    def __init__(self, periods: list[Period], days_per_week: int,
                 closed: set[tuple[int, int]], hard_rules: list):
        self.periods = periods
        self.index = {p.id: i for i, p in enumerate(periods)}
        self.grid = frozenset((d, p.id) for d in range(days_per_week) for p in periods)
        self.open = frozenset(c for c in self.grid if c not in closed)
        self.rules = hard_rules
        self.restricted = len(self.open) < len(self.grid) or bool(hard_rules)
        self._allowed: dict[tuple, frozenset] = {}

    def _rules_for(self, lesson: Lesson) -> tuple:
        return tuple(r for r in self.rules if r.covers(lesson))

    def allowed(self, lesson: Lesson) -> frozenset:
        rules = self._rules_for(lesson)
        if rules not in self._allowed:
            self._allowed[rules] = frozenset(
                c for c in self.open
                if not any(r.forbids(c[0], self.index[c[1]]) for r in rules))
        return self._allowed[rules]

    def scope(self, lessons: list[Lesson]) -> tuple[frozenset, list[str]]:
        """(κελιά που χωρούν οι κάρτες, «γιατί λιγότερα από όλο το πλέγμα»)."""
        if not self.restricted:
            return self.grid, []
        distinct: dict[frozenset, None] = {}
        rules: dict[str, object] = {}
        for lesson in lessons:
            distinct[self.allowed(lesson)] = None
            for rule in self._rules_for(lesson):
                rules.setdefault(rule.label, rule)
        cells = frozenset().union(*distinct) if distinct else frozenset()
        why = []
        if len(self.open) < len(self.grid):
            why.append("μέσα στο ωράριο λειτουργίας")
        if rules and len(cells) < len(self.open):
            why.append(rules_phrase(list(rules.values())))
        return cells, why

    def free(self, cells: frozenset, unavailable: list[tuple[int, int]]) -> int:
        """|κελιά| μείον κωλύματα — χωρίς να ξαναμετράει κωλύματα σε κελιά
        που έχουν ήδη αφαιρεθεί (π.χ. πρωινό κώλυμα εκτός ωραρίου)."""
        already_out = sum(1 for c in unavailable if c in self.grid and c not in cells)
        return len(cells) - (len(unavailable) - already_out)

    def longest_run(self, lesson: Lesson) -> int:
        """Μεγαλύτερη σειρά συνεχόμενων ωρών μιας μέρας που χωράει η κάρτα."""
        allowed = self.allowed(lesson) if self.restricted else self.grid
        best = 0
        for day in {d for d, _ in self.grid}:
            run = 0
            for p in self.periods:
                run = run + 1 if (day, p.id) in allowed else 0
                best = max(best, run)
        return best


def check_feasibility(db: Session, term_id: int | None = None) -> FeasibilityReport:
    """Run all pre-solve checks against ONE scenario's data.

    term_id=None → το ενεργό σενάριο. Τα lessons και οι availability rows
    είναι scenario-scoped (Terms Phase 1) — χωρίς το φίλτρο ο έλεγχος
    άθροιζε τη ζήτηση/μη-διαθεσιμότητα ΟΛΩΝ των σεναρίων μαζί, δηλ. ψευδή
    «δεν επαρκούν» μόλις υπάρξει δεύτερο σενάριο. Mirrors engine._load_data.
    """
    report = FeasibilityReport()

    if term_id is None:
        term_id = get_active_term_id(db)

    teachers = db.query(Teacher).all()
    classes = db.query(SchoolClass).all()
    classrooms = db.query(Classroom).filter(Classroom.archived_at.is_(None)).all()
    lessons_q = db.query(Lesson)
    teacher_unavail_q = db.query(TeacherAvailability).filter(
        TeacherAvailability.status == "unavailable"
    )
    student_unavail_q = db.query(StudentAvailability).filter(
        StudentAvailability.status == "unavailable"
    )
    if term_id is not None:
        lessons_q = lessons_q.filter(Lesson.term_id == term_id)
        teacher_unavail_q = teacher_unavail_q.filter(
            TeacherAvailability.term_id == term_id
        )
        student_unavail_q = student_unavail_q.filter(
            StudentAvailability.term_id == term_id
        )
    lessons = lessons_q.all()
    periods = (
        db.query(Period)
        .filter(Period.is_break == False)  # noqa: E712
        .order_by(Period.sort_order)
        .all()
    )
    subjects = db.query(Subject).all()
    settings = db.query(SchoolSettings).first()
    days_per_week = settings.days_per_week if settings else 5

    teacher_unavail = teacher_unavail_q.all()
    student_unavail = student_unavail_q.all()
    enrollments = db.query(StudentClassEnrollment).all()
    # Όπως ο solver: ωράριο λειτουργίας (H0) + «Σκληροί» κανόνες χρήστη.
    rules = parse_constraints(
        db.query(Constraint).filter(Constraint.is_active == True).all())  # noqa: E712
    cells = _Cells(periods, days_per_week,
                   closed_cells(settings, periods, days_per_week), rules.hard_rules)

    report.stats["term_id"] = term_id

    n_periods = len(periods)
    report.stats["days_per_week"] = days_per_week
    report.stats["periods_per_day"] = n_periods
    report.stats["open_periods_per_week"] = len(cells.open)
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
        cells=cells,
    )
    _check_teacher_load(
        report,
        lessons=lessons,
        teachers=teachers,
        teacher_unavail=teacher_unavail,
        days_per_week=days_per_week,
        n_periods=n_periods,
        cells=cells,
    )
    _check_class_load(
        report,
        lessons=lessons,
        classes=classes,
        days_per_week=days_per_week,
        n_periods=n_periods,
        cells=cells,
    )
    _check_special_room_demand(
        report,
        lessons=lessons,
        classrooms=classrooms,
        days_per_week=days_per_week,
        n_periods=n_periods,
        cells=cells,
    )
    _check_block_lengths(report, lessons=lessons, n_periods=n_periods, cells=cells)
    _check_rule_restricted_lessons(report, lessons=lessons, teacher_unavail=teacher_unavail,
                                   cells=cells)
    _check_student_load(
        report,
        lessons=lessons,
        enrollments=enrollments,
        student_unavail=student_unavail,
        days_per_week=days_per_week,
        n_periods=n_periods,
        # 👥 Η λίστα ΚΑΘΕ κάρτας (τμήμα + προσθήκες − εξαιρέσεις), όπως ο solver.
        rosters=lesson_roster.roster_map(db, lessons),
        student_names={st.id: f"{st.last_name} {st.first_name}".strip()
                       for st in db.query(Student).all()},
        cells=cells,
    )
    # Σκληροί κανόνες που δεν επιβάλλονται ως υποχρεωτικοί — να το ξέρει ο χρήστης.
    report.warnings.extend(rules.warnings)

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
    cells: _Cells | None = None,
) -> None:
    """Total demand vs supply across all rooms/periods/days (μέσα στο
    ωράριο λειτουργίας / τους σκληρούς κανόνες, αν υπάρχουν)."""
    total_needed = sum(l.periods_per_week for l in lessons)
    usable, why = cells.scope(lessons) if cells else (None, [])
    n_cells = len(usable) if why else days_per_week * n_periods
    total_available = n_cells * n_classrooms

    report.stats["total_periods_needed"] = total_needed
    report.stats["total_slots_available"] = total_available
    report.stats["load_factor"] = (
        round(total_needed / total_available, 3) if total_available else None
    )

    if total_needed > total_available:
        if why:
            report.errors.append(
                f"Δεν επαρκούν τα slots: χρειάζονται {total_needed} αλλά "
                f"υπάρχουν μόνο {total_available} ({n_cells} ώρες/εβδομάδα "
                f"{' και '.join(why)} × {n_classrooms} αίθουσες)"
            )
        else:
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
    cells: _Cells | None = None,
) -> None:
    """Per-teacher: hours-required vs available-periods after unavailability
    and max_periods_per_day caps (+ ωράριο λειτουργίας / σκληροί κανόνες)."""
    by_teacher: dict[int, int] = defaultdict(int)
    lessons_by_teacher: dict[int, list[Lesson]] = defaultdict(list)
    for l in lessons:
        by_teacher[l.teacher_id] += l.periods_per_week
        lessons_by_teacher[l.teacher_id].append(l)

    unavail_by_teacher: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for ua in teacher_unavail:
        unavail_by_teacher[ua.teacher_id].append((ua.day_of_week, ua.period_id))

    teacher_overloads: list[dict] = []
    for t in teachers:
        required = by_teacher.get(t.id, 0)
        if required == 0:
            continue

        unavail = unavail_by_teacher.get(t.id, [])
        base_avail = days_per_week * n_periods - len(unavail)
        avail, why = base_avail, []
        if cells is not None:
            usable, why = cells.scope(lessons_by_teacher[t.id])
            if why:
                avail = cells.free(usable, unavail)

        limits = []
        if t.max_periods_per_day and t.max_periods_per_day < n_periods:
            limits.append(t.max_periods_per_day * days_per_week)
        if t.max_days_per_week and t.max_days_per_week < days_per_week:
            limits.append(t.max_days_per_week * (t.max_periods_per_day or n_periods))
        week = t.max_periods_per_week or None
        caps = limits + ([week] if week else [])
        base_capacity = min([base_avail, *caps])   # όπως πριν (χωρίς ωράριο/κανόνες)
        capacity = min([avail, *caps])

        teacher_overloads.append(
            {"teacher_id": t.id, "name": t.name, "required": required, "capacity": capacity}
        )
        if required > capacity:
            if week and week < min([avail, *limits]):
                # Το «Max/Εβδ.» είναι το όριο που κόβει — ο solver το τηρεί (H6b).
                report.errors.append(
                    f"Καθηγητής {t.name}: έχει {required} ώρες μαθημάτων αλλά "
                    f"«Max/Εβδ.» {week}"
                )
            elif why and required <= base_capacity:
                report.errors.append(
                    f"Καθηγητής {t.name}: χρειάζεται {required} ώρες αλλά "
                    f"χωράνε μόνο {capacity} {' και '.join(why)}"
                )
            else:
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
    cells: _Cells | None = None,
) -> None:
    """Per-class: total weekly hours can't exceed days × periods
    (μέσα στο ωράριο λειτουργίας / τους σκληρούς κανόνες, αν υπάρχουν)."""
    by_class: dict[int, int] = defaultdict(int)
    lessons_by_class: dict[int, list[Lesson]] = defaultdict(list)
    for l in lessons:
        by_class[l.class_id] += l.periods_per_week
        lessons_by_class[l.class_id].append(l)

    class_loads: list[dict] = []
    for c in classes:
        required = by_class.get(c.id, 0)
        if required == 0:
            continue
        capacity, why = days_per_week * n_periods, []
        if cells is not None:
            usable, why = cells.scope(lessons_by_class[c.id])
            if why:
                capacity = len(usable)
        class_loads.append(
            {"class_id": c.id, "name": c.name, "required": required, "capacity": capacity}
        )
        if required > capacity and why:
            report.errors.append(
                f"Τάξη {c.name}: χρειάζεται {required} ώρες αλλά χωράνε μόνο "
                f"{capacity} {' και '.join(why)}"
            )
        elif required > capacity:
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
    cells: _Cells | None = None,
) -> None:
    """If subjects require lab/gym/etc., check that demand fits the rooms
    of that type."""
    rooms_by_type: dict[str, int] = defaultdict(int)
    for r in classrooms:
        rooms_by_type[r.room_type or "regular"] += 1

    demand_by_type: dict[str, int] = defaultdict(int)
    lessons_by_type: dict[str, list[Lesson]] = defaultdict(list)
    for l in lessons:
        sub = l.subject
        if l.classroom_id:
            continue
        if sub and sub.requires_special_room and sub.special_room_type:
            demand_by_type[sub.special_room_type] += l.periods_per_week
            lessons_by_type[sub.special_room_type].append(l)

    special_summary: list[dict] = []
    for room_type, demand in demand_by_type.items():
        rooms = rooms_by_type.get(room_type, 0)
        n_cells, why = days_per_week * n_periods, []
        if cells is not None:
            usable, why = cells.scope(lessons_by_type[room_type])
            if why:
                n_cells = len(usable)
        capacity = rooms * n_cells
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
        elif demand > capacity and why:
            report.errors.append(
                f"Αίθουσες τύπου '{room_type}': ζήτηση {demand} ώρες αλλά "
                f"χωρητικότητα μόνο {capacity} ({rooms} αίθουσες × "
                f"{n_cells} ώρες/εβδομάδα {' και '.join(why)})"
            )
        elif demand > capacity:
            report.errors.append(
                f"Αίθουσες τύπου '{room_type}': ζήτηση {demand} ώρες αλλά "
                f"χωρητικότητα μόνο {capacity} ({rooms} αίθουσες × "
                f"{days_per_week} μέρες × {n_periods} ώρες)"
            )

    report.stats["special_rooms"] = special_summary


def _check_rule_restricted_lessons(
    report: FeasibilityReport,
    lessons: list[Lesson],
    teacher_unavail: list[TeacherAvailability],
    cells: _Cells,
) -> None:
    """Κάρτα που περιορίζει σκληρός κανόνας: χωράνε οι ώρες της στα κελιά
    που αφήνει ο κανόνας, μείον τα κωλύματα του καθηγητή της; (Τα αθροιστικά
    checks ανά καθηγητή/τμήμα δεν το βλέπουν όταν μόνο μία κάρτα περιορίζεται.)"""
    if not cells.rules:
        return
    unavail: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for ua in teacher_unavail:
        unavail[ua.teacher_id].add((ua.day_of_week, ua.period_id))
    for l in lessons:
        if len(cells.allowed(l)) >= len(cells.open):
            continue  # κανένας σκληρός κανόνας δεν της κόβει κελιά
        usable, why = cells.scope([l])
        blocked = unavail.get(l.teacher_id, set()) & usable
        possible = len(usable) - len(blocked)
        if l.periods_per_week > possible:
            extra = " και με τα κωλύματα του καθηγητή" if blocked else ""
            report.errors.append(
                f"{_lesson_label(l)}: χρειάζεται {l.periods_per_week} ώρες αλλά χωράνε "
                f"μόνο {possible} {' και '.join(why)}{extra}"
            )


def _check_block_lengths(
    report: FeasibilityReport, lessons: list[Lesson], n_periods: int,
    cells: _Cells | None = None,
) -> None:
    """A block longer than the school day can never be placed — ούτε block
    μεγαλύτερο από τις συνεχόμενες ώρες που αφήνει το ωράριο λειτουργίας /
    ένας σκληρός κανόνας."""
    restricted = cells is not None and cells.restricted
    for l in lessons:
        run = cells.longest_run(l) if restricted else n_periods
        for length in _parse_distribution(l):
            if length > n_periods:
                report.errors.append(
                    f"{_lesson_label(l)}: ζητάει block {length} ωρών αλλά η "
                    f"μέρα έχει μόνο {n_periods} διαθέσιμες περιόδους"
                )
                break
            if length > run:
                _, why = cells.scope([l])
                report.errors.append(
                    f"{_lesson_label(l)}: ζητάει block {length} ωρών αλλά "
                    f"{' και '.join(why) or 'με τους περιορισμούς'} η μέρα έχει μόνο "
                    f"{run} συνεχόμενες ώρες"
                )
                break


def _check_student_load(
    report: FeasibilityReport,
    lessons: list[Lesson],
    enrollments: list[StudentClassEnrollment],
    student_unavail: list[StudentAvailability],
    days_per_week: int,
    n_periods: int,
    rosters: dict[int, set[int]] | None = None,
    student_names: dict[int, str] | None = None,
    cells: _Cells | None = None,
) -> None:
    """Per-student: total weekly enrolled hours vs availability windows.
    Useful για φροντιστήριο όπου μαθητές γράφονται σε πολλά τμήματα.

    `rosters` ({lesson_id: {student_id}}) = η λίστα κάθε κάρτας με τις
    εξαιρέσεις/προσθήκες· χωρίς αυτό, μετράμε τα σκέτα τμήματα."""
    hours_by_student: dict[int, int] = defaultdict(int)
    lessons_by_student: dict[int, list[Lesson]] = defaultdict(list)
    if rosters is not None:
        for l in lessons:
            for sid in rosters.get(l.id, ()):
                hours_by_student[sid] += l.periods_per_week
                lessons_by_student[sid].append(l)
    else:
        lessons_by_class: dict[int, list[Lesson]] = defaultdict(list)
        for l in lessons:
            lessons_by_class[l.class_id].append(l)
        for e in enrollments:
            for l in lessons_by_class.get(e.class_id, []):
                hours_by_student[e.student_id] += l.periods_per_week
                lessons_by_student[e.student_id].append(l)

    unavail_by_student: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for ua in student_unavail:
        unavail_by_student[ua.student_id].append((ua.day_of_week, ua.period_id))

    overloaded: list[dict] = []
    for student_id, required in hours_by_student.items():
        unavail = unavail_by_student.get(student_id, [])
        base_capacity = days_per_week * n_periods - len(unavail)
        capacity, why = base_capacity, []
        if cells is not None:
            usable, why = cells.scope(lessons_by_student[student_id])
            if why:
                capacity = cells.free(usable, unavail)
        if required > capacity:
            overloaded.append(
                {"student_id": student_id, "required": required, "capacity": capacity}
            )
            who = (student_names or {}).get(student_id) or f"id={student_id}"
            if why and required <= base_capacity:
                report.errors.append(
                    f"Μαθητής {who}: εγγεγραμμένος σε {required} ώρες "
                    f"αλλά χωράνε μόνο {capacity} {' και '.join(why)}"
                )
            else:
                report.errors.append(
                    f"Μαθητής {who}: εγγεγραμμένος σε {required} ώρες "
                    f"αλλά η διαθεσιμότητά του επιτρέπει μόνο {capacity}"
                )
    report.stats["overloaded_students"] = overloaded
