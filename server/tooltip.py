"""Tooltip rendering shared between usage-server.py (60 s tick) and
generate-icon.py (15 min full POST regen)."""
import datetime, os, re, time
from pathlib import Path

DESKTOP = Path.home() / '.local/share/applications/claude-usage.desktop'

WD_MAP = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}


def parse_reset(reset, reset_minutes=None, anchor_ts=None):
    """Returns (is_countdown, display) or None. Countdown shows ⏱h:mm; day shows 'Tue 1:00'.

    When reset_minutes (the snapshot value at scrape time) and anchor_ts
    (the cache's _timestamp) are both supplied, the "Resets in …"
    countdown forms are recomputed as `reset_minutes - minutes_elapsed`
    so the tooltip ticks down minute-by-minute between scrapes. The
    "Resets Tue 5 PM" day/time form below uses datetime.now() and is
    already live regardless of these args."""
    if not reset:
        return None

    # Live countdown: prefer snapshot + elapsed over re-parsing the
    # frozen literal in `reset`. Only applies to "Resets in …" forms;
    # the day/time form has its own live-recomputation path below.
    if reset_minutes is not None and anchor_ts is not None \
            and re.match(r'[Rr]esets? in \d+', reset):
        # Floor-divide elapsed seconds by 60 so the countdown only ticks
        # down after a full minute passes (i.e., at scrape time + 0 s
        # shows the scraped value, not value-1 from FP drift).
        elapsed_min = max(0, int((time.time() - anchor_ts) // 60))
        remaining = max(0, reset_minutes - elapsed_min)
        return (True, f"{remaining // 60}:{remaining % 60:02d}")

    m = re.match(r'[Rr]esets? in (\d+) hr (\d+) min', reset)
    if m:
        return (True, f"{m.group(1)}:{int(m.group(2)):02d}")
    m = re.match(r'[Rr]esets? in (\d+) min', reset)
    if m:
        return (True, f"0:{int(m.group(1)):02d}")
    m = re.match(r'[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)', reset)
    if m:
        day, h, mn, ap = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        # Unknown day (locale change, formatter glitch) — return None so the
        # caller falls back to the literal reset string rather than silently
        # defaulting to Monday and rendering the wrong reset day.
        if day not in WD_MAP:
            return None
        if ap == 'PM' and h != 12: h += 12
        elif ap == 'AM' and h == 12: h = 0
        now = datetime.datetime.now()
        wd = WD_MAP[day]
        ahead = (wd - now.weekday()) % 7
        if ahead == 0:
            candidate = now.replace(hour=h, minute=mn, second=0, microsecond=0)
            if candidate <= now:
                ahead = 7
        target = (now + datetime.timedelta(days=ahead)).replace(hour=h, minute=mn, second=0, microsecond=0)
        mins = int((target - now).total_seconds() / 60)
        if mins < 24 * 60:
            return (True, f"{mins // 60}:{mins % 60:02d}")
        return (False, f"{day} {h:02d}:{mn:02d}")

    return None


def format_tooltip(meters, anchor_ts=None):
    find = lambda kw: next((m for m in meters if kw in (m.get('label') or '').lower()), None)
    current = find('session') or find('current')
    all_m   = find('all')
    sonnet  = find('sonnet')
    parts = []
    for key, meter in [('current', current), ('all', all_m), ('sonnet', sonnet)]:
        if not meter:
            continue
        pct = meter.get('pct', 0)
        if key == 'sonnet' and pct == 0:
            continue
        part = f"{key} {pct}%"
        reset_info = parse_reset(
            meter.get('reset'),
            reset_minutes=meter.get('reset_minutes'),
            anchor_ts=anchor_ts,
        )
        if reset_info:
            is_countdown, display = reset_info
            part += f" ⏱{display}" if is_countdown else f" {display}"
        parts.append(part)
    return '   |   '.join(parts) if parts else 'Claude Usage'


def update_desktop(meters, icon_path=None, scrape_ts=None):
    """Rewrite the .desktop launcher's Name= line with a fresh tooltip.

    If icon_path is None, preserve the existing Icon= line — that's the
    path the 60 s tick takes from usage-server.py; the 15 min regen
    from generate-icon.py passes a fresh timestamped path.

    scrape_ts is the cache's _timestamp (epoch seconds when the scrape
    landed); when supplied, countdown-form resets are recomputed live
    in parse_reset so the tooltip ticks down between scrapes."""
    if not DESKTOP.exists():
        return
    name = format_tooltip(meters, anchor_ts=scrape_ts).replace('\n', r'\n')
    lines = DESKTOP.read_text().splitlines()
    out = []
    for line in lines:
        if line.startswith('Name='):
            out.append(f'Name={name}')
        elif line.startswith('Icon='):
            out.append(line if icon_path is None else f'Icon={icon_path}')
        elif line.startswith('#'):
            out.append(line)
        elif line.startswith('[') or '=' in line or line == '':
            out.append(line)
        # else: skip orphaned lines from a previous broken write
    # Unique per-writer tmp name. Multiple writers can race on this path
    # (60 s tooltip tick from usage-server.py + generate-icon.py invocations
    # from both the server's POST handler and the GNOME extension's tier
    # transitions). A shared `.tmp` filename would let one writer's open()
    # truncate another's in-flight write.
    tmp = DESKTOP.with_suffix(f'.desktop.tmp.{os.getpid()}.{time.time_ns()}')
    tmp.write_text('\n'.join(out) + '\n')
    tmp.replace(DESKTOP)
