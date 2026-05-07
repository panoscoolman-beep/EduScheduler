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
                 mode: str = "strict",
                 locked_assignments: list[dict] | None = None):
        """
        Args:
            db: SQLAlchemy session
            max_time_seconds: solver wall-time cap
            mode: "strict" (every block must be placed — INFEASIBLE if
                any can't fit) or "permissive" (blocks are placed when
                possible, otherwise reported in `result.unplaced`).
            locked_assignments: optional list of slot dicts that the
                solver must keep at their (day, period, room). Each
                entry has lesson_id / day_of_week / period_id /
                classroom_id. Used by the "lock & regenerate" flow:
                user marks slots they like, solver redistributes the
                rest.
        """
        self.db = db
        self.max_time_seconds = max_time_seconds
        self.mode = mode if mode in ("strict", "permissive") else "strict"
        self.locked_assignments: list[dict] = locked_assignments or []

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
            self._apply_locked_assignments()
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

    def _apply_locked_assignments(self):
        """Force the cells named in self.locked_assignments to 1.

        Used by the "Lock & Regenerate" workflow: the user marks slots
        they want kept, we run the solver again, and these cells become
        hard fixed points that the solver builds around.

        If a locked cell points at an x-var that doesn't exist (e.g.
        because the lesson now has a different classroom_id constraint),
        we silently skip it rather than make the model infeasible.
        Genuinely impossible combinations will surface as INFEASIBLE
        from the regular constraint network.
        """
        if not self.locked_assignments:
            return

        applied = 0
        for entry in self.locked_assignments:
            key = (
                entry.get("lesson_id"),
                entry.get("day_of_week"),
                entry.get("period_id"),
                entry.get("classroom_id"),
            )
            if any(v is None for v in key):
                continue
            x_var = self.x.get(key)
            if x_var is None:
                logger.warning(
                    "Locked slot %s has no matching x-var, skipping", key
                )
                continue
            self.model.Add(x_var == 1)
            applied += 1
        logger.info("Applied %d locked assignments", applied)

    def _apply_soft_constraints(self):
        """Apply soft constraints as penalty terms in the objective."""
        days = range(self.days_per_week)
        active_soft = [c for c in self.constraints if c.constraint_type == "soft"]

        for constraint in active_soft:
            rule = json.loads(constraint.rule)
            rule_type = rule.get("type")
            weight = max(1, constraint.weight)

            if rule_type == "min_teacher_gaps":
                self._soft_min_teacher_gaps(days, weight)
            elif rule_type == "min_class_gaps":
                self._soft_min_class_gaps(days, weight)
            elif rule_type == "subject_distribution":
                self._soft_subject_distribution(days, weight)
            elif rule_type == "teacher_day_balance":
                self._soft_teacher_day_balance(days, weight)
            elif rule_type == "no_late_day":
                # rule: {"type":"no_late_day", "max_period_index": 5,
                #        "scope": "class"|"teacher"|"all", "id": <int>|null}
                self._soft_no_late_day(days, weight, rule)
            elif rule_type == "teacher_preferred_days":
                # rule: {"type":"teacher_preferred_days",
                #        "teacher_id": <int>, "days": [0,2,4]}
                self._soft_teacher_preferred_days(days, weight, rule)
            elif rule_type == "consecutive_blocks_preference":
                # rule: {"type":"consecutive_blocks_preference"} — no params
                self._soft_consecutive_blocks(days, weight)
            elif rule_type == "class_compactness":
                # rule: {"type":"class_compactness"} — soft penalty per
                # additional teaching day a class occupies beyond minimum
                self._soft_class_compactness(days, weight)

    def _build_busy_indicators(self, days: range, owner_lessons_map: dict[int, list]):
        """For each (owner_id, day, period_idx) build a BoolVar that is 1
        if any of `owner_lessons_map[owner_id]` is taught at that slot
        (across any room). Used by gap/late-day/preferred-day constraints
        so the OR-tools logic is identical regardless of whose schedule
        we're examining (teacher / class / room / student).

        Returns dict[(owner_id, day, period_idx)] -> BoolVar.
        """
        busy: dict[tuple[int, int, int], cp_model.IntVar] = {}
        period_ids = self._teaching_period_ids

        for owner_id, owner_lessons in owner_lessons_map.items():
            for day in days:
                for p_idx, p_id in enumerate(period_ids):
                    vars_at = []
                    for lesson in owner_lessons:
                        for room in self._get_available_rooms(lesson):
                            key = (lesson.id, day, p_id, room.id)
                            if key in self.x:
                                vars_at.append(self.x[key])
                    if not vars_at:
                        # owner cannot teach/learn at this slot — encode as 0
                        zero = self.model.NewIntVar(0, 0, f"zero_{owner_id}_{day}_{p_idx}")
                        busy[(owner_id, day, p_idx)] = zero
                        continue
                    is_busy = self.model.NewBoolVar(
                        f"busy_{owner_id}_d{day}_p{p_idx}"
                    )
                    # is_busy = max(vars_at)
                    self.model.AddMaxEquality(is_busy, vars_at)
                    busy[(owner_id, day, p_idx)] = is_busy
        return busy

    def _count_blocks_per_day(self, busy: dict, owner_id: int, day: int,
                              n_periods: int, label: str) -> cp_model.IntVar:
        """Count how many separate teaching blocks (consecutive runs of
        busy=1 periods) the owner has on this day. Returns an IntVar.
        """
        # A "block start" at period i = busy[i]=1 AND (i==0 OR busy[i-1]=0).
        # Number of blocks = sum of block_starts.
        starts = []
        for i in range(n_periods):
            s = self.model.NewBoolVar(f"start_{label}_{owner_id}_d{day}_p{i}")
            curr = busy[(owner_id, day, i)]
            if i == 0:
                # s = curr
                self.model.Add(s == curr)
            else:
                prev = busy[(owner_id, day, i - 1)]
                # s = 1 iff curr=1 AND prev=0
                # Reified: s <= curr, s <= 1-prev, s >= curr - prev
                self.model.Add(s <= curr)
                self.model.Add(s <= 1 - prev)
                self.model.Add(s >= curr - prev)
            starts.append(s)
        n_blocks = self.model.NewIntVar(0, n_periods, f"nblocks_{label}_{owner_id}_d{day}")
        self.model.Add(n_blocks == sum(starts))
        return n_blocks

    def _soft_min_teacher_gaps(self, days: range, weight: int):
        """Penalize fragmented teacher days. Σκορ = (blocks - 1) ανά μέρα,
        scaled by weight. Δουλεύει σωστά: όταν ο καθηγητής έχει 1 block
        (consecutive teaching) η ποινή είναι 0· για κάθε επιπλέον block
        προστίθεται weight."""
        busy = self._build_busy_indicators(days, self._lessons_by_teacher)
        n_periods = len(self._teaching_period_ids)
        for teacher_id in self._lessons_by_teacher:
            for day in days:
                n_blocks = self._count_blocks_per_day(
                    busy, teacher_id, day, n_periods, "tgap"
                )
                # gaps = max(0, blocks - 1)
                gaps = self.model.NewIntVar(0, n_periods, f"tgaps_{teacher_id}_d{day}")
                self.model.Add(gaps >= n_blocks - 1)
                self.model.Add(gaps >= 0)
                self.penalties.append(gaps * weight)

    def _soft_min_class_gaps(self, days: range, weight: int):
        """Penalize fragmented class days — ίδιο pattern με τους
        καθηγητές αλλά για τα τμήματα. Σημαντικό για user experience:
        τμήμα Α' Λυκείου με 1ω-κενό-1ω-κενό-1ω είναι UX disaster."""
        busy = self._build_busy_indicators(days, self._lessons_by_class)
        n_periods = len(self._teaching_period_ids)
        for class_id in self._lessons_by_class:
            for day in days:
                n_blocks = self._count_blocks_per_day(
                    busy, class_id, day, n_periods, "cgap"
                )
                gaps = self.model.NewIntVar(0, n_periods, f"cgaps_{class_id}_d{day}")
                self.model.Add(gaps >= n_blocks - 1)
                self.model.Add(gaps >= 0)
                self.penalties.append(gaps * weight)

    def _soft_no_late_day(self, days: range, weight: int, rule: dict):
        """Penalize teaching after a configurable late-period threshold.

        Rule format:
            {"type": "no_late_day",
             "max_period_index": 5,            # 0-indexed; teach beyond this = penalty
             "scope": "class"|"teacher"|"all", # whose schedule to check
             "id": <int>|null}                 # specific owner if not "all"
        """
        max_idx = int(rule.get("max_period_index", len(self._teaching_period_ids) - 1))
        scope = rule.get("scope", "all")
        target_id = rule.get("id")

        if scope == "teacher":
            owners = self._lessons_by_teacher
        elif scope == "class":
            owners = self._lessons_by_class
        else:
            # 'all' = sum over each class (roof penalty for everyone)
            owners = self._lessons_by_class

        if target_id is not None:
            owners = {target_id: owners.get(target_id, [])} if target_id in owners else {}

        busy = self._build_busy_indicators(days, owners)
        n_periods = len(self._teaching_period_ids)
        for owner_id in owners:
            for day in days:
                for i in range(max_idx + 1, n_periods):
                    # Each late period busy = 1 contributes weight to penalty.
                    self.penalties.append(busy[(owner_id, day, i)] * weight)

    def _soft_teacher_preferred_days(self, days: range, weight: int, rule: dict):
        """Penalize teaching on a teacher's non-preferred days.

        Rule format:
            {"type": "teacher_preferred_days",
             "teacher_id": <int>,
             "days": [0, 2, 4]}     # preferred day indices (Mon=0)
        """
        teacher_id = rule.get("teacher_id")
        preferred = set(rule.get("days") or [])
        if teacher_id is None or not preferred:
            return
        if teacher_id not in self._lessons_by_teacher:
            return

        busy = self._build_busy_indicators(
            days, {teacher_id: self._lessons_by_teacher[teacher_id]}
        )
        n_periods = len(self._teaching_period_ids)
        for day in days:
            if day in preferred:
                continue
            for i in range(n_periods):
                # Each unwanted-day teaching slot adds weight
                self.penalties.append(busy[(teacher_id, day, i)] * weight)

    def _soft_consecutive_blocks(self, days: range, weight: int):
        """For lessons with periods_per_week >= 2 και distribution κενό
        (= όλα 1ωρα μπλοκ), προτίμησε τα 1ωρα να γίνουν διπλά consecutive.

        Δηλαδή: για μάθημα 4 ωρών την εβδομάδα, αντί 4×1ω σκόρπια,
        προτίμησε 2×2ω (αν δεν υπάρχει explicit distribution).
        Είναι soft: αν δεν χωράνε διπλά, ο solver τα κάνει 1ωρα κανονικά.
        """
        for lesson in self.lessons:
            if lesson.periods_per_week < 2:
                continue
            if lesson.distribution and lesson.distribution.strip():
                continue  # user explicitly specified distribution — respect it

            rooms = self._get_available_rooms(lesson)
            if not rooms:
                continue

            for day in days:
                # consec_pairs[i] = 1 if lesson active at i AND i+1 (same room)
                consec_count = []
                for room in rooms:
                    for i in range(len(self.periods) - 1):
                        p1 = self.periods[i]
                        p2 = self.periods[i + 1]
                        k1 = (lesson.id, day, p1.id, room.id)
                        k2 = (lesson.id, day, p2.id, room.id)
                        if k1 in self.x and k2 in self.x:
                            pair = self.model.NewBoolVar(
                                f"consec_l{lesson.id}_d{day}_p{i}_r{room.id}"
                            )
                            self.model.Add(pair <= self.x[k1])
                            self.model.Add(pair <= self.x[k2])
                            self.model.Add(pair >= self.x[k1] + self.x[k2] - 1)
                            consec_count.append(pair)

                # Reward consecutive pairs by NEGATIVE penalty (=bonus).
                # Each pair on this day is worth `weight` toward the goal.
                for c in consec_count:
                    self.penalties.append((1 - c) * (weight // 4 if weight >= 4 else 1))

    def _soft_class_compactness(self, days: range, weight: int):
        """Penalize spreading a class's lessons across more days than
        necessary. A class with 6 lessons/week distributed over 5 days
        feels worse than 6 over 3 days."""
        n_periods = len(self._teaching_period_ids)
        for class_id, class_lessons in self._lessons_by_class.items():
            total_lessons = sum(l.periods_per_week for l in class_lessons)
            if total_lessons == 0:
                continue
            # Minimum days needed = ceil(total / n_periods)
            min_days = -(-total_lessons // n_periods)

            day_active_vars = []
            for day in days:
                vars_in_day = []
                for lesson in class_lessons:
                    for room in self._get_available_rooms(lesson):
                        for period in self.periods:
                            key = (lesson.id, day, period.id, room.id)
                            if key in self.x:
                                vars_in_day.append(self.x[key])
                if not vars_in_day:
                    continue
                day_active = self.model.NewBoolVar(
                    f"comp_c{class_id}_d{day}"
                )
                self.model.AddMaxEquality(day_active, vars_in_day)
                day_active_vars.append(day_active)

            if not day_active_vars:
                continue
            n_active_days = self.model.NewIntVar(
                0, self.days_per_week, f"comp_c{class_id}_n"
            )
            self.model.Add(n_active_days == sum(day_active_vars))
            excess = self.model.NewIntVar(
                0, self.days_per_week, f"comp_c{class_id}_x"
            )
            self.model.Add(excess >= n_active_days - min_days)
            self.model.Add(excess >= 0)
            self.penalties.append(excess * weight)

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
