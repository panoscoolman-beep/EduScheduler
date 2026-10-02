"""Τα blocks μιας κάρτας (π.χ. «2×2ωρα») σε διαφορετικές μέρες (2/10/2026).

Πριν: τίποτα δεν κρατούσε τα δύο δίωρα σε διαφορετικές μέρες — με το
«Συμπτυγμένο πρόγραμμα» ο solver τα στοίβαζε σε ΕΝΑ τετράωρο. Τώρα ισχυρή
μαλακή ποινή: διαφορετικές μέρες όποτε γίνεται, ποτέ «αδύνατο».
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import (
    Classroom, Constraint, Lesson, Period, SchoolClass, SchoolSettings, Subject, Teacher,
    TeacherAvailability, Term,
)
from backend.solver.engine import TimetableSolver


def _env(distribution="2,2", ppw=4, rules=(), n_periods=6):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(Term(id=1, name="Σενάριο", is_active=True))
    s.add(SchoolSettings(school_name="Κ", days_per_week=5))
    subj = Subject(name="Μαθηματικά", short_name="ΜΑΘ", color="#000000")
    t = Teacher(name="Τ", short_name="Τ", color="#000000")
    c = SchoolClass(name="Γ1", short_name="Γ1")
    room = Classroom(name="Α", short_name="Α")
    periods = [Period(name=f"{i + 1}η", short_name=f"{i + 1}η", start_time=f"{14 + i:02d}:00",
                      end_time=f"{14 + i:02d}:50", is_break=False, sort_order=i + 1)
               for i in range(n_periods)]
    s.add_all([subj, t, c, room, *periods])
    s.commit()
    les = Lesson(term_id=1, subject_id=subj.id, teacher_id=t.id, class_id=c.id,
                 periods_per_week=ppw, distribution=distribution)
    s.add(les)
    for rtype, weight in rules:
        s.add(Constraint(name=rtype, constraint_type="soft", category="general", weight=weight,
                         is_active=True, rule=json.dumps({"type": rtype})))
    s.commit()
    return SimpleNamespace(s=s, t=t, lesson=les, periods=periods)


PANELLINIES = (("min_teacher_gaps", 80), ("class_compactness", 70))


def _days(res):
    return sorted({x["day_of_week"] for x in res.slots})


def test_two_doubles_go_on_different_days_even_with_compactness():
    env = _env(rules=PANELLINIES)
    res = TimetableSolver(env.s, max_time_seconds=10, term_id=1).solve()
    assert res.status == "optimal" and len(res.slots) == 4
    assert len(_days(res)) == 2                                  # πριν: ένα τετράωρο, 1 μέρα


def test_double_plus_single_also_spread():
    env = _env(distribution="2,1", ppw=3, rules=PANELLINIES)
    res = TimetableSolver(env.s, max_time_seconds=10, term_id=1).solve()
    assert res.status == "optimal" and len(_days(res)) == 2


def test_blocks_still_placed_when_only_one_day_is_possible():
    """Μαλακό: αν ο καθηγητής έρχεται μόνο Δευτέρα, μπαίνουν και τα δύο εκεί."""
    env = _env(rules=PANELLINIES)
    for d in range(1, 5):
        for p in env.periods:
            env.s.add(TeacherAvailability(term_id=1, teacher_id=env.t.id, day_of_week=d,
                                          period_id=p.id, status="unavailable"))
    env.s.commit()
    for mode in ("strict", "permissive"):
        res = TimetableSolver(env.s, max_time_seconds=10, mode=mode, term_id=1).solve()
        assert res.status == "optimal" and len(res.slots) == 4 and _days(res) == [0]


def _has_sameday_vars(solver):
    return any(v.name.startswith("sameday_") for v in solver.model.Proto().variables)


def test_untouched_without_objective_or_without_multi_hour_blocks():
    """Χωρίς μαλακούς κανόνες (strict) ο solver δεν βελτιστοποιεί τίποτα → ίδιο
    μοντέλο με πριν· το ίδιο για «2» (ένα block) και «1,1,1,1» (όλα μονόωρα)."""
    cases = [("2,2", 4, ()), ("4", 4, PANELLINIES), ("1,1,1,1", 4, PANELLINIES), ("", 4, PANELLINIES),
             ("1,1,1,1,1,1", 6, PANELLINIES), ("2,2,2,2,2,2", 12, PANELLINIES)]  # blocks > μέρες
    for distribution, ppw, rules in cases:
        env = _env(distribution=distribution or None, ppw=ppw, rules=rules)
        solver = TimetableSolver(env.s, max_time_seconds=10, term_id=1)
        assert solver.solve().status == "optimal"
        assert not _has_sameday_vars(solver), distribution
