"""Tooltip rendering shared between usage-server.py (60 s tick) and
generate-icon.py (15 min full POST regen)."""
import datetime, re
from pathlib import Path

DESKTOP = Path.home() / '.local/share/applications/claude-usage.desktop'


def parse_reset(reset):
    """Returns (is_countdown, display) or None. Countdown shows ⏱h:mm; day shows 'Tue 1:00'."""
    if not reset:
        return None
    m = re.match(r'[Rr]esets? in (\d+) hr (\d+) min', reset)
    if m:
        return (True, f"{m.group(1)}:{int(m.group(2)):02d}")
    m = re.match(r'[Rr]esets? in (\d+) min', reset)
    if m:
        return (True, f"0:{int(m.group(1)):02d}")
    m = re.match(r'[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)', reset)
    if m:
        day, h, mn, ap = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        if ap == 'PM' and h != 12: h += 12
        elif ap == 'AM' and h == 12: h = 0
        now = datetime.datetime.now()
        wd = {'Mon':0,'Tue':1,'Wed':2,'Thu':3,'Fri':4,'Sat':5,'Sun':6}.get(day, 0)
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


def format_tooltip(meters):
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
        reset_info = parse_reset(meter.get('reset'))
        if reset_info:
            is_countdown, display = reset_info
            part += f" ⏱{display}" if is_countdown else f" {display}"
        parts.append(part)
    return '   |   '.join(parts) if parts else 'Claude Usage'


def update_desktop(meters, icon_path=None):
    """Rewrite the .desktop launcher's Name= line with a fresh tooltip.

    If icon_path is None, preserve the existing Icon= line — that's the
    path the 60 s tick takes from usage-server.py; the 15 min regen
    from generate-icon.py passes a fresh timestamped path."""
    if not DESKTOP.exists():
        return
    name = format_tooltip(meters).replace('\n', r'\n')
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
    tmp = DESKTOP.with_suffix(DESKTOP.suffix + '.tmp')
    tmp.write_text('\n'.join(out) + '\n')
    tmp.replace(DESKTOP)
