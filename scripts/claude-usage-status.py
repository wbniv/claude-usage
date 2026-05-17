#!/usr/bin/env python3
"""Health check for the Claude Usage indicator."""
import json, os, subprocess, sys, time
from pathlib import Path

_CACHE_HOME = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
CACHE_JSON = _CACHE_HOME / 'claude-usage' / 'usage.json'
EXT_ID = 'claude-usage@indri.studio'


def _systemctl(*args):
    return subprocess.run(['systemctl', '--user', *args],
                          capture_output=True, text=True)


def _check_service():
    if _systemctl('is-active', '--quiet', 'claude-usage-fetch.service').returncode == 0:
        pid = _systemctl('show', '-p', 'MainPID', '--value',
                         'claude-usage-fetch.service').stdout.strip() or '?'
        print(f'  Service:    ● running (PID {pid})')
    else:
        print('  Service:    ✗ not running')
        print('              Fix: systemctl --user start claude-usage-fetch.service')


def _check_cache():
    if not CACHE_JSON.exists():
        print('  Cache:      ✗ not found')
        print('              Fix: click the Chrome extension toolbar icon to trigger the first fetch')
        return
    try:
        d = json.loads(CACHE_JSON.read_text())
    except Exception as e:
        print(f'  Cache:      ✗ parse error: {e}')
        return

    ts_min = int((time.time() - d.get('_timestamp', 0)) / 60)
    plan = d.get('plan') or '?'
    sfc = d.get('_scrape_fail_count', 0) or 0
    astat = d.get('_anthropic_status') or {}

    if ts_min > 20:
        print(f'  Cache:      ✗ {ts_min}m old — extension flips to BROKEN at this point (plan: {plan})')
        print('              Fix: click the Chrome extension toolbar icon to force a fetch')
    elif ts_min > 10:
        print(f'  Cache:      ⚠ {ts_min}m old — extension flips to STALE at this point (plan: {plan})')
    else:
        print(f'  Cache:      ✓ present ({ts_min}m ago, plan: {plan})')

    if sfc >= 2:
        print(f'  Scrape:     ⚠ {sfc} consecutive failures — click Chrome toolbar to retry')
    elif sfc == 1:
        print('  Scrape:     1 recent failure (recoverable)')

    ind = astat.get('indicator')
    if ind and ind != 'none':
        desc = astat.get('description') or ind
        print(f'  Anthropic:  ⚠ {desc}')
    component = astat.get('claude_ai_component_status')
    if component and component != 'operational':
        print(f'  Anthropic:  ⚠ claude.ai component: {component}')

    if d.get('_ext_version_mismatch'):
        ev = d.get('_ext_version') or '?'
        print(f'  Chrome ext: ⚠ v{ev} differs from server-expected version')
        print('              Fix: chrome://extensions → Claude Usage Tracker → Reload')

    for m in d.get('meters', []):
        label = (m.get('label') or '?')[:40]
        pct = m.get('pct', 0)
        bar = '█' * round(pct / 10) + '░' * (10 - round(pct / 10))
        print(f'  Meter:      {label:<40}  {pct:3d}%  {bar}')


def _check_extension():
    r = subprocess.run(['gnome-extensions', 'show', EXT_ID],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f'  Extension:  ✗ not installed')
        print(f'              Fix: gnome-extensions enable {EXT_ID}')
        return
    state = next((l.split(':', 1)[1].strip()
                  for l in r.stdout.splitlines() if 'State:' in l), '?')
    print(f'  Extension:  {state} ({EXT_ID})')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print(f'Usage: {Path(sys.argv[0]).name}')
        print()
        print('Check the health of the Claude Usage indicator:')
        print('  - systemd service status')
        print('  - cache file age and meter breakdown')
        print('  - GNOME extension state')
        sys.exit(0)

    print('Claude Usage — status check')
    print()
    _check_service()
    _check_cache()
    _check_extension()
    print()
