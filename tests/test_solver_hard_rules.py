"""«Σκληρός (υποχρεωτικός)» κανόνας χρήστη και «Max/Εβδ.» καθηγητή (2/10/2026).

Πριν: ο solver διάβαζε ΜΟΝΟ τους μαλακούς κανόνες — ένας κανόνας
αποθηκευμένος ως «Σκληρός» αγνοούνταν εντελώς (ούτε καν ως προτίμηση), και το
«Max/Εβδ.» του καθηγητή δεν το κοιτούσε καθόλου. Τώρα επιβάλλονται, και ο
Έλεγχος Εφικτότητας / το μήνυμα αποτυχίας / η Παλέτα λένε ονομαστικά ποιος
κανόνας ή καθηγητής φταίει. Οι αποθηκευμένες λύσεις δεν αγγίζονται.
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
    TeacherAvailability, Term, TimetableSlot, TimetableSolution,
)
from backend.services.feasibility import check_feasibility
from backend.solver.engine import TimetableSolver
from backend.solver.hard_rules import parse_constraints


def _env(n_periods=6, days=5, n_rooms=1, teacher_kw=None):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(Term(id=1, name="Σενάριο", is_active=True))
    s.add(SchoolSettings(school_name="Κ", days_per_week=days))
    subj = Subject(name="Φυσική", short_name="ΦΥΣ", color="#000000")
    teacher = Teacher(name="Παπαδόπουλος", short_name="ΠΑΠ", color="#000000", **(teacher_kw or {}))
    c1, c2 = SchoolClass(name="Γ1", short_name="Γ1"), SchoolClass(name="Γ2", short_name="Γ2")
    rooms = [Classroom(name=f"Α{i}", short_name=f"Α{i}") for i in range(n_rooms)]
    periods = [Period(name=f"{i + 1}η", short_name=f"{i + 1}η", start_time=f"{14 + i:02d}:00",
                      end_time=f"{14 + i:02d}:50", is_break=False, sort_order=i + 1)
               for i in range(n_periods)]
    s.add_all([subj, teacher, c1, c2, *rooms, *periods])
    s.commit()
    return SimpleNamespace(s=s, subj=subj, t=teacher, c1=c1, c2=c2, rooms=rooms, periods=periods)


def _lesson(env, ppw, cls=None, teacher=None, distribution=None):
    les = Lesson(term_id=1, subject_id=env.subj.id, teacher_id=(teacher or env.t).id,
                 class_id=(cls or env.c1).id, periods_per_week=ppw, distribution=distribution)
    env.s.add(les)
    env.s.commit()
    return les


def _rule(env, name, ctype="hard", weight=100, **rule):
    env.s.add(Constraint(name=name, constraint_type=ctype, category="general", weight=weight,
                         is_active=True, rule=json.dumps(rule)))
    env.s.commit()


def _unavailable(env, teacher, cells):
    for day, period in cells:
        env.s.add(TeacherAvailability(term_id=1, teacher_id=teacher.id, day_of_week=day,
                                      period_id=period.id, status="unavailable"))
    env.s.commit()


def _solve(env, mode="strict", locked=None):
    return TimetableSolver(env.s, max_time_seconds=10, mode=mode, locked_assignments=locked,
                           term_id=1).solve()


def _idx(env):
    return {p.id: i for i, p in enumerate(env.periods)}


# ───────────────────────── parse_constraints ─────────────────────────

def _c(name, ctype, rule):
    return Constraint(name=name, constraint_type=ctype, category="general", weight=50,
                      is_active=True, rule=rule if isinstance(rule, str) else json.dumps(rule))


def test_parse_constraints_classifies_every_kind_of_hard_row():
    rows = [
        _c("Μαλακός", "soft", {"type": "no_late_day", "max_period_index": 1}),
        _c("Χωρίς σύγκρουση καθηγητή", "hard", {"type": "no_teacher_clash"}),
        _c("Όχι αργά", "hard", {"type": "no_late_day", "max_period_index": 2, "scope": "class", "id": 7}),
        _c("Μόνο Δευτέρα", "hard", {"type": "teacher_preferred_days", "teacher_id": 3, "days": [0]}),
        _c("Κενά", "hard", {"type": "min_teacher_gaps"}),
        _c("Δικός μου", "hard", {"type": "custom"}),
        _c("Χαλασμένος", "hard", "{όχι json"),
        _c("Άδειες μέρες", "hard", {"type": "teacher_preferred_days", "teacher_id": 3, "days": []}),
        _c("Λάθος ώρα", "hard", {"type": "no_late_day", "max_period_index": "x"}),
    ]
    parsed = parse_constraints(rows)
    kinds = [(r.name, r.kind) for r in parsed.hard_rules]
    assert kinds == [("Όχι αργά", "no_late_day"), ("Μόνο Δευτέρα", "teacher_preferred_days")]
    assert parsed.hard_rules[0].target_id == 7 and parsed.hard_rules[0].max_period_index == 2
    assert parsed.hard_rules[1].days == frozenset({0})
    assert [c.name for c in parsed.as_soft] == ["Κενά"]
    text = " | ".join(parsed.warnings)
    for name in ("Κενά", "Δικός μου", "Χαλασμένος", "Άδειες μέρες", "Λάθος ώρα"):
        assert f"«{name}»" in text
    # ετικέτες ενσωματωμένων κανόνων και μαλακοί κανόνες: καμία προειδοποίηση
    assert "«Χωρίς σύγκρουση καθηγητή»" not in text and "«Μαλακός»" not in text
    assert len(parsed.warnings) == 5


# ───────────────────────── teacher_preferred_days (hard) ─────────────────────────

def test_hard_preferred_days_beats_a_soft_preference_for_other_days():
    """Πριν: ο σκληρός «μόνο Δευ/Τρί» αγνοούνταν και ο μαλακός «Τετ–Παρ» τα έστελνε εκεί."""
    env = _env()
    _lesson(env, 4)
    _rule(env, "Μόνο Δευ-Τρί", teacher_id=env.t.id, days=[0, 1], type="teacher_preferred_days")
    _rule(env, "Προτιμά Τετ-Παρ", ctype="soft", teacher_id=env.t.id, days=[2, 3, 4],
          type="teacher_preferred_days")
    res = _solve(env)
    assert res.status == "optimal", res.message
    assert len(res.slots) == 4
    assert {x["day_of_week"] for x in res.slots} <= {0, 1}


def test_hard_preferred_days_that_cannot_be_met_is_infeasible_and_named():
    from backend.routers.solver import solver_status
    from backend.services.solver_jobs import _persist_solver_result

    env = _env()
    _lesson(env, 2)
    _unavailable(env, env.t, [(0, p) for p in env.periods])          # Δευτέρα κώλυμα
    _rule(env, "Μόνο Δευτέρα", teacher_id=env.t.id, days=[0], type="teacher_preferred_days")
    res = _solve(env)
    assert res.status == "infeasible"
    assert "«Μόνο Δευτέρα»" in res.message

    report = check_feasibility(env.s, term_id=1).to_dict()
    assert report["feasible"] is False
    assert any("Παπαδόπουλος" in e and "με τον σκληρό κανόνα «Μόνο Δευτέρα»" in e
               for e in report["errors"]), report["errors"]
    assert any("σκληρό" in s for s in report["suggestions"])

    sol = TimetableSolution(name="Π", status="generating", term_id=1)
    env.s.add(sol)
    env.s.commit()
    _persist_solver_result(env.s, sol, res)
    status = solver_status(sol.id, db=env.s)
    assert status.status == "infeasible" and "«Μόνο Δευτέρα»" in status.message


def test_hard_preferred_days_permissive_parks_the_hours_with_the_rule_name():
    env = _env()
    _lesson(env, 2)
    _unavailable(env, env.t, [(0, p) for p in env.periods])
    _rule(env, "Μόνο Δευτέρα", teacher_id=env.t.id, days=[0], type="teacher_preferred_days")
    res = _solve(env, mode="permissive")
    assert res.status in ("optimal", "feasible")
    assert not res.slots
    assert sum(e["hours"] for e in res.unplaced) == 2
    assert all("«Μόνο Δευτέρα»" in e["reason"] for e in res.unplaced)


# ───────────────────────── no_late_day (hard) ─────────────────────────

def test_hard_no_late_day_for_a_class_is_enforced_and_named():
    """Γ1 «όχι μετά τη 2η ώρα», ο καθηγητής έχει κώλυμα 1η–2η: αδύνατο για το Γ1
    (πριν: «βέλτιστη λύση» με τις ώρες αργά). Το Γ2 δεν αφορά ο κανόνας."""
    env = _env()
    _lesson(env, 2, cls=env.c1)
    _lesson(env, 2, cls=env.c2)
    _unavailable(env, env.t, [(d, p) for d in range(5) for p in env.periods[:2]])
    _rule(env, "Γ1 νωρίς", type="no_late_day", max_period_index=1, scope="class", id=env.c1.id)
    assert _solve(env).status == "infeasible"

    res = _solve(env, mode="permissive")
    placed_classes = {env.s.get(Lesson, x["lesson_id"]).class_id for x in res.slots}
    assert placed_classes == {env.c2.id} and len(res.slots) == 2
    assert sum(e["hours"] for e in res.unplaced) == 2
    assert all("«Γ1 νωρίς»" in e["reason"] for e in res.unplaced)

    report = check_feasibility(env.s, term_id=1).to_dict()
    assert any(e.startswith("Φυσική (Γ1): χρειάζεται 2 ώρες αλλά χωράνε μόνο 0")
               and "«Γ1 νωρίς»" in e for e in report["errors"]), report["errors"]
    assert not any("Γ2" in e for e in report["errors"])


def test_hard_no_late_day_keeps_every_hour_early():
    """Δευ–Πέμ ο καθηγητής έχει κώλυμα 1η–3η και (μαλακά) προτιμά Δευ–Πέμ: χωρίς
    τον σκληρό κανόνα οι ώρες πήγαιναν Δευ–Πέμ ΑΡΓΑ· με αυτόν, Παρασκευή νωρίς."""
    env = _env(n_rooms=2)
    _lesson(env, 3, cls=env.c1)
    _unavailable(env, env.t, [(d, p) for d in range(4) for p in env.periods[:3]])
    _rule(env, "Όλοι ως 3η", type="no_late_day", max_period_index=2, scope="all")
    _rule(env, "Προτιμά Δευ-Πέμ", ctype="soft", teacher_id=env.t.id, days=[0, 1, 2, 3],
          type="teacher_preferred_days")
    res = _solve(env)
    assert res.status == "optimal" and len(res.slots) == 3
    idx = _idx(env)
    assert sorted((x["day_of_week"], idx[x["period_id"]]) for x in res.slots) == [(4, 0), (4, 1), (4, 2)]


def test_locked_hour_is_exempt_from_a_hard_rule():
    """Όπως στα κωλύματα/ωράριο: ό,τι κλείδωσε ρητά ο χρήστης μένει."""
    env = _env()
    les = _lesson(env, 3)
    _rule(env, "Ως 2η", type="no_late_day", max_period_index=1, scope="all")
    locked = [{"lesson_id": les.id, "day_of_week": 2, "period_id": env.periods[5].id,
               "classroom_id": env.rooms[0].id}]
    res = _solve(env, locked=locked)
    assert res.status in ("optimal", "feasible"), res.message
    idx = _idx(env)
    cells = sorted((x["day_of_week"], idx[x["period_id"]]) for x in res.slots)
    assert (2, 5) in cells
    assert all(i <= 1 for d, i in cells if (d, i) != (2, 5))


# ───────────────────────── preference types / broken rows ─────────────────────────

def test_hard_preference_rule_is_applied_as_soft_with_a_warning():
    """«Ισοκατανομή» ως Σκληρός: δεν γίνεται υποχρεωτικός, αλλά ούτε αγνοείται πια."""
    env = _env(n_periods=3, days=1)
    _lesson(env, 3)
    _rule(env, "Ισοκατανομή", weight=40, type="subject_distribution")
    res = _solve(env)
    assert res.status == "optimal"
    assert res.score == 2 * 40                                   # όπως αν ήταν Μαλακός
    assert any("«Ισοκατανομή»" in w and "Μαλακός" in w for w in res.stats["warnings"])


def test_unsupported_and_broken_hard_rows_never_crash_and_are_reported():
    env = _env()
    _lesson(env, 2)
    _rule(env, "Δικός μου", type="custom")
    env.s.add(Constraint(name="Χαλασμένος", constraint_type="hard", category="general", weight=50,
                         is_active=True, rule="{όχι json"))
    env.s.commit()
    res = _solve(env)
    assert res.status == "optimal" and len(res.slots) == 2
    warnings = " | ".join(res.stats["warnings"])
    assert "«Δικός μου»" in warnings and "«Χαλασμένος»" in warnings
    report = check_feasibility(env.s, term_id=1).to_dict()
    assert report["feasible"] is True
    assert any("«Δικός μου»" in w for w in report["warnings"])


def test_seeded_builtin_hard_rows_change_nothing():
    """Οι ετικέτες «Χωρίς σύγκρουση…» ισχύουν ήδη πάντα: ίδιο μοντέλο, καμία προειδοποίηση."""
    def model_bytes(with_rows: bool):
        env = _env()
        _lesson(env, 3)
        if with_rows:
            for rtype in ("no_teacher_clash", "no_class_clash", "no_room_clash",
                          "curriculum_fulfillment", "teacher_availability"):
                _rule(env, rtype, type=rtype)
        solver = TimetableSolver(env.s, max_time_seconds=10, term_id=1)
        res = solver.solve()
        return res, solver.model.Proto().SerializeToString()

    res_a, proto_a = model_bytes(False)
    res_b, proto_b = model_bytes(True)
    assert proto_a == proto_b
    assert "warnings" not in res_b.stats


# ───────────────────────── «Max/Εβδ.» (H6b) ─────────────────────────

def test_weekly_max_strict_is_infeasible_and_names_the_teacher():
    env = _env(teacher_kw={"max_periods_per_week": 3})
    _lesson(env, 3, cls=env.c1)
    _lesson(env, 3, cls=env.c2)
    res = _solve(env)
    assert res.status == "infeasible"                            # πριν: «βέλτιστη», 6 ώρες
    assert "Παπαδόπουλος" in res.message and "«Max/Εβδ.» 3" in res.message
    report = check_feasibility(env.s, term_id=1).to_dict()
    assert "Καθηγητής Παπαδόπουλος: έχει 6 ώρες μαθημάτων αλλά «Max/Εβδ.» 3" in report["errors"]
    assert any("«Max/Εβδ.»" in s for s in report["suggestions"])


def test_weekly_max_permissive_parks_the_excess_with_the_reason():
    env = _env(teacher_kw={"max_periods_per_week": 3})
    _lesson(env, 3, cls=env.c1)
    _lesson(env, 3, cls=env.c2)
    res = _solve(env, mode="permissive")
    assert res.status in ("optimal", "feasible")
    assert len(res.slots) == 3                                   # πριν: 6
    assert sum(e["hours"] for e in res.unplaced) == 3
    assert all("«Max/Εβδ.» 3" in e["reason"] for e in res.unplaced)
    assert any("Max/Εβδ." in w for w in res.stats["warnings"])


def test_weekly_max_never_drops_hours_the_user_locked():
    """4 κλειδωμένες ώρες πάνω από όριο 3: μένουν· οι νέες ώρες πάνε στην Παλέτα."""
    env = _env(teacher_kw={"max_periods_per_week": 3})
    les = _lesson(env, 4, cls=env.c1)
    _lesson(env, 2, cls=env.c2)
    locked = [{"lesson_id": les.id, "day_of_week": d, "period_id": env.periods[0].id,
               "classroom_id": env.rooms[0].id} for d in range(4)]
    res = _solve(env, mode="permissive", locked=locked)
    assert res.status in ("optimal", "feasible")
    got = {(x["lesson_id"], x["day_of_week"], x["period_id"]) for x in res.slots}
    assert all((e["lesson_id"], e["day_of_week"], e["period_id"]) in got for e in locked)
    assert len(res.slots) == 4 and sum(e["hours"] for e in res.unplaced) == 2


def test_weekly_max_that_cannot_bind_leaves_the_model_unchanged():
    def proto(cap):
        env = _env(teacher_kw={"max_periods_per_week": cap})
        _lesson(env, 3, cls=env.c1)
        _lesson(env, 2, cls=env.c2)
        solver = TimetableSolver(env.s, max_time_seconds=10, term_id=1)
        assert solver.solve().status == "optimal"
        return solver.model.Proto().SerializeToString()

    assert proto(None) == proto(5) == proto(40)


def test_weekly_max_feasibility_keeps_other_messages_unchanged():
    """Όταν κόβει η διαθεσιμότητα (όχι το Max/Εβδ.), το μήνυμα μένει το παλιό."""
    env = _env(teacher_kw={"max_periods_per_week": 20})
    _lesson(env, 8)
    _unavailable(env, env.t, [(d, p) for d in range(4) for p in env.periods])
    report = check_feasibility(env.s, term_id=1).to_dict()
    assert report["errors"] == [
        "Καθηγητής Παπαδόπουλος: χρειάζεται 8 ώρες αλλά η διαθεσιμότητά του επιτρέπει μόνο 6"]


def test_status_message_lists_solver_warnings():
    from backend.routers.solver import solver_status
    from backend.services.solver_jobs import _persist_solver_result

    env = _env(teacher_kw={"max_periods_per_week": 3})
    _lesson(env, 3, cls=env.c1)
    _lesson(env, 3, cls=env.c2)
    sol = TimetableSolution(name="Π", status="generating", term_id=1)
    env.s.add(sol)
    env.s.commit()
    _persist_solver_result(env.s, sol, _solve(env, mode="permissive"))
    msg = solver_status(sol.id, db=env.s).message
    assert msg.startswith("Ολοκληρώθηκε") and "⚠️" in msg and "«Max/Εβδ.» 3" in msg
    rows = env.s.query(TimetableSlot).filter(TimetableSlot.solution_id == sol.id).all()
    assert sum(1 for r in rows if r.is_unplaced) == 3
