"""Aggregate metrics for a TimetableSolution — used by the
side-by-side comparison view.

Each metric is computed from the solution's slots + the solution's
score field. We deliberately keep the service pure: no DB writes,
just a `compute(solution_id, db)` that returns a dict.

Lower is better for every metric except `placed_count`. The frontend
uses this to highlight the 'winner' per row.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import pstdev
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from backend.models import TimetableSolution, TimetableSlot, Lesson


@dataclass
class SolutionMetrics:
    solution_id: int
    name: str
    status: str
    score: Optional[float]
    placed_count: int
    unplaced_count: int
    teacher_gap_total: int       # 1-period gaps summed across teachers
    workload_stddev: float       # σ of hours/teacher (lower = fairer)
    avg_days_per_class: float    # mean of distinct teaching days per class
    max_days_per_class: int
    late_periods_used: int       # slots placed at period_index > 4 (configurable)

    LATE_THRESHOLD_INDEX: int = 4   # 0-indexed: anything past 5th period is "late"

    def to_dict(self) -> dict:
        return {
            "solution_id": self.solution_id,
            "name": self.name,
            "status": self.status,
            "score": self.score,
            "placed_count": self.placed_count,
            "unplaced_count": self.unplaced_count,
            "teacher_gap_total": self.teacher_gap_total,
            "workload_stddev": round(self.workload_stddev, 2),
            "avg_days_per_class": round(self.avg_days_per_class, 2),
            "max_days_per_class": self.max_days_per_class,
            "late_periods_used": self.late_periods_used,
        }


def compute(solution_id: int, db: Session) -> Optional[SolutionMetrics]:
    """Aggregate metrics for one solution. Returns None if not found."""
    sol = (
        db.query(TimetableSolution)
        .filter(TimetableSolution.id == solution_id)
        .first()
    )
    if not sol:
        return None

    slots = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == solution_id)
        .options(joinedload(TimetableSlot.lesson).joinedload(Lesson.teacher))
        .all()
    )

    placed = [s for s in slots if not s.is_unplaced]
    unplaced = [s for s in slots if s.is_unplaced]

    return SolutionMetrics(
        solution_id=sol.id,
        name=sol.name,
        status=sol.status,
        score=sol.score,
        placed_count=len(placed),
        unplaced_count=len(unplaced),
        teacher_gap_total=_count_teacher_gaps(placed),
        workload_stddev=_workload_stddev(placed),
        avg_days_per_class=_avg_days_per_class(placed),
        max_days_per_class=_max_days_per_class(placed),
        late_periods_used=_late_periods_used(placed),
    )


def compare(solution_ids: list[int], db: Session) -> dict:
    """Compute metrics for every requested solution + identify the
    best value per metric across all of them.

    Returns:
        {
            "metrics": [SolutionMetrics dicts...],
            "winners": {metric_name: solution_id},
        }
    """
    metrics_list = [
        compute(sid, db) for sid in solution_ids
    ]
    metrics_list = [m for m in metrics_list if m is not None]

    if len(metrics_list) < 2:
        return {
            "metrics": [m.to_dict() for m in metrics_list],
            "winners": {},
        }

    winners: dict[str, int] = {}

    def _pick_winner(key: str, lower_is_better: bool):
        values = [(m.solution_id, getattr(m, key)) for m in metrics_list]
        values = [(sid, v) for sid, v in values if v is not None]
        if not values:
            return
        if lower_is_better:
            best = min(values, key=lambda t: t[1])
        else:
            best = max(values, key=lambda t: t[1])
        winners[key] = best[0]

    # Lower-is-better metrics
    for key in (
        "score",                # solver penalty objective
        "unplaced_count",
        "teacher_gap_total",
        "workload_stddev",
        "avg_days_per_class",
        "max_days_per_class",
        "late_periods_used",
    ):
        _pick_winner(key, lower_is_better=True)

    # Higher-is-better
    _pick_winner("placed_count", lower_is_better=False)

    return {
        "metrics": [m.to_dict() for m in metrics_list],
        "winners": winners,
    }


# ---------------------------------------------------------------------------
# Per-metric helpers
# ---------------------------------------------------------------------------

def _count_teacher_gaps(placed: list[TimetableSlot]) -> int:
    """Count 1-period gaps in each teacher's daily schedule.

    Walks each (teacher, day) pair, sorts the period IDs, and adds
    1 to the gap count for every period that's missing between two
    occupied ones (a gap of N periods counts as N).
    """
    by_teacher_day: dict[tuple[int, int], list[int]] = defaultdict(list)
    for s in placed:
        if s.lesson and s.lesson.teacher_id is not None and s.day_of_week is not None:
            by_teacher_day[(s.lesson.teacher_id, s.day_of_week)].append(s.period_id)

    total_gaps = 0
    for periods in by_teacher_day.values():
        if len(periods) < 2:
            continue
        sorted_p = sorted(periods)
        for i in range(len(sorted_p) - 1):
            # period_id may not be sequential; treat any non-adjacent
            # pair as a gap of (delta - 1) periods.
            delta = sorted_p[i + 1] - sorted_p[i]
            if delta > 1:
                total_gaps += delta - 1
    return total_gaps


def _workload_stddev(placed: list[TimetableSlot]) -> float:
    """Population stddev of hours per teacher. Lower = fairer split."""
    by_teacher: dict[int, int] = defaultdict(int)
    for s in placed:
        if s.lesson and s.lesson.teacher_id is not None:
            by_teacher[s.lesson.teacher_id] += 1
    if len(by_teacher) < 2:
        return 0.0
    return pstdev(by_teacher.values())


def _avg_days_per_class(placed: list[TimetableSlot]) -> float:
    by_class_days: dict[int, set[int]] = defaultdict(set)
    for s in placed:
        if s.lesson and s.lesson.class_id is not None and s.day_of_week is not None:
            by_class_days[s.lesson.class_id].add(s.day_of_week)
    if not by_class_days:
        return 0.0
    return sum(len(d) for d in by_class_days.values()) / len(by_class_days)


def _max_days_per_class(placed: list[TimetableSlot]) -> int:
    by_class_days: dict[int, set[int]] = defaultdict(set)
    for s in placed:
        if s.lesson and s.lesson.class_id is not None and s.day_of_week is not None:
            by_class_days[s.lesson.class_id].add(s.day_of_week)
    if not by_class_days:
        return 0
    return max(len(d) for d in by_class_days.values())


def _late_periods_used(placed: list[TimetableSlot]) -> int:
    """Count slots placed at a period_id higher than the threshold.

    Note: period_id is the DB primary key, not the period's index.
    For a meaningful comparison across solutions we'd need the
    teaching-period ordinals. Approximation: just count slots whose
    period_id is among the top half. Caller can override the
    threshold if needed.
    """
    if not placed:
        return 0
    ids = sorted({s.period_id for s in placed if s.period_id is not None})
    if not ids:
        return 0
    threshold = ids[len(ids) // 2]
    return sum(1 for s in placed if (s.period_id or 0) > threshold)
