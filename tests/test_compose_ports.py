"""Οι πόρτες του docker-compose.yml πρέπει να δηλώνουν IPv4 διεύθυνση.

Χωρίς διεύθυνση (π.χ. "8082:8000") το Docker ανοίγει την πόρτα και σε [::].
Το firewall του server (APP-PORT-GUARD, iptables) καλύπτει μόνο IPv4 και ο
server έχει δημόσια IPv6, οπότε μια «γυμνή» πόρτα θα έβγαζε στο internet
ένα API χωρίς login.
"""
from __future__ import annotations

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
_ALLOWED_HOSTS = ("0.0.0.0", "127.0.0.1")


def _published_ports(text: str) -> list[str]:
    ports, in_ports, indent = [], False, 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cur = len(line) - len(line.lstrip())
        if stripped == "ports:":
            in_ports, indent = True, cur
            continue
        if in_ports:
            if cur <= indent:
                in_ports = False
            elif stripped.startswith("- "):
                ports.append(stripped[2:].strip().strip("\"'"))
    return ports


def test_compose_has_published_ports():
    assert _published_ports(COMPOSE.read_text(encoding="utf-8")), "δεν βρέθηκε καμία πόρτα"


def test_every_published_port_is_bound_to_ipv4():
    for spec in _published_ports(COMPOSE.read_text(encoding="utf-8")):
        host = spec.split(":")[0] if spec.count(":") == 2 else None
        assert host in _ALLOWED_HOSTS, (
            f"η πόρτα {spec!r} ακούει και σε IPv6 — γράψ' την ως '0.0.0.0:{spec}'"
        )


def test_parser_flags_bare_port():
    sample = 'services:\n  b:\n    ports:\n      - "8082:8000"\n    networks:\n      - x\n'
    assert _published_ports(sample) == ["8082:8000"]
    assert re.match(r"^\d+:\d+$", _published_ports(sample)[0])
