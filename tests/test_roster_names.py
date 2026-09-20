"""👥 Αυτόματα ονόματα μαθητών: «Ιγνάτης Μ.» παντού (κάρτες, πλέγμα, email)."""
from backend.services.lesson_roster import short_name


def test_short_name_is_first_plus_initial():
    assert short_name("ΙΓΝΑΤΗΣ", "ΜΟΥΤΑΦΗΣ") == "ΙΓΝΑΤΗΣ Μ."
    assert short_name("Δήμητρα", "Πασβούρη") == "Δήμητρα Π."
    assert short_name("  Νίκος  ", "") == "Νίκος"
    assert short_name("", "ΠΑΠΠΑΣ") == "ΠΑΠΠΑΣ"
    assert short_name("", "") == ""
