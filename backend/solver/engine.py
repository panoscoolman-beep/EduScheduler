"""
EduScheduler Solver Engine — Google OR-Tools CP-SAT

Transforms school scheduling data into a Constraint Satisfaction Problem
and solves it to produce an optimal timetable.
"""

import json
import logging
from dataclasses import dataclass, field

from ortools.sat.python import cp_model
from sqlalchemy.orm import Session

from backend.models import (
    Teacher, Subject, SchoolClass, Classroom, Lesson,
    Period, TeacherAvailability, Constraint,
    TimetableSolution, TimetableSlot, SchoolSettings,
    StudentClassEnrollment, StudentAvailability
)

logger = logging.getLogger(__name__)


@dataclass
class SolverResult:
    """Result from the solver engine."""
    status: str  # optimal / feasible / infeasible / timeout / error
    message: str
    score: float | None = None
    slots: list[dict] = field(default_factory=list)
    unplaced: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


class TimetableSolver:
    """
    CP-SAT based timetable solver.

    Workflow:
    1. Load all entities from DB
    2. Build CP-SAT model with decision variables
    3. Apply hard constraints
    4. Apply soft constraints (as penalty terms)
    5. Solve and extract solution
    """

    # In permissive mode each unplaced block adds this much penalty so
    # the solver always prefers placing whenever feasible. Tuned to be
    # an order of magnitude larger than typical soft-constraint weights.
    UNPLACED_PENALTY: int = 100_000

    def __init__(self, db: Session, max_time_seconds: int = 120,
                 mode: str = "strict"):
        """
        Args:
            db: SQLAlchemy session
            max_time_seconds: solver wall-time cap
            mode: "strict" (every block must be placed — INFEASIBLE if
                any can't fit) or "permissive" (blocks are placed when
                possible, otherwise reported in `result.unplaced`).
        """
        self.db = db
        self.max_time_seconds = max_time_seconds
        self.mode = mode if mode in ("strict", "permissive") else "strict"

        # Data from DB (loaded in _load_data)
        self.teachers: list[Teacher] = []
        self.subjects: list[Subject] = []
        self.classes: list[SchoolClass] = []
        self.classrooms: list[Classroom] = []
        self.lessons: list[Lesson] = []
        self.periods: list[Period] = []
        self.availabilities: list[TeacherAvailability] = []
        self.student_availabilities: list[StudentAvailability] = []
        self.constraints: list[Constraint] = []
        self.enrollments: list[StudentClassEnrollment] = []
        self.days_per_week: int = 5

        # OR-Tools
        self.model = cp_model.CpModel()
        self.x: dict[tuple[int, int, int, int], cp_model.IntVar] = {}
        self.penalties: list[cp_model.IntVar] = []

        # Index mappings for fast lookup
        self._lessons_by_teacher: dict[int, list[Lesson]] = {}
        self._lessons_by_class: dict[int, list[Lesson]] = {}
        self._lessons_by_student: dict[int, list[Lesson]] = {}
        self._unavailable: set[tuple[int, int, int]] = set()  # (teacher_id, day, period_id)
        self._student_unavailable: set[tuple[int, int, int]] = set() # (student_id, day, period_id)
        self._teaching_period_ids: list[int] = []

    def solve(self) -> SolverResult:
        """Run the full solve pipeline."""
        try:
            self._load_data()
            validation_error = self._validate_data()
            if validation_error:
                return SolverResult(status="error", message=validation_error)

            self._build_indices()
            self._create_variables()
            self._apply_hard_constraints()
            self._apply_soft_constraints()

            # Objective: minimize total penalty
            if self.penalties:
                self.model.Minimize(sum(self.penalties))

            # Solve
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = self.max_time_seconds
            solver.parameters.num_workers = 4
            solver.parameters.log_search_progress = True

            status = solver.Solve(self.model)

            return self._extract_result(solver, status)

        except Exception as e:
            logger.exception("Solver encountered an error")
            return SolverResult(status="error", message=f"Σφάλμα solver: {str(e)}")

    def _load_data(self):
        """Load all required data from the database."""
        self.teachers = self.db.query(Teacher).all()
        self.subjects = self.db.query(Subject).all()
        self.classes = self.db.query(SchoolClass).all()
        self.classrooms = self.db.query(Classroom).all()
        self.lessons = self.db.query(Lesson).all()
        self.periods = self.db.query(Period).filter(Period.is_break == False).order_by(Period.sort_order).all()
        self.availabilities = self.db.query(TeacherAvailability).filter(
            TeacherAvailability.status == "unavailable"
        ).all()
        self.student_availabilities = self.db.query(StudentAvailability).filter(
            StudentAvailability.status == "unavailable"
        ).all()
        self.enrollments = self.db.query(StudentClassEnrollment).all()
        self.constraints = self.db.query(Constraint).filter(Constraint.is_active == True).all()

        settings = self.db.query(SchoolSettings).first()
        self.days_per_week = settings.days_per_week if settings else 5

    def _validate_data(self) -> str | None:
        """Validate that we have enough data to generate a schedule.

        Beyond quantity checks, we look for individual lessons that **cannot
        be placed** with the current configuration so the solver doesn't
        silently drop them (issue: lessons with deleted classroom_id, or
        special_room_type with no matching room, or block size larger than
        the school day). Surface those as a friendly error instead of
        producing a partial schedule.
        """
        if not self.teachers:
            return "Δεν υπάρχουν καθηγητές"
        if not self.classes:
            return "Δεν υπάρχουν τάξεις"
        if not self.lessons:
            return "Δεν υπάρχουν μαθήματα-κάρτες"
        if not self.periods:
            return "Δεν υπάρχουν ώρες διδασκαλίας"
        if not self.classrooms:
            return "Δεν υπάρχουν αίθουσες"

        # Check total capacity
        total_slots_needed = sum(l.periods_per_week for l in self.lessons)
        total_slots_available = self.days_per_week * len(self.periods) * len(self.classrooms)
        if total_slots_needed > total_slots_available:
            return (
                f"Δεν επαρκούν τα slots: χρειάζονται {total_slots_needed} "
                f"αλλά υπάρχουν μόνο {total_slots_available} "
                f"({self.days_per_week} μέρες × {len(self.periods)} ώρες × {len(self.classrooms)} αίθουσες)"
            )

        # Per-lesson placement checks — these are the silent-drop traps.
        # In permissive mode they're not fatal — undeplaceable lessons end
        # up in the parking lot. We record them in `_pre_unplaced` so
        # `_extract_result` can surface them with a reason.
        self._pre_unplaced: list[dict] = []
        unplaceable_messages: list[str] = []
        n_periods = len(self.periods)

        for lesson in self.lessons:
            label = self._lesson_label(lesson)

            rooms = self._get_available_rooms(lesson)
            if not rooms:
                if lesson.classroom_id:
                    reason = (
                        f"αίθουσα id={lesson.classroom_id} δεν υπάρχει "
                        "(διαγράφηκε χωρίς να ενημερωθεί το lesson)"
                    )
                else:
                    sub = lesson.subject
                    rt = sub.special_room_type if sub else "?"
                    reason = (
                        f"το μάθημα απαιτεί αίθουσα τύπου '{rt}' αλλά "
                        "δεν υπάρχει καμία τέτοια"
                    )
                unplaceable_messages.append(f"  • {label}: {reason}")
                self._pre_unplaced.append(
                    {"lesson_id": lesson.id, "reason": reason}
                )
                continue

            for L in self._parse_distribution(lesson):
                if L > n_periods:
                    reason = (
                        f"ζητάει block {L} ωρών αλλά η μέρα έχει μόνο "
                        f"{n_periods} διαθέσιμες περιόδους"
                    )
                    unplaceable_messages.append(f"  • {label}: {reason}")
                    self._pre_unplaced.append(
                        {"lesson_id": lesson.id, "reason": reason}
                    )
                    break

        if unplaceable_messages and self.mode == "strict":
            return (
                "Δεν μπορούν να τοποθετηθούν τα παρακάτω μαθήματα:\n"
                + "\n".join(unplaceable_messages)
                + "\n\nΔιόρθωσε αυτά πρώτα ή χρησιμοποίησε permissive mode "
                "για να σταλούν στο parking lot."
            )

        return None

    def _lesson_label(self, lesson: Lesson) -> str:
        """Human-readable label για μηνύματα προς τον χρήστη."""
        subj = lesson.subject.name if lesson.subject else "?"
        cls = lesson.school_class.name if lesson.school_class else "?"
        return f"{subj} (τμήμα {cls}, lesson id={lesson.id})"

    def _build_indices(self):
        """Build lookup indices for fast constraint checking."""
        self._teaching_period_ids = [p.id for p in self.periods]

        for lesson in self.lessons:
            self._lessons_by_teacher.setdefault(lesson.teacher_id, []).append(lesson)
            self._lessons_by_class.setdefault(lesson.class_id, []).append(lesson)

        # Build _lessons_by_student
        class_to_lessons = self._lessons_by_class
        for enrollment in self.enrollments:
            student_id = enrollment.student_id
            class_id = enrollment.class_id
            if class_id in class_to_lessons:
                self._lessons_by_student.setdefault(student_id, []).extend(class_to_lessons[class_id])

        for avail in self.availabilities:
            self._unavailable.add((avail.teacher_id, avail.day_of_week, avail.period_id))

        for savail in self.student_availabilities:
            self._student_unavailable.add((savail.student_id, savail.day_of_week, savail.period_id))

    def _get_available_rooms(self, lesson: Lesson) -> list[Classroom]:
        """Get rooms that can host this lesson."""
        if lesson.classroom_id:
            room = next((r for r in self.classrooms if r.id == lesson.classroom_id), None)
            return [room] if room else []

        if lesson.subject and lesson.subject.requires_special_room:
            return [r for r in self.classrooms if r.room_type == lesson.subject.special_room_type]

        return self.classrooms

    def _parse_distribution(self, lesson: Lesson) -> list[int]:
        """Convert a distribution string like '2,1' to a list of block lengths [2, 1]."""
        if lesson.distribution:
            try:
                blocks = [int(v.strip()) for v in lesson.distribution.split(",") if v.strip()]
                if sum(blocks) == lesson.periods_per_week:
                    return blocks
            except ValueError:
                pass
        # Default: all 1s
        return [1] * lesson.periods_per_week

    def _create_variables(self):
        """Create decision variables: blocks and coverage (x).

        In strict mode, each lesson block must be placed exactly once
        (AddExactlyOne hard constraint).

        In permissive mode, each block has a 'placed' bool that the solver
        is heavily penalized for setting to 0 — so it will always prefer
        to place a block when feasible, and only leave one unplaced when
        no legal slot exists. `_block_placed` is recorded so we can read
        back which blocks ended up in the parking lot.
        """
        days = range(self.days_per_week)
        # Mapping for cell coverage: (day, period_id, room_id) -> list of block_start vars that cover it
        self._covers = {}
        # In permissive mode: list of (lesson_id, block_idx, length, placed_var, reason_if_no_starts)
        self._block_placed: list[tuple] = []

        for lesson in self.lessons:
            blocks = self._parse_distribution(lesson)
            available_rooms = self._get_available_rooms(lesson)

            for b_idx, L in enumerate(blocks):
                # We need exactly one start var for this block
                block_start_vars = []
                for day in days:
                    for i in range(len(self.periods) - L + 1):
                        p_start = self.periods[i]
                        for room in available_rooms:
                            var_name = f"b_l{lesson.id}_b{b_idx}_d{day}_p{p_start.id}_r{room.id}"
                            b_var = self.model.NewBoolVar(var_name)
                            block_start_vars.append(b_var)

                            # Record that this start var covers subsequent periods
                            for offset in range(L):
                                p_covered = self.periods[i + offset]
                                key = (lesson.id, day, p_covered.id, room.id)
                                self._covers.setdefault(key, []).append(b_var)

                if not block_start_vars:
                    # No legal placement (e.g. block too long for any day)
                    if self.mode == "permissive":
                        self._block_placed.append(
                            (lesson.id, b_idx, L, None,
                             "Δεν υπάρχει νόμιμη θέση για αυτό το block")
                        )
                    continue

                if self.mode == "strict":
                    self.model.AddExactlyOne(block_start_vars)
                else:
                    # Permissive: placed = sum(starts), penalize 1 - placed.
                    placed = self.model.NewBoolVar(
                        f"placed_l{lesson.id}_b{b_idx}"
                    )
                    self.model.Add(sum(block_start_vars) == placed)
                    self.penalties.append((1 - placed) * self.UNPLACED_PENALTY)
                    self._block_placed.append(
                        (lesson.id, b_idx, L, placed, None)
                    )

            # Map the block coverage to x
            for day in days:
                for p in self.periods:
                    for room in available_rooms:
                        var_name = f"x_l{lesson.id}_d{day}_p{p.id}_r{room.id}"
                        x_var = self.model.NewBoolVar(var_name)
                        self.x[lesson.id, day, p.id, room.id] = x_var

                        # Get all block start vars of THIS lesson that cover this cell
                        covering_vars = self._covers.get((lesson.id, day, p.id, room.id), [])
                        
                        if not covering_vars:
                            # Cannot be scheduled here
                            self.model.Add(x_var == 0)
                        else:
                            # x_var is exactly the sum of its covering blocks 
                            # (since blocks of the same lesson cannot overlap because x is boolean)
                            self.model.Add(x_var == sum(covering_vars))

    def _apply_hard_constraints(self):
        """Apply all hard (non-negotiable) constraints."""
        days = range(self.days_per_week)

        # H1: (Removed) Each lesson is scheduled exactly periods_per_week times.
        # This is now implicitly enforced by the Block Distribution mechanics in _create_variables.

        # H2: No teacher clash — at most 1 lesson per teacher per (day, period)
        for teacher_id, teacher_lessons in self._lessons_by_teacher.items():
            for day in days:
                for period in self.periods:
                    vars_at_slot = []
                    for lesson in teacher_lessons:
                        available_rooms = self._get_available_rooms(lesson)
                        for room in available_rooms:
                            key = (lesson.id, day, period.id, room.id)
                            if key in self.x:
                                vars_at_slot.append(self.x[key])
                    if vars_at_slot:
                        self.model.Add(sum(vars_at_slot) <= 1)

        # H3: No class clash — at most 1 lesson per class per (day, period)
        for class_id, class_lessons in self._lessons_by_class.items():
            for day in days:
                for period in self.periods:
                    vars_at_slot = []
                    for lesson in class_lessons:
                        available_rooms = self._get_available_rooms(lesson)
                        for room in available_rooms:
                            key = (lesson.id, day, period.id, room.id)
                            if key in self.x:
                                vars_at_slot.append(self.x[key])
                    if vars_at_slot:
                        self.model.Add(sum(vars_at_slot) <= 1)

        # H4: No room clash — at most 1 lesson per room per (day, period)
        for room in self.classrooms:
            for day in days:
                for period in self.periods:
                    vars_at_slot = [
                        self.x[l.id, day, period.id, room.id]
                        for l in self.lessons
                        if (l.id, day, period.id, room.id) in self.x
                    ]
                    if vars_at_slot:
                        self.model.Add(sum(vars_at_slot) <= 1)

        # H5: Teacher availability — block unavailable slots
        for teacher_id, teacher_lessons in self._lessons_by_teacher.items():
            for lesson in teacher_lessons:
                available_rooms = self._get_available_rooms(lesson)
                for day in days:
                    for period in self.periods:
                        if (teacher_id, day, period.id) in self._unavailable:
                            for room in available_rooms:
                                key = (lesson.id, day, period.id, room.id)
                                if key in self.x:
                                    self.model.Add(self.x[key] == 0)

        # H6: Max periods per day for teachers
        for teacher in self.teachers:
            if teacher.max_periods_per_day:
                teacher_lessons = self._lessons_by_teacher.get(teacher.id, [])
                for day in days:
                    vars_in_day = []
                    for lesson in teacher_lessons:
                        available_rooms = self._get_available_rooms(lesson)
                        for period in self.periods:
                            for room in available_rooms:
                                key = (lesson.id, day, period.id, room.id)
                                if key in self.x:
                                    vars_in_day.append(self.x[key])
                    if vars_in_day:
                        self.model.Add(sum(vars_in_day) <= teacher.max_periods_per_day)

        # H7: No student clash (cross-class overlap)
        for student_id, student_lessons in self._lessons_by_student.items():
            for day in days:
                for period in self.periods:
                    vars_at_slot = []
                    for lesson in student_lessons:
                        available_rooms = self._get_available_rooms(lesson)
                        for room in available_rooms:
                            key = (lesson.id, day, period.id, room.id)
                            if key in self.x:
                                vars_at_slot.append(self.x[key])
                    if vars_at_slot:
                        self.model.Add(sum(vars_at_slot) <= 1)

        # H8: Student availability — block unavailable slots
        for student_id, student_lessons in self._lessons_by_student.items():
            for lesson in student_lessons:
                available_rooms = self._get_available_rooms(lesson)
                for day in days:
                    for period in self.periods:
                        if (student_id, day, period.id) in self._student_unavailable:
                            for room in available_rooms:
                                key = (lesson.id, day, period.id, room.id)
                                if key in self.x:
                                    self.model.Add(self.x[key] == 0)

        # H9: Teacher Max Days Per Week
        for teacher in self.teachers:
            if teacher.max_days_per_week and teacher.max_days_per_week < self.days_per_week:
                teacher_lessons = self._lessons_by_teacher.get(teacher.id, [])
                if not teacher_lessons:
                    continue
                days_working_vars = []
                for day in days:
                    day_var = self.model.NewBoolVar(f"t_day_{teacher.id}_{day}")
                    days_working_vars.append(day_var)
                    vars_in_day = []
                    for lesson in teacher_lessons:
                        available_rooms = self._get_available_rooms(lesson)
                        for period in self.periods:
                            for room in available_rooms:
                                key = (lesson.id, day, period.id, room.id)
                                if key in self.x:
                                    vars_in_day.append(self.x[key])
                    if vars_in_day:
                        self.model.AddMaxEquality(day_var, vars_in_day)
                    else:
                        self.model.Add(day_var == 0)
                
                self.model.Add(sum(days_working_vars) <= teacher.max_days_per_week)

        # H10: Student Max Days Per Week
        for enrollment in self.enrollments:
            student = enrollment.student
            if student.max_days_per_week and student.max_days_per_week < self.days_per_week:
                student_lessons = self._lessons_by_student.get(student.id, [])
                if not student_lessons:
                    continue
                days_working_vars = []
                for day in days:
                    day_var = self.model.NewBoolVar(f"s_day_{student.id}_{day}")
                    days_working_vars.append(day_var)
                    vars_in_day = []
                    for lesson in student_lessons:
                        available_rooms = self._get_available_rooms(lesson)
                        for period in self.periods:
                            for room in available_rooms:
                                key = (lesson.id, day, period.id, room.id)
                                if key in self.x:
                                    vars_in_day.append(self.x[key])
                    if vars_in_day:
                        self.model.AddMaxEquality(day_var, vars_in_day)
                    else:
                        self.model.Add(day_var == 0)
                
                self.model.Add(sum(days_working_vars) <= student.max_days_per_week)

    def _apply_soft_constraints(self):
        """Apply soft constraints as penalty terms in the objective."""
        days = range(self.days_per_week)
        active_soft = [c for c in self.constraints if c.constraint_type == "soft"]

        for constraint in active_soft:
            rule = json.loads(constraint.rule)
            rule_type = rule.get("type")

            if rule_type == "min_teacher_gaps":
                self._soft_min_teacher_gaps(days, constraint.weight)
            elif rule_type == "min_class_gaps":
                self._soft_min_class_gaps(days, constraint.weight)
            elif rule_type == "subject_distribution":
                self._soft_subject_distribution(days, constraint.weight)
            elif rule_type == "teacher_day_balance":
                self._soft_teacher_day_balance(days, constraint.weight)

    def _soft_min_teacher_gaps(self, days: range, weight: int):
        """Minimize gaps in teacher schedules (penalize free periods between lessons)."""
        for teacher_id, teacher_lessons in self._lessons_by_teacher.items():
            for day in days:
                # For each pair of non-consecutive teaching slots, penalize if gap
                period_ids = self._teaching_period_ids
                for i in range(len(period_ids)):
                    for j in range(i + 2, len(period_ids)):
                        # Teacher teaches at period i and j but not at periods between
                        teaches_at_i = []
                        teaches_at_j = []
                        teaches_between = []

                        for lesson in teacher_lessons:
                            rooms = self._get_available_rooms(lesson)
                            for room in rooms:
                                key_i = (lesson.id, day, period_ids[i], room.id)
                                key_j = (lesson.id, day, period_ids[j], room.id)
                                if key_i in self.x:
                                    teaches_at_i.append(self.x[key_i])
                                if key_j in self.x:
                                    teaches_at_j.append(self.x[key_j])

                                for k in range(i + 1, j):
                                    key_k = (lesson.id, day, period_ids[k], room.id)
                                    if key_k in self.x:
                                        teaches_between.append(self.x[key_k])

                        # Only penalize single-period gaps to keep model manageable
                        if j == i + 2 and teaches_at_i and teaches_at_j and not teaches_between:
                            gap_penalty = self.model.NewBoolVar(
                                f"gap_t{teacher_id}_d{day}_p{i}_{j}"
                            )
                            # gap_penalty = 1 if teacher teaches at i and j but not between
                            self.model.AddBoolOr(
                                [gap_penalty.Not()] +
                                [v.Not() for v in teaches_at_i]
                            )
                            self.model.AddBoolOr(
                                [gap_penalty.Not()] +
                                [v.Not() for v in teaches_at_j]
                            )
                            self.penalties.append(gap_penalty * weight)

    def _soft_min_class_gaps(self, days: range, weight: int):
        """Minimize gaps in class schedules."""
        for class_id, class_lessons in self._lessons_by_class.items():
            for day in days:
                period_ids = self._teaching_period_ids
                for i in range(len(period_ids) - 2):
                    teaches_at_i = []
                    teaches_at_next = []

                    for lesson in class_lessons:
                        rooms = self._get_available_rooms(lesson)
                        for room in rooms:
                            key_i = (lesson.id, day, period_ids[i], room.id)
                            key_next = (lesson.id, day, period_ids[i + 2], room.id)
                            if key_i in self.x:
                                teaches_at_i.append(self.x[key_i])
                            if key_next in self.x:
                                teaches_at_next.append(self.x[key_next])

                    # Simple gap detection for adjacent pairs
                    if teaches_at_i and teaches_at_next:
                        gap_var = self.model.NewBoolVar(f"cgap_c{class_id}_d{day}_p{i}")
                        self.penalties.append(gap_var * weight)

    def _soft_subject_distribution(self, days: range, weight: int):
        """Try to spread lessons of same subject across different days."""
        for lesson in self.lessons:
            if lesson.periods_per_week <= 1:
                continue

            rooms = self._get_available_rooms(lesson)
            for day in days:
                lessons_on_day = []
                for period in self.periods:
                    for room in rooms:
                        key = (lesson.id, day, period.id, room.id)
                        if key in self.x:
                            lessons_on_day.append(self.x[key])

                if lessons_on_day and lesson.periods_per_week > 1:
                    # Penalize having more than 1 of the same lesson on the same day
                    over_one = self.model.NewIntVar(0, lesson.periods_per_week, f"dist_l{lesson.id}_d{day}")
                    self.model.Add(over_one >= sum(lessons_on_day) - 1)
                    self.model.Add(over_one >= 0)
                    self.penalties.append(over_one * weight)

    def _soft_teacher_day_balance(self, days: range, weight: int):
        """Balance teacher workload across days."""
        for teacher_id, teacher_lessons in self._lessons_by_teacher.items():
            total_lessons = sum(l.periods_per_week for l in teacher_lessons)
            ideal_per_day = total_lessons / max(self.days_per_week, 1)

            for day in days:
                day_count = []
                for lesson in teacher_lessons:
                    rooms = self._get_available_rooms(lesson)
                    for period in self.periods:
                        for room in rooms:
                            key = (lesson.id, day, period.id, room.id)
                            if key in self.x:
                                day_count.append(self.x[key])

                if day_count:
                    deviation = self.model.NewIntVar(0, 20, f"bal_t{teacher_id}_d{day}")
                    total = sum(day_count)
                    self.model.Add(deviation >= total - int(ideal_per_day + 0.5))
                    self.model.Add(deviation >= int(ideal_per_day) - total)
                    self.penalties.append(deviation * (weight // 2))

    def _collect_unplaced(self, solver: cp_model.CpSolver) -> list[dict]:
        """Build the parking-lot list. Combines:
        - lessons rejected pre-solve (no available rooms / block too long)
        - lesson blocks the solver chose to leave unplaced in permissive mode
        """
        out: list[dict] = []

        # Pre-validation rejections (only populated in permissive mode —
        # strict mode short-circuits in _validate_data)
        for entry in getattr(self, "_pre_unplaced", []):
            out.append({
                "lesson_id": entry["lesson_id"],
                "block_index": 0,
                "block_length": None,
                "reason": entry["reason"],
            })

        # Solver-decided unplaced blocks
        for lesson_id, b_idx, length, placed_var, reason in self._block_placed:
            if placed_var is None:
                # Already added via _pre_unplaced (no legal slot at all)
                if not any(e["lesson_id"] == lesson_id for e in out):
                    out.append({
                        "lesson_id": lesson_id,
                        "block_index": b_idx,
                        "block_length": length,
                        "reason": reason or "Δεν βρέθηκε κατάλληλη θέση",
                    })
                continue

            if solver.Value(placed_var) == 0:
                out.append({
                    "lesson_id": lesson_id,
                    "block_index": b_idx,
                    "block_length": length,
                    "reason": (
                        "Ο solver δεν βρήκε χωρητικό slot ταυτόχρονα με "
                        "τους υπόλοιπους περιορισμούς"
                    ),
                })

        return out

    def _extract_result(self, solver: cp_model.CpSolver, status: int) -> SolverResult:
        """Extract the solution from the solver."""
        status_map = {
            cp_model.OPTIMAL: "optimal",
            cp_model.FEASIBLE: "feasible",
            cp_model.INFEASIBLE: "infeasible",
            cp_model.MODEL_INVALID: "error",
            cp_model.UNKNOWN: "timeout",
        }

        result_status = status_map.get(status, "error")

        if result_status in ("optimal", "feasible"):
            slots = []
            for (lesson_id, day, period_id, room_id), var in self.x.items():
                if solver.Value(var) == 1:
                    slots.append({
                        "lesson_id": lesson_id,
                        "day_of_week": day,
                        "period_id": period_id,
                        "classroom_id": room_id,
                    })

            unplaced = self._collect_unplaced(solver)

            score = solver.ObjectiveValue() if self.penalties else 0.0
            if unplaced:
                message = (
                    f"Βρέθηκε λύση — τοποθετήθηκαν {len(slots)} ώρες, "
                    f"{len(unplaced)} ώρες έμειναν στο parking lot."
                )
            else:
                message = (
                    "Βρέθηκε βέλτιστη λύση!" if result_status == "optimal"
                    else "Βρέθηκε λύση (μη βέλτιστη)"
                )

            return SolverResult(
                status=result_status,
                message=message,
                score=score,
                slots=slots,
                unplaced=unplaced,
                stats={
                    "wall_time": solver.WallTime(),
                    "branches": solver.NumBranches(),
                    "conflicts": solver.NumConflicts(),
                    "total_lessons_placed": len(slots),
                    "total_lessons_unplaced": len(unplaced),
                    "mode": self.mode,
                },
            )

        if result_status == "timeout":
            return SolverResult(
                status="timeout",
                message=(
                    f"Ο solver έκανε timeout μετά από {self.max_time_seconds}s "
                    "χωρίς να βρει πλήρη λύση. Δοκίμασε:\n"
                    "  • Αύξησε το max_time_seconds (π.χ. 300)\n"
                    "  • Χαλάρωσε κάποιους hard constraints\n"
                    "  • Δοκίμασε permissive mode (parking lot για ό,τι δεν χωράει)"
                ),
                stats={
                    "wall_time": solver.WallTime(),
                    "branches": solver.NumBranches(),
                    "conflicts": solver.NumConflicts(),
                },
            )

        if result_status == "infeasible":
            return SolverResult(
                status="infeasible",
                message=(
                    "Οι περιορισμοί σου είναι αντιφατικοί — δεν υπάρχει "
                    "πρόγραμμα που να τους ικανοποιεί όλους. Δοκίμασε να "
                    "χαλαρώσεις constraints (π.χ. teacher availability ή "
                    "max_periods_per_day) ή χρησιμοποίησε permissive mode."
                ),
            )

        return SolverResult(
            status=result_status,
            message="Σφάλμα στον solver — επικοινώνησε με τον διαχειριστή.",
        )
