#!/usr/bin/env bash
# Live smoke test for the claude-usage .deb on a real systemd host.
#
# Runs *after* the .deb is installed system-wide (typically on a GH Actions
# bare runner: `sudo apt-get install ./dist/claude-usage_X.Y.Z_all.deb`).
# Creates a fresh user, enables linger, starts the user service, POSTs a
# probe payload, and verifies the cache write — exercises capability drops,
# namespace setup, ExecStart path, and the validator + atomic-write path
# end-to-end. Catches the R-1 class of regression (218/CAPABILITIES) that
# only manifests at exec time.
#
# Argument: the username to create and run as (default: cu-testuser).
set -euo pipefail

TESTUSER="${1:-cu-testuser}"
PORT="${CLAUDE_USAGE_PORT:-7331}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [testuser]"
    echo ""
    echo "Live-smoke test: creates a user, starts claude-usage-fetch.service,"
    echo "POSTs a probe payload, and verifies the cache write."
    exit 0
fi

if [ ! -d /run/systemd/system ]; then
    echo "FAIL: systemd is not PID 1 — this script requires a real systemd host." >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "FAIL: must run as root (creates a user, calls loginctl)." >&2
    exit 1
fi

echo "==> Creating user '$TESTUSER' and enabling linger"
if ! id -u "$TESTUSER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$TESTUSER"
fi
loginctl enable-linger "$TESTUSER"

TESTUID=$(id -u "$TESTUSER")
RUNTIME_DIR="/run/user/$TESTUID"

# Wait for the user manager to come up after enable-linger.
# `loginctl user-status` returns 0 once the user manager is active.
for _ in $(seq 1 20); do
    if loginctl user-status "$TESTUSER" 2>/dev/null | grep -q 'State: active\|State: lingering'; then
        break
    fi
    sleep 0.5
done

run_as() {
    runuser -u "$TESTUSER" -- env XDG_RUNTIME_DIR="$RUNTIME_DIR" DBUS_SESSION_BUS_ADDRESS="unix:path=$RUNTIME_DIR/bus" "$@"
}

echo "==> Reloading user systemd and starting the service"
run_as systemctl --user daemon-reload
run_as systemctl --user start claude-usage-fetch.service

# Give the service a moment to bind the port + start the HTTP loop.
sleep 3

echo "==> Checking service is active"
if ! run_as systemctl --user is-active --quiet claude-usage-fetch.service; then
    echo "FAIL: claude-usage-fetch.service is not active" >&2
    run_as systemctl --user status claude-usage-fetch.service --no-pager || true
    run_as journalctl --user -u claude-usage-fetch.service -n 20 --no-pager || true
    exit 1
fi

echo "==> POSTing probe payload to 127.0.0.1:$PORT/update"
run_as curl -sf -X POST "http://127.0.0.1:$PORT/update" \
    -H 'Content-Type: application/json' \
    -d '{"meters":[{"pct":42,"label":"live-smoke","reset":null}]}' >/dev/null

echo "==> Verifying cache write"
CACHE="/home/$TESTUSER/.cache/claude-usage/usage.json"
if [ ! -f "$CACHE" ]; then
    echo "FAIL: $CACHE was not written" >&2
    exit 1
fi

if ! grep -q '"live-smoke"' "$CACHE"; then
    echo "FAIL: $CACHE missing probe label" >&2
    cat "$CACHE" >&2
    exit 1
fi

echo "==> Stopping service"
run_as systemctl --user stop claude-usage-fetch.service

echo "OK: live smoke test passed"
