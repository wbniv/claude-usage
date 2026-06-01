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

    # STAT-1 (pass-29): the diagnostic must not crash on a corrupt cache — it's
    # the tool a user runs *because* something is wrong. _timestamp /
    # _scrape_fail_count / pct are validated on POST, but the cache is read
    # before any new POST, so a hand-edit or downgrade can leave a non-numeric
    # value. Coerce defensively (bool ⊂ int in Python, so exclude bool).
    raw_ts = d.get('_timestamp', 0)
    if isinstance(raw_ts, bool) or not isinstance(raw_ts, (int, float)):
        raw_ts = 0
    ts_min = int((time.time() - raw_ts) / 60)
    plan = d.get('plan') or '?'
    sfc = d.get('_scrape_fail_count', 0) or 0
    if isinstance(sfc, bool) or not isinstance(sfc, int):
        sfc = 0
    astat = d.get('_anthropic_status') or {}

    if ts_min > 20:
        print(f'  Cache:      ✗ {ts_min}m old — extension flips to BROKEN at this point (plan: {plan})')
        print('              Fix: click the Chrome extension toolbar icon to force a fetch')
    elif ts_min > 15:
        # 15-min stale threshold — must agree with extension.js's `age > 15`
        # (raised 10→15 in pass-13 A‑2 for MV3 alarm jitter). Drift between
        # this number and the extension's would make the diagnostic lie.
        print(f'  Cache:      ⚠ {ts_min}m old — extension flips to STALE at this point (plan: {plan})')
    else:
        print(f'  Cache:      ✓ present ({ts_min}m ago, plan: {plan})')

    if sfc >= 2:
        print(f'  Scrape:     ⚠ {sfc} consecutive failures — click Chrome toolbar to retry')
    elif sfc == 1:
        print('  Scrape:     1 recent failure (recoverable)')

    # L2-2 (pass-18): surface the scraper's distinguished "parse failure"
    # signal so panel-grey troubleshooting points at the actual cause.
    # Today the only emitted value is 'locale_or_layout' (page hydrated but
    # English string anchors missed); future values can extend.
    pf = d.get('_parse_failure')
    if pf == 'locale_or_layout':
        print('  Scrape:     ⚠ scraper produced no meters; page may be in a non-English locale')
        print('              Fix: set browser language to English in Chrome settings, then reload')
    elif pf:
        print(f'  Scrape:     ⚠ parse failure: {pf}')

    ind = astat.get('indicator')
    if ind and ind != 'none':
        desc = astat.get('description') or ind
        print(f'  Anthropic:  ⚠ {desc}')
    component = astat.get('claude_ai_component_status')
    if component and component != 'operational':
        print(f'  Anthropic:  ⚠ claude.ai component: {component}')

    ev = d.get('_ext_version')
    if d.get('_ext_version_mismatch'):
        print(f'  Chrome ext: ⚠ v{ev or "?"} differs from server-expected version')
        print('              Fix: chrome://extensions → Claude Usage Tracker → Reload')
    elif ev is None and raw_ts > 0:
        # Cache has data but no version stamp → Chrome ext predates 0.11.1's
        # _ext_version field. Most likely: user upgraded the .deb but Chrome is
        # still running the old loaded copy and was never reloaded.
        print('  Chrome ext: ⚠ running version predates 0.11.1 (no _ext_version stamp)')
        print('              Fix: chrome://extensions → Claude Usage Tracker → Reload')

    for m in d.get('meters', []):
        label = (m.get('label') or '?')[:40]
        pct = m.get('pct', 0)
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            pct = 0
        pct = int(pct)
        filled = max(0, min(10, round(pct / 10)))
        bar = '█' * filled + '░' * (10 - filled)
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


def _check_chrome_orphans():
    """Flag Chrome-registered Claude Usage extensions whose load-unpacked path
    no longer exists. Common after switching install methods (source → .deb);
    Chrome silently keeps the orphan registration with a load error."""
    prefs = Path.home() / '.config/google-chrome/Default/Preferences'
    if not prefs.exists():
        return
    try:
        exts = json.loads(prefs.read_text())['extensions']['settings']
    except (KeyError, json.JSONDecodeError):
        return
    for eid, e in exts.items():
        path = e.get('path', '') or ''
        if 'claude-usage' in path and not Path(path).exists():
            print(f'  Chrome ext: ⚠ orphan registration at {path}')
            print(f'              Fix: chrome://extensions → remove "{eid[:8]}…"')


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
    _check_chrome_orphans()
    print()
