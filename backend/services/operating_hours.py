"""Ωράριο λειτουργίας: ποιες διδακτικές ώρες εμφανίζονται στα πλέγματα.

Το φροντιστήριο έχει διδακτικές ώρες 08:00–22:00, αλλά δουλεύει κυρίως
απόγευμα — τα πρωινά κελιά γέμιζαν άσκοπα το πλέγμα και τις εκτυπώσεις. Με
`school_settings.visible_from/visible_to` («14:00» / «22:00») κρύβονται.

Κανόνας ασφαλείας: μια ώρα που έχει ΤΟΠΟΘΕΤΗΜΕΝΟ μάθημα δεν κρύβεται ποτέ
(εμφανίζεται με σήμανση «εκτός ωραρίου»), ώστε να μη «χαθεί» μάθημα από την
οθόνη. Αφορά μόνο την εμφάνιση — ο solver δεν αλλάζει. Ίδιοι κανόνες με το
`TimetableHelpers.visiblePeriods` του frontend.
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


def visible_periods(periods: Iterable, window_from, window_to,
                    used_period_ids: set[int] | None = None) -> list:
    """Οι ώρες μέσα στο ωράριο + όσες έχουν τοποθετημένο μάθημα."""
    used = used_period_ids or set()
    return [p for p in periods
            if in_window(p.start_time, window_from, window_to) or p.id in used]
