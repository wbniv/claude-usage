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

CACHE_JSON="$HOME/.cache/claude-usage/usage.json"

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
    # Single Python invocation parses the cache once and reports cache age,
    # tier signals, and per-meter rows. Thresholds match the GNOME extension
    # (extension.js): stale at 10 min, broken at 20 min — `claude-usage-status`
    # used to report `⚠` only past 30 min, which lied compared to the panel.
    python3 - "$CACHE_JSON" <<'EOF'
import json, sys, time
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"  Cache:      ✗ parse error: {e}")
    sys.exit(0)

ts_min = int((time.time() - d.get('_timestamp', 0)) / 60)
plan = d.get('plan') or '?'
sfc = d.get('_scrape_fail_count', 0) or 0
astat = d.get('_anthropic_status') or {}

if ts_min > 20:
    print(f"  Cache:      ✗ {ts_min}m old — extension flips to BROKEN at this point (plan: {plan})")
    print(f"              Fix: click the Chrome extension toolbar icon to force a fetch")
elif ts_min > 10:
    print(f"  Cache:      ⚠ {ts_min}m old — extension flips to STALE at this point (plan: {plan})")
else:
    print(f"  Cache:      ✓ present ({ts_min}m ago, plan: {plan})")

if sfc >= 2:
    print(f"  Scrape:     ⚠ {sfc} consecutive failures — click Chrome toolbar to retry")
elif sfc == 1:
    print(f"  Scrape:     1 recent failure (recoverable)")

ind = astat.get('indicator')
if ind and ind != 'none':
    desc = astat.get('description') or ind
    print(f"  Anthropic:  ⚠ {desc}")
component = astat.get('claude_ai_component_status')
if component and component != 'operational':
    print(f"  Anthropic:  ⚠ claude.ai component: {component}")

for m in d.get('meters', []):
    label = (m.get('label') or '?')[:40]
    pct = m.get('pct', 0)
    bar = '█' * round(pct / 10) + '░' * (10 - round(pct / 10))
    print(f"  Meter:      {label:<40}  {pct:3d}%  {bar}")
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
