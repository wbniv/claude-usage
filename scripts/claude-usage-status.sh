#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $(basename "$0")"
    echo ""
    echo "Check the health of the Claude Usage indicator:"
    echo "  - systemd service status"
    echo "  - cache file age and meter breakdown"
    echo "  - GNOME extension state"
    exit 0
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage

CACHE_JSON="$HOME/.cache/claude-usage.json"

echo "Claude Usage — status check"
echo ""

# ── Service ──────────────────────────────────────────────────────────────────
if systemctl --user is-active --quiet claude-usage-fetch.service 2>/dev/null; then
    pid=$(systemctl --user show -p MainPID --value claude-usage-fetch.service 2>/dev/null || echo "?")
    echo "  Service:    ● running (PID $pid)"
else
    echo "  Service:    ✗ not running"
    echo "              Fix: systemctl --user start claude-usage-fetch.service"
fi

# ── Cache ─────────────────────────────────────────────────────────────────────
if [ -f "$CACHE_JSON" ]; then
    ts=$(python3 - "$CACHE_JSON" <<'EOF'
import json, sys, time
try:
    d = json.load(open(sys.argv[1]))
    print(int((time.time() - d.get('_timestamp', 0)) / 60))
except Exception:
    print("?")
EOF
)
    plan=$(python3 - "$CACHE_JSON" <<'EOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get('plan') or '?')
except Exception:
    print("?")
EOF
)
    if [ "$ts" = "?" ] || [ "$ts" -gt 30 ] 2>/dev/null; then
        echo "  Cache:      ⚠ ${ts}m old — data may be stale (plan: $plan)"
        echo "              Fix: click the Chrome extension toolbar icon to force a fetch"
    else
        echo "  Cache:      ✓ present (${ts}m ago, plan: $plan)"
    fi
    python3 - "$CACHE_JSON" <<'EOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    for m in d.get('meters', []):
        label = (m.get('label') or '?')[:40]
        pct   = m.get('pct', 0)
        bar   = '█' * round(pct / 10) + '░' * (10 - round(pct / 10))
        print(f"  Meter:      {label:<40}  {pct:3d}%  {bar}")
except Exception as e:
    print(f"  Cache:      ✗ parse error: {e}")
EOF
else
    echo "  Cache:      ✗ not found"
    echo "              Fix: click the Chrome extension toolbar icon to trigger the first fetch"
fi

# ── GNOME extension ───────────────────────────────────────────────────────────
EXT_ID="claude-usage@indri.studio"
if gnome-extensions show "$EXT_ID" &>/dev/null; then
    state=$(gnome-extensions show "$EXT_ID" 2>/dev/null | grep -i 'State:' | awk '{print $2}' || echo "?")
    echo "  Extension:  $state ($EXT_ID)"
else
    echo "  Extension:  ✗ not installed"
    echo "              Fix: gnome-extensions enable $EXT_ID"
fi

echo ""
