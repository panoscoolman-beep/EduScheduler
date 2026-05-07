#!/bin/bash
#
# Migration: hand the GitHub Actions runner over to systemd so it
# survives reboots and auto-restarts on crash. Same pattern as
# /home/coolman/korifi-crm-v2/tools/migrate_runner_to_systemd.sh.
#
# Differences:
#   - The unit doesn't exist yet, so we run `svc.sh install` first.
#   - The drop-in override goes to the freshly-created unit's .d dir.
#
# What this does (in order):
#   1. Verifies no GitHub Actions job is currently in flight.
#   2. Stops the manually-started ./run.sh chain (SIGTERM cascade).
#   3. Runs `./svc.sh install coolman` to register the systemd unit.
#   4. Adds drop-in: .d/override.conf with Restart=on-failure +
#      RestartSec=10 (the upstream installer never adds these).
#   5. systemctl daemon-reload + start.
#   6. Verifies active(running) and ESTABLISHED HTTPS to GitHub.
#
# Run with sudo (single password prompt):
#   sudo bash /home/coolman/EduScheduler/tools/migrate_runner_to_systemd.sh

set -euo pipefail

readonly RUNNER_DIR="/home/coolman/actions-runner-edscheduler"
readonly RUNNER_USER="coolman"

log() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "ERROR: must be run as root (use: sudo bash $0)" >&2
    exit 1
  fi
}

verify_no_active_job() {
  log "1/6  Checking for in-flight GitHub Actions jobs"
  if pgrep -af "${RUNNER_DIR}.*Runner.Worker" >/dev/null 2>&1; then
    echo "ERROR: a Runner.Worker process is active — wait for it to finish" >&2
    pgrep -af "${RUNNER_DIR}.*Runner.Worker" >&2
    exit 2
  fi
  echo "  ok — no active worker"
}

stop_manual_runner() {
  log "2/6  Stopping manual ./run.sh + Runner.Listener (if running)"
  local pids
  pids=$(pgrep -af "${RUNNER_DIR}" | grep -v "$0\|grep" | awk '{print $1}' || true)
  if [[ -z "${pids}" ]]; then
    echo "  no manual processes found"
    return 0
  fi
  echo "  PIDs: ${pids}"
  echo "${pids}" | xargs -r kill -INT 2>/dev/null || true
  for _ in $(seq 1 30); do
    sleep 1
    if ! pgrep -f "${RUNNER_DIR}" >/dev/null 2>&1; then
      echo "  ok — exited cleanly via SIGINT"
      return 0
    fi
  done
  echo "  WARN: still running after 30s, escalating to SIGTERM"
  pgrep -f "${RUNNER_DIR}" | xargs -r kill -TERM 2>/dev/null || true
  sleep 5
  pgrep -f "${RUNNER_DIR}" | xargs -r kill -KILL 2>/dev/null || true
}

register_systemd_unit() {
  log "3/6  Registering systemd service via svc.sh install"
  cd "${RUNNER_DIR}"
  ./svc.sh install "${RUNNER_USER}" 2>&1 | sed 's/^/  /'
}

write_override() {
  # Find the unit name svc.sh installed; pattern is
  # actions.runner.<owner>-<repo>.<runner-name>.service
  local svc
  svc=$(systemctl list-unit-files --no-pager 'actions.runner.*EduScheduler*.service' 2>/dev/null \
        | awk '/\.service/ {print $1; exit}')
  if [[ -z "${svc}" ]]; then
    # Fallback search
    svc=$(systemctl list-unit-files --no-pager 'actions.runner.*panoscoolman*.service' 2>/dev/null \
          | grep -i edscheduler | awk '{print $1; exit}')
  fi
  if [[ -z "${svc}" ]]; then
    echo "ERROR: could not find the installed unit name" >&2
    systemctl list-unit-files --no-pager 'actions.runner.*' >&2
    exit 3
  fi
  echo "  installed unit: ${svc}"

  local override_dir="/etc/systemd/system/${svc}.d"
  log "4/6  Writing drop-in override at ${override_dir}/override.conf"
  mkdir -p "${override_dir}"
  cat > "${override_dir}/override.conf" <<'EOF'
# Auto-restart policy added 2026-05-07 — the upstream unit (installed
# by GitHub's svc.sh) has no Restart= directive, so a crash leaves the
# service in failed state until someone manually starts it.
[Service]
Restart=on-failure
RestartSec=10
EOF

  # Stash unit name for later steps
  echo "${svc}" > /tmp/.eds-runner-unit-name
}

start_via_systemd() {
  local svc; svc=$(cat /tmp/.eds-runner-unit-name)
  log "5/6  systemctl daemon-reload + reset-failed + start"
  systemctl daemon-reload
  systemctl reset-failed "${svc}" || true
  systemctl start "${svc}"
  echo "  start command issued for ${svc}"
}

verify_active() {
  local svc; svc=$(cat /tmp/.eds-runner-unit-name)
  log "6/6  Verifying active(running) + ESTABLISHED to GitHub"
  for _ in $(seq 1 30); do
    sleep 1
    if systemctl is-active --quiet "${svc}"; then
      echo "  ok — unit is active"
      systemctl status "${svc}" --no-pager -l | head -10
      break
    fi
  done

  for _ in $(seq 1 20); do
    sleep 1
    if ss -tnp 2>/dev/null | grep -q "actions-runner-edscheduler/.*\\.443"; then
      :  # not the right pattern, skip
    fi
    if pgrep -af "${RUNNER_DIR}.*Runner.Listener" >/dev/null 2>&1; then
      local pid
      pid=$(pgrep -f "${RUNNER_DIR}.*Runner.Listener" | head -1)
      if ss -tnp 2>/dev/null | grep ":443" | grep -q "pid=${pid}"; then
        echo "  ok — Runner.Listener pid=${pid} ESTABLISHED to GitHub"
        return 0
      fi
    fi
  done
  echo "WARN: no ESTABLISHED :443 socket from Runner.Listener after 20s." >&2
  echo "      Check: journalctl -u $(cat /tmp/.eds-runner-unit-name) -n 50" >&2
}

main() {
  require_root
  verify_no_active_job
  stop_manual_runner
  register_systemd_unit
  write_override
  start_via_systemd
  verify_active
  log "DONE — EduScheduler runner now managed by systemd with auto-restart."
}

main "$@"
