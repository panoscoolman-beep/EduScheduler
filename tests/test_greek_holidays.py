"""Tests για τον υπολογισμό ελληνικών αργιών (ICS EXDATE)."""
from __future__ import annotations

import datetime

from backend.services.greek_holidays import holidays_in_range, orthodox_easter


def test_orthodox_easter_known_years():
    # Δημοσιευμένες ημερομηνίες ορθόδοξου Πάσχα.
    assert orthodox_easter(2025) == datetime.date(2025, 4, 20)
    assert orthodox_easter(2026) == datetime.date(2026, 4, 12)
    assert orthodox_easter(2027) == datetime.date(2027, 5, 2)


def test_school_year_range_contains_fixed_and_movable():
    hs = holidays_in_range(datetime.date(2026, 9, 7), datetime.date(2027, 5, 28))
    assert datetime.date(2026, 10, 28) in hs   # Επέτειος του «Όχι»
    assert datetime.date(2026, 12, 25) in hs   # Χριστούγεννα
    assert datetime.date(2027, 1, 1) in hs     # Πρωτοχρονιά (επόμενο έτος)
    assert datetime.date(2027, 3, 25) in hs    # 25η Μαρτίου
    assert datetime.date(2027, 3, 15) in hs    # Καθαρά Δευτέρα 2027 (Πάσχα 2/5 − 48)
    assert datetime.date(2027, 5, 3) in hs     # Δευτέρα του Πάσχα 2027
    assert datetime.date(2026, 8, 15) not in hs  # πριν το range
    assert hs == sorted(hs)


def test_empty_and_inverted_ranges():
    d = datetime.date(2026, 7, 4)
    assert holidays_in_range(d, d) == []             # καμία αργία τη μέρα αυτή
    assert holidays_in_range(d, d - datetime.timedelta(days=1)) == []
