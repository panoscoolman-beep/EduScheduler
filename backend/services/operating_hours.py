"""Ωράριο λειτουργίας: ποιες διδακτικές ώρες εμφανίζονται στα πλέγματα.

Το φροντιστήριο έχει διδακτικές ώρες 08:00–22:00, αλλά δουλεύει κυρίως
απόγευμα — τα πρωινά κελιά γέμιζαν άσκοπα το πλέγμα και τις εκτυπώσεις. Με
`school_settings.visible_from/visible_to` («14:00» / «22:00») κρύβονται.

Κανόνας ασφαλείας: μια ώρα που έχει ΤΟΠΟΘΕΤΗΜΕΝΟ μάθημα δεν κρύβεται ποτέ
(εμφανίζεται με σήμανση «εκτός ωραρίου»), ώστε να μη «χαθεί» μάθημα από την
οθόνη. Ίδιοι κανόνες με το `TimetableHelpers.visiblePeriods` του frontend.

Από 18/9/2026 το ωράριο δεσμεύει ΚΑΙ τον solver (`closed_cells`): δεν
τοποθετεί μάθημα εκτός ωραρίου της μέρας, εκτός αν είναι ρητά κλειδωμένο.
"""
from __future__ import annotations

import re
from typing import Iterable

_TIME = re.compile(r"^(\d{1,2}):(\d{2})")


def to_minutes(value) -> int | None:
    match = _TIME.match(str(value or "").strip())
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


def in_window(start_time, window_from, window_to) -> bool:
    """Ξεκινά μέσα στο [from, to); χωρίς ωράριο ή άγνωστη ώρα → μέσα."""
    start = to_minutes(start_time)
    lo, hi = to_minutes(window_from), to_minutes(window_to)
    if start is None:
        return True
    if lo is not None and start < lo:
        return False
    if hi is not None and start >= hi:
        return False
    return True


SATURDAY = 5


def day_window(settings, day: int) -> tuple:
    """(από, έως) μιας ημέρας: το Σάββατο έχει δικό του ωράριο αν έχει οριστεί."""
    if day == SATURDAY and (getattr(settings, "saturday_from", None)
                            or getattr(settings, "saturday_to", None)):
        return settings.saturday_from, settings.saturday_to
    return getattr(settings, "visible_from", None), getattr(settings, "visible_to", None)


def closed_cells(settings, periods: Iterable, days_per_week: int) -> set[tuple[int, int]]:
    """(μέρα, period_id) εκτός ωραρίου λειτουργίας — κενό αν δεν έχει οριστεί ωράριο."""
    if not has_any_window(settings):
        return set()
    periods = list(periods)
    out = set()
    for day in range(days_per_week):
        lo, hi = day_window(settings, day)
        out |= {(day, p.id) for p in periods if not in_window(p.start_time, lo, hi)}
    return out


def has_any_window(settings) -> bool:
    return bool(settings and any(getattr(settings, f, None) for f in
                                 ("visible_from", "visible_to", "saturday_from", "saturday_to")))


def visible_periods_for_days(periods: Iterable, windows: list[tuple],
                             used_period_ids: set[int] | None = None) -> list:
    """Γραμμή φαίνεται αν είναι ανοιχτή ΕΣΤΩ μία ημέρα ή αν έχει μάθημα."""
    used = used_period_ids or set()
    return [p for p in periods
            if p.id in used or any(in_window(p.start_time, lo, hi) for lo, hi in windows)]


def visible_periods(periods: Iterable, window_from, window_to,
                    used_period_ids: set[int] | None = None) -> list:
    """Οι ώρες μέσα στο ωράριο + όσες έχουν τοποθετημένο μάθημα."""
    used = used_period_ids or set()
    return [p for p in periods
            if in_window(p.start_time, window_from, window_to) or p.id in used]
