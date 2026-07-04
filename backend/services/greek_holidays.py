"""Ελληνικές (εθνικές) αργίες — για EXDATE στο ICS export.

Σταθερές + κινητές (βάσει ορθόδοξου Πάσχα). Η λίστα είναι οι πανελλαδικές
αργίες που κλείνουν και τα φροντιστήρια· τοπικές/σχολικές (π.χ. πολιούχος,
Τριών Ιεραρχών) δεν περιλαμβάνονται — προστίθενται εύκολα στο _FIXED αν
χρειαστεί.
"""
from __future__ import annotations

import datetime

# (μήνας, μέρα) — σταθερές αργίες
_FIXED = [
    (1, 1),    # Πρωτοχρονιά
    (1, 6),    # Θεοφάνια
    (3, 25),   # Ευαγγελισμός / Εθνική εορτή
    (5, 1),    # Πρωτομαγιά
    (8, 15),   # Κοίμηση της Θεοτόκου
    (10, 28),  # Επέτειος του «Όχι»
    (12, 25),  # Χριστούγεννα
    (12, 26),  # Σύναξη της Θεοτόκου
]

# Απόσταση από το ορθόδοξο Πάσχα (σε μέρες)
_EASTER_RELATIVE = [
    -48,  # Καθαρά Δευτέρα
    -2,   # Μεγάλη Παρασκευή
    0,    # Κυριακή του Πάσχα
    1,    # Δευτέρα του Πάσχα
    50,   # Αγίου Πνεύματος
]


def orthodox_easter(year: int) -> datetime.date:
    """Ορθόδοξο Πάσχα (Γρηγοριανό ημερολόγιο) — Ιουλιανός υπολογισμός
    (Meeus) + μετατόπιση +13 ημερών, έγκυρο για τα έτη 1900–2099.

    Γνωστές τιμές που κλειδώνονται από tests: 2025-04-20, 2026-04-12,
    2027-05-02."""
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    julian = datetime.date(year, month, day)
    return julian + datetime.timedelta(days=13)


def holidays_in_range(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Όλες οι αργίες μέσα στο [start, end] (inclusive), ταξινομημένες."""
    if start > end:
        return []
    out: set[datetime.date] = set()
    for year in range(start.year, end.year + 1):
        for month, day in _FIXED:
            d = datetime.date(year, month, day)
            if start <= d <= end:
                out.add(d)
        easter = orthodox_easter(year)
        for offset in _EASTER_RELATIVE:
            d = easter + datetime.timedelta(days=offset)
            if start <= d <= end:
                out.add(d)
    return sorted(out)
