"""Φίλτρο λίστας μαθητών (τάξη / κατεύθυνση / αναζήτηση) — pure, χωρίς βάση.

Οι ΙΔΙΟΙ κανόνες με το frontend (`frontend/js/views/students_helpers.js`),
ώστε η εκτύπωση και η εξαγωγή να βγάζουν ακριβώς ό,τι βλέπει ο χρήστης στην
οθόνη:
- μέσα σε κάθε ομάδα «Η» (Β΄ ή Γ΄ Λυκείου), ανάμεσα στις ομάδες «ΚΑΙ»·
- η κενή τιμή στις τάξεις σημαίνει «Χωρίς τάξη»·
- η αναζήτηση αγνοεί τόνους/κεφαλαία και κάθε λέξη της πρέπει να βρεθεί σε
  επώνυμο, όνομα, email ή τηλέφωνο.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Iterable

NO_GRADE_LABEL = "Χωρίς τάξη"


def normalize(value: str | None) -> str:
    """Χωρίς τόνους/διαλυτικά, πεζά, τελικό ς → σ."""
    decomposed = unicodedata.normalize("NFD", value or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.lower().replace("ς", "σ").strip()


def _clean(values: Iterable[str] | None, *, keep_empty: bool) -> tuple[str, ...]:
    out: list[str] = []
    for v in values or ():
        v = (v or "").strip()
        if (v or keep_empty) and v not in out:
            out.append(v)
    return tuple(out)


@dataclass(frozen=True)
class StudentFilter:
    grades: tuple[str, ...] = ()
    tracks: tuple[str, ...] = ()
    search: str = ""

    @classmethod
    def from_query(
        cls,
        grades: Iterable[str] | None = None,
        tracks: Iterable[str] | None = None,
        search: str | None = None,
    ) -> "StudentFilter":
        # Στις τάξεις το "" είναι έγκυρη επιλογή («Χωρίς τάξη»)· στις
        # κατευθύνσεις ένα κενό δεν σημαίνει τίποτα και αγνοείται.
        return cls(
            grades=_clean(grades, keep_empty=True),
            tracks=_clean(tracks, keep_empty=False),
            search=(search or "").strip(),
        )

    def is_active(self) -> bool:
        return bool(self.grades or self.tracks or normalize(self.search))

    def matches(self, student) -> bool:
        grade = (getattr(student, "grade", None) or "").strip()
        track = (getattr(student, "track", None) or "").strip()
        if self.grades and grade not in self.grades:
            return False
        if self.tracks and track not in self.tracks:
            return False
        return self._matches_search(student)

    def _matches_search(self, student) -> bool:
        words = normalize(self.search).split()
        if not words:
            return True
        hay = normalize(" ".join(
            getattr(student, field, None) or ""
            for field in ("last_name", "first_name", "email", "phone")
        ))
        return all(w in hay for w in words)

    def apply(self, students: Iterable) -> list:
        """Κρατά τη σειρά εισόδου (ο καλών ταξινομεί)."""
        return [s for s in students if self.matches(s)]

    def summary(self) -> str:
        """Ανθρώπινη περιγραφή για την κεφαλίδα της εκτύπωσης ('' αν δεν ισχύει)."""
        parts = []
        if self.grades:
            parts.append("Τάξη: " + ", ".join(g or NO_GRADE_LABEL for g in self.grades))
        if self.tracks:
            parts.append("Κατεύθυνση / Τομέας: " + ", ".join(self.tracks))
        if self.search:
            parts.append(f"Αναζήτηση: «{self.search}»")
        return " · ".join(parts)

    def query_params(self) -> list[tuple[str, str]]:
        """Για να ξαναχτιστεί ένα URL με τα ίδια φίλτρα (π.χ. αλλαγή ταξινόμησης)."""
        params = [("grade", g) for g in self.grades]
        params += [("track", t) for t in self.tracks]
        if self.search:
            params.append(("q", self.search))
        return params
