"""Κανόνες χρήστη αποθηκευμένοι ως «Σκληρός (υποχρεωτικός)».

Μέχρι 2/10/2026 ο solver διάβαζε ΜΟΝΟ τους μαλακούς κανόνες: ένας κανόνας
αποθηκευμένος ως «Σκληρός» αγνοούνταν εντελώς (ούτε καν ως προτίμηση) και το
πρόγραμμα μπορούσε να τον παραβιάζει χωρίς καμία ειδοποίηση.

Κοινή ερμηνεία για τον solver (engine.py) ΚΑΙ τον Έλεγχο Εφικτότητας
(services/feasibility.py), ώστε να συμφωνούν πάντα:

* `no_late_day`, `teacher_preferred_days` → ΥΠΟΧΡΕΩΤΙΚΟΙ: τα κελιά που
  απαγορεύουν μένουν κενά για τα μαθήματα που αφορούν (ίδια επιλογή
  «ποιους αφορά» με τη μαλακή εκδοχή). Ό,τι έχει κλειδώσει ρητά ο χρήστης
  εξαιρείται, όπως στα κωλύματα/ωράριο.
* κανόνες-προτιμήσεις (κενά, ισοκατανομή, συμπτυγμένο…) → «υποχρεωτικό» δεν
  έχει νόημα (π.χ. «μηδέν κενά» σχεδόν πάντα αδύνατο): εφαρμόζονται ως
  Μαλακοί, με προειδοποίηση.
* ετικέτες των ενσωματωμένων κανόνων (seed-defaults: «Χωρίς σύγκρουση
  καθηγητή» κ.λπ.) → ισχύουν ήδη πάντα (H2–H5), τίποτα επιπλέον.
* οτιδήποτε άλλο → αγνοείται, με προειδοποίηση (όχι σιωπηλά).

Καθαρό module (χωρίς OR-Tools / DB) — unit-testable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

ENFORCEABLE_TYPES = frozenset({"no_late_day", "teacher_preferred_days"})
SOFT_ONLY_TYPES = frozenset({
    "min_teacher_gaps", "min_class_gaps", "subject_distribution",
    "teacher_day_balance", "consecutive_blocks_preference", "class_compactness",
})
BUILTIN_TYPES = frozenset({
    "no_teacher_clash", "no_class_clash", "no_room_clash",
    "curriculum_fulfillment", "teacher_availability",
})


@dataclass(frozen=True)
class HardRule:
    """Ένας υποχρεωτικός κανόνας που ο solver επιβάλλει."""

    name: str
    kind: str                         # no_late_day | teacher_preferred_days
    scope: str = "all"                # no_late_day: teacher | class | all
    target_id: int | None = None      # no_late_day: συγκεκριμένο τμήμα/καθηγητής
    max_period_index: int | None = None
    teacher_id: int | None = None     # teacher_preferred_days
    days: frozenset = field(default_factory=frozenset)

    def covers(self, lesson) -> bool:
        """Αφορά αυτό το μάθημα-κάρτα; (ίδια επιλογή με τη μαλακή εκδοχή)"""
        if self.kind == "teacher_preferred_days":
            return lesson.teacher_id == self.teacher_id
        owner = lesson.teacher_id if self.scope == "teacher" else lesson.class_id
        return self.target_id is None or owner == self.target_id

    def forbids(self, day: int, period_index: int) -> bool:
        """Απαγορεύει (μέρα, θέση ώρας 0-based στις διδακτικές ώρες);"""
        if self.kind == "teacher_preferred_days":
            return day not in self.days
        return self.max_period_index is not None and period_index > self.max_period_index

    @property
    def label(self) -> str:
        return f"«{self.name}»"


@dataclass
class ParsedRules:
    hard_rules: list[HardRule] = field(default_factory=list)
    # Σκληρές γραμμές τύπου-προτίμησης: εφαρμόζονται ως Μαλακές.
    as_soft: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _as_int(value) -> int:
    if isinstance(value, bool):
        raise ValueError("bool")
    return int(value)


def parse_constraints(constraints) -> ParsedRules:
    """Χωρίζει τους ενεργούς ΣΚΛΗΡΟΥΣ κανόνες. Οι μαλακοί δεν αγγίζονται εδώ
    (ο solver τους εφαρμόζει όπως πάντα). Δεν πετά ποτέ εξαίρεση: άκυρος
    σκληρός κανόνας → προειδοποίηση, όχι «Σφάλμα solver»."""
    out = ParsedRules()
    for c in constraints:
        if c.constraint_type != "hard":
            continue
        name = c.name or f"#{c.id}"
        try:
            rule = json.loads(c.rule) if isinstance(c.rule, str) else c.rule
        except (TypeError, ValueError):
            rule = None
        if not isinstance(rule, dict):
            out.warnings.append(
                f"Ο σκληρός κανόνας «{name}» δεν διαβάζεται (άκυρος κανόνας) και αγνοείται.")
            continue
        rtype = rule.get("type")
        if rtype in BUILTIN_TYPES:
            continue
        if rtype in SOFT_ONLY_TYPES:
            out.as_soft.append(c)
            out.warnings.append(
                f"Ο κανόνας «{name}» είναι «Σκληρός», αλλά αυτό το είδος κανόνα δεν μπορεί "
                "να είναι υποχρεωτικό — εφαρμόζεται ως Μαλακός (προτίμηση).")
            continue
        if rtype not in ENFORCEABLE_TYPES:
            out.warnings.append(
                f"Ο σκληρός κανόνας «{name}» (τύπος «{rtype}») δεν υποστηρίζεται από τον "
                "solver και αγνοείται.")
            continue
        try:
            if rtype == "no_late_day":
                max_idx = rule.get("max_period_index")
                target = rule.get("id")
                out.hard_rules.append(HardRule(
                    name=name, kind=rtype, scope=rule.get("scope") or "all",
                    target_id=None if target is None else _as_int(target),
                    max_period_index=None if max_idx is None else _as_int(max_idx),
                ))
            else:  # teacher_preferred_days
                teacher_id, days = rule.get("teacher_id"), rule.get("days") or []
                if teacher_id is None or not days:
                    out.warnings.append(
                        f"Ο σκληρός κανόνας «{name}» δεν έχει καθηγητή ή ημέρες και αγνοείται.")
                    continue
                out.hard_rules.append(HardRule(
                    name=name, kind=rtype, teacher_id=_as_int(teacher_id),
                    days=frozenset(_as_int(d) for d in days),
                ))
        except (TypeError, ValueError):
            out.warnings.append(
                f"Ο σκληρός κανόνας «{name}» έχει άκυρες παραμέτρους και αγνοείται.")
    return out


def phrase(rules: list[HardRule]) -> str:
    """«με τον σκληρό κανόνα «Χ»» / «με τους σκληρούς κανόνες «Χ», «Υ»»."""
    labels = list(dict.fromkeys(r.label for r in rules))
    if len(labels) == 1:
        return f"με τον σκληρό κανόνα {labels[0]}"
    return "με τους σκληρούς κανόνες " + ", ".join(labels)
