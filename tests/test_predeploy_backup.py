"""tools/predeploy_backup.sh — backup της βάσης πριν από deploy με νέο migration.

Το `docker` αντικαθίσταται από ψεύτικο script στο PATH, οπότε το test τρέχει
χωρίς Docker και ελέγχει μόνο τις αποφάσεις του script: πότε παίρνει backup,
πότε όχι, και ότι κάθε αποτυχία σταματά το deploy (exit ≠ 0) χωρίς να αφήνει
μισό αρχείο.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "predeploy_backup.sh"
HEAD = "d1e3f5a7b9c2"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="χρειάζεται bash")

_FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$1" in
  inspect)
    [ -n "${FAKE_NO_CONTAINER:-}" ] && { echo "Error: No such object" >&2; exit 1; }
    echo "${FAKE_RUNNING:-true}" ;;
  exec)
    args="$*"
    if [[ "$args" == *alembic_version* ]]; then
      [ -n "${FAKE_PSQL_FAIL:-}" ] && { echo "too many clients" >&2; exit 2; }
      echo "${FAKE_CURRENT:-}"
    elif [[ "$args" == *pg_dump* ]]; then
      [ -n "${FAKE_DUMP_FAIL:-}" ] && { echo "pg_dump: error" >&2; exit 1; }
      printf 'PGDMP-fake'
    elif [[ "$args" == *pg_restore* ]]; then
      cat > /dev/null
      [ -n "${FAKE_TOC_EMPTY:-}" ] && exit 1
      printf ';\n; Archive created\n;\n215; 1259 16385 TABLE public students edscheduler\n'
    fi ;;
esac
"""


@pytest.fixture()
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(_FAKE_DOCKER)
    docker.chmod(0o755)
    e = {
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_LOG": str(tmp_path / "docker.log"),
        "BACKUP_DIR": str(tmp_path / "backups"),
        "GITHUB_SHA": "abcdef1234567",
    }
    return e, tmp_path


def _run(e, *args, **extra):
    full = {**e, **{k: str(v) for k, v in extra.items()}}
    return subprocess.run(["bash", str(SCRIPT), *args], env=full,
                          capture_output=True, text=True, timeout=30)


def _dumps(tmp_path):
    d = tmp_path / "backups"
    return sorted(d.glob("*.dump")) if d.exists() else []


def _log(tmp_path):
    p = tmp_path / "docker.log"
    return p.read_text() if p.exists() else ""


def test_requires_target_head(env):
    e, _ = env
    r = _run(e)
    assert r.returncode == 1


def test_first_install_without_db_container_skips(env):
    e, tmp = env
    r = _run(e, HEAD, FAKE_NO_CONTAINER=1)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _dumps(tmp) == []
    assert "pg_dump" not in _log(tmp)


def test_stopped_db_container_blocks_deploy(env):
    e, tmp = env
    r = _run(e, HEAD, FAKE_RUNNING="false")
    assert r.returncode == 1
    assert _dumps(tmp) == []


def test_db_already_at_head_skips_backup(env):
    e, tmp = env
    r = _run(e, HEAD, FAKE_CURRENT=HEAD)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _dumps(tmp) == []
    assert "pg_dump" not in _log(tmp)


def test_pending_migration_takes_verified_backup(env):
    e, tmp = env
    r = _run(e, HEAD, FAKE_CURRENT="c9d2e4f6a8b1")
    assert r.returncode == 0, r.stdout + r.stderr
    dumps = _dumps(tmp)
    assert len(dumps) == 1
    assert dumps[0].name.startswith("pre-deploy-abcdef1-")
    assert dumps[0].read_text() == "PGDMP-fake"
    assert "pg_restore --list" in _log(tmp)
    assert "Backup OK" in r.stdout


def test_unknown_db_revision_also_backs_up(env):
    """Βάση σε revision που ο νέος κώδικας δεν ξέρει (π.χ. revert κώδικα χωρίς
    downgrade): πάλι backup πριν αγγίξει οτιδήποτε το entrypoint."""
    e, tmp = env
    r = _run(e, HEAD, FAKE_CURRENT="ffffffffffff")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(_dumps(tmp)) == 1


def test_unreadable_alembic_version_blocks_deploy(env):
    e, tmp = env
    r = _run(e, HEAD, FAKE_PSQL_FAIL=1)
    assert r.returncode == 1
    assert _dumps(tmp) == []
    assert "pg_dump" not in _log(tmp)


def test_failed_pg_dump_blocks_deploy_and_leaves_no_file(env):
    e, tmp = env
    r = _run(e, HEAD, FAKE_CURRENT="c9d2e4f6a8b1", FAKE_DUMP_FAIL=1)
    assert r.returncode == 1
    assert _dumps(tmp) == []


def test_unreadable_backup_blocks_deploy_and_is_removed(env):
    e, tmp = env
    r = _run(e, HEAD, FAKE_CURRENT="c9d2e4f6a8b1", FAKE_TOC_EMPTY=1)
    assert r.returncode == 1
    assert _dumps(tmp) == []
