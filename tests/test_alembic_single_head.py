"""Φύλακας: τα migrations σχηματίζουν μία γραμμή με ένα μόνο head.

Διπλό revision id (π.χ. αντιγραμμένο αρχείο) ή δύο αρχεία στο ίδιο
down_revision → «Multiple head revisions» και το deploy σκάει στο
`alembic upgrade head` του entrypoint.
"""
from pathlib import Path
import re

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def test_revision_ids_are_unique():
    ids = [re.search(r'^revision[^=]*=\s*["\']([^"\']+)["\']', p.read_text(), re.M).group(1)
           for p in (ROOT / "alembic" / "versions").glob("*.py")]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)


def test_single_head():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
