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
# PORT is read from the service's port file *after* it starts (below), not
# hardcoded — dynamic port discovery (0.11.7+) means the service may bind
# 7332..7340 if 7331 is contended on the runner. CLAUDE_USAGE_PORT, if set,
# pins the service's bind port via systemd env — the port file still reports
# the actually-bound port, so reading it works under both pinning and fallback.

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

# The .deb's postinst auto-runs claude-usage-setup for SUDO_USER (the user
# who ran `apt-get install …`). That user's service is already bound to
# 127.0.0.1:7331 by the time we get here, which would make cu-smoke's
# instance crash-loop on EADDRINUSE — `is-active --quiet` still reports
# "activating" as active, so the POSTs would silently hit the wrong server.
# Stop the prior-user service first so cu-smoke's owns the port.
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ] && [ "$SUDO_USER" != "$TESTUSER" ]; then
    SUDO_UID=$(id -u "$SUDO_USER" 2>/dev/null || echo "")
    if [ -n "$SUDO_UID" ]; then
        echo "==> Stopping pre-existing claude-usage service for $SUDO_USER (UID $SUDO_UID) to free port 7331"
        runuser -u "$SUDO_USER" -- env \
            XDG_RUNTIME_DIR="/run/user/$SUDO_UID" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$SUDO_UID/bus" \
            systemctl --user stop claude-usage-fetch.service 2>/dev/null || true
    fi
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

# Read the port the service actually bound. Without this, the smoke test
# hardcoded 7331 and would POST to whatever happened to squat that port
# when dynamic discovery (0.11.7+) made the service fall through to 7332+.
PORT_FILE="/home/$TESTUSER/.cache/claude-usage/port"
if [ ! -f "$PORT_FILE" ]; then
    echo "FAIL: $PORT_FILE not written — port-file write path broken?" >&2
    exit 1
fi
PORT=$(cat "$PORT_FILE")
echo "==> Service bound port $PORT (from $PORT_FILE)"

# Track the actual installed Chrome ext version for the fixture POST. Hard-
# coding 0.11.1 produced a "version mismatch" warning on every CI run that
# masked the signal we want — a real mismatch in the field. The .deb is
# already installed at this point so the manifest is on disk.
EXT_VER=$(python3 -c "import json; print(json.load(open('/usr/share/claude-usage/chrome-extension/manifest.json'))['version'])")

echo "==> POSTing current-shape probe payload to 127.0.0.1:$PORT/update"
run_as curl -sf -X POST "http://127.0.0.1:$PORT/update" \
    -H 'Content-Type: application/json' \
    -d "{\"meters\":[{\"pct\":42,\"label\":\"live-smoke\",\"reset\":null,\"reset_minutes\":120}],\"_ext_version\":\"$EXT_VER\"}" >/dev/null

# Backcompat probe (C-3): a pre-V-1 Chrome extension would not include
# _ext_version, reset_minutes, or _period_lengths. The server's validator
# must remain permissive of older shapes so users on stale extensions
# don't have their POSTs silently rejected mid-upgrade. Keep the literal
# 'Max plan' string (older scraper output) to exercise the same path.
echo "==> POSTing old-shape probe payload (no _ext_version, no reset_minutes)"
run_as curl -sf -X POST "http://127.0.0.1:$PORT/update" \
    -H 'Content-Type: application/json' \
    -d '{"meters":[{"pct":50,"label":"live-smoke-old","reset":"Resets in 1 hr 0 min"}],"plan":"Max plan"}' >/dev/null

echo "==> Verifying cache write"
CACHE="/home/$TESTUSER/.cache/claude-usage/usage.json"
if [ ! -f "$CACHE" ]; then
    echo "FAIL: $CACHE was not written" >&2
    exit 1
fi

if ! grep -q '"live-smoke-old"' "$CACHE"; then
    echo "FAIL: $CACHE missing probe label (second POST didn't take)" >&2
    cat "$CACHE" >&2
    exit 1
fi

# A-1: every write must stamp _schema; the second POST should have written 1.
if ! grep -q '"_schema": 1' "$CACHE"; then
    echo "FAIL: $CACHE missing _schema:1 — A-1 regression" >&2
    cat "$CACHE" >&2
    exit 1
fi

echo "==> Stopping service"
run_as systemctl --user stop claude-usage-fetch.service

echo "OK: live smoke test passed"
