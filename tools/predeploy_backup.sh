#!/usr/bin/env bash
# Backup της βάσης ΠΡΙΝ από deploy που φέρνει νέα Alembic revision.
#
# Το entrypoint.sh τρέχει `alembic upgrade head` μόλις ξεκινήσει ο νέος
# backend, οπότε αυτό το script τρέχει στο CI πριν από το
# `docker compose up -d --build` (ίδιο μοτίβο με το «backup first» του CRM).
#
# Χρήση:  tools/predeploy_backup.sh <head revision του νέου κώδικα>
#
#   - Δεν υπάρχει container βάσης (πρώτη εγκατάσταση) → τίποτα, exit 0.
#   - Η βάση είναι ήδη στο head → τίποτα, exit 0.
#   - Αλλιώς (εκκρεμεί revision, ή η βάση είναι σε revision που ο νέος κώδικας
#     δεν ξέρει) → pg_dump -Fc + έλεγχος με pg_restore --list, exit 0.
#   - Container σταματημένο, αποτυχία ανάγνωσης revision, dump ή ελέγχου
#     → exit 1, ΔΕΝ γίνεται deploy (fail-closed).
#
# Env (προαιρετικά): DB_CONTAINER (edscheduler-db),
#   BACKUP_DIR (/home/coolman/backups/edscheduler/manual), GITHUB_SHA.
set -euo pipefail

target_head="${1:-}"
if [ -z "$target_head" ]; then
  echo "::error::predeploy_backup: λείπει το head revision του νέου κώδικα"
  exit 1
fi

db="${DB_CONTAINER:-edscheduler-db}"
backup_dir="${BACKUP_DIR:-/home/coolman/backups/edscheduler/manual}"

if ! running=$(docker inspect -f '{{.State.Running}}' "$db" 2>/dev/null); then
  echo "Δεν υπάρχει container '$db' (πρώτη εγκατάσταση;) — τίποτα για backup."
  exit 0
fi
if [ "$running" != "true" ]; then
  echo "::error::Το container '$db' υπάρχει αλλά είναι σταματημένο — δεν γίνεται backup, άρα ούτε deploy. Ξεκίνα το (docker start $db) και ξανάτρεξε το job."
  exit 1
fi

# Τα POSTGRES_USER/POSTGRES_DB υπάρχουν ήδη μέσα στο container της βάσης.
if ! current=$(docker exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version"'); then
  echo "::error::Δεν διαβάστηκε το alembic_version — σταματώ χωρίς deploy (μια αποτυχημένη ανάγνωση δεν σημαίνει «τίποτα δεν εκκρεμεί»)."
  exit 1
fi
current=$(printf '%s' "$current" | tr -d '[:space:]')
echo "Βάση: ${current:-<κενό>} · νέος κώδικας: ${target_head}"

if [ "$current" = "$target_head" ]; then
  echo "Κανένα νέο migration — χωρίς backup."
  exit 0
fi

mkdir -p "$backup_dir"
sha="${GITHUB_SHA:-local}"
dump="${backup_dir}/pre-deploy-${sha:0:7}-$(date -u +%Y%m%dT%H%M%SZ).dump"
echo "Backup της βάσης στο ${dump}..."
if ! docker exec "$db" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$dump"; then
  rm -f "$dump"
  echo "::error::Το pg_dump (ή η εγγραφή του ${dump}) απέτυχε — δεν γίνεται deploy."
  exit 1
fi
# Το pg_restore πρέπει και να ΠΕΤΥΧΕΙ — όχι μόνο να τυπώσει κάποιες γραμμές.
toc=$(docker exec -i "$db" pg_restore --list < "$dump") || toc=""
entries=$(printf '%s\n' "$toc" | grep -cE '^[0-9]+;' || true)
if [ ! -s "$dump" ] || [ "${entries:-0}" -eq 0 ]; then
  rm -f "$dump"   # να μη μείνει «backup» που δεν διαβάζεται
  echo "::error::Το backup ήταν άδειο ή δεν διαβάζεται (pg_restore --list) — δεν γίνεται deploy."
  exit 1
fi
echo "Backup OK: $(du -h "$dump" | cut -f1), ${entries} εγγραφές TOC."
