"""Tooltip rendering shared between usage-server.py (60 s tick) and
generate-icon.py (full POST regen on each scrape)."""
import datetime, os, re, sys, time
from pathlib import Path

_DATA_HOME = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
DESKTOP = _DATA_HOME / 'applications' / 'claude-usage.desktop'

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
        # BASE-4 (2026-05-30 review): normalise total minutes so an input like
        # "1 hr 90 min" rolls over to 2:30 instead of rendering "1:90". Mirrors
        # the live branch above and desktop/gnome/extension.js::formatReset.
        total = int(m.group(1)) * 60 + int(m.group(2))
        return (True, f"{total // 60}:{total % 60:02d}")
    m = re.match(r'[Rr]esets? in (\d+) min', reset)
    if m:
        total = int(m.group(1))
        return (True, f"{total // 60}:{total % 60:02d}")
    m = re.match(r'[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)', reset)
    if m:
        day, h, mn, ap = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        # Unknown day (locale change, formatter glitch) — return None so the
        # caller falls back to the literal reset string rather than silently
        # defaulting to Monday and rendering the wrong reset day.
        if day not in WD_MAP:
            return None
        # Parity with the JS twins (scraper.js, background.js, extension.js)
        # which all return null on out-of-range values. Without this, a
        # malformed reset like "Resets Tue 25:99 AM" passes the regex and
        # raises ValueError from datetime.replace, dumping a Python traceback
        # to the journal via _tooltip_tick's / generate-icon.py's outer
        # try/except (T-8, pass-15 §4).
        if not (1 <= h <= 12 and 0 <= mn <= 59):
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
        # 12 h matches extension.js::formatReset (set in 0.11.10): resets more
        # than half a day away show a concrete day+time rather than ⏱h:mm.
        # Two adjacent UI surfaces (popup row and dock-launcher tooltip) must
        # agree on the threshold or they read inconsistently for the same meter.
        if mins < 12 * 60:
            return (True, f"{mins // 60}:{mins % 60:02d}")
        return (False, f"{day} {h:02d}:{mn:02d}")

    return None


# TT-1 (pass-18 finding, fixed post-pass-21): one-shot guard for the
# unrecognised-labels warning. _tooltip_tick calls format_tooltip every 60s,
# so an unfixable mismatch (claude.ai renamed meter labels) used to produce
# 1440 identical stderr lines per day. Once-per-process is enough — the
# user sees the signal and the journal stays clean.
_unrecognised_warned = False


def format_tooltip(meters, anchor_ts=None):
    find = lambda kw: next((m for m in meters if kw in (m.get('label') or '').lower()), None)
    current = find('session') or find('current')
    all_m   = find('all')
    sonnet  = find('sonnet')
    global _unrecognised_warned
    if meters and not (current or all_m) and not _unrecognised_warned:
        print("warning: no recognisable meter labels found; tooltip may be empty "
              "(suppressing further occurrences this session)",
              file=sys.stderr, flush=True)
        _unrecognised_warned = True
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
    return 'Claude Usage   ✴   ' + '   |   '.join(parts) if parts else 'Claude Usage'


def update_desktop(meters, scrape_ts=None):
    """Rewrite the .desktop launcher with fresh Name= tooltip text.

    TF-1 + D-1 (pass-16 §7, §13): always full read-parse-write — race-free
    against any concurrent writer (the old re.sub Name=-only shortcut could
    revert a fresh Icon= line back to its previous value in the rare overlap
    with generate-icon.py's writes). Also always pins Icon=claude-usage so a
    pre-0.11.18 .desktop with an absolute Icon= path gets migrated on the
    first 60s tick after upgrade.

    scrape_ts: when supplied, countdown resets are recomputed live."""
    if not DESKTOP.exists():
        return
    name = format_tooltip(meters, anchor_ts=scrape_ts).replace('\n', r'\n')
    text = DESKTOP.read_text()
    out = []
    saw_name = saw_icon = False
    # UD-1 (pass-26): only rewrite Name=/Icon= inside [Desktop Entry], not
    # inside [Desktop Action ...] subgroups which have their own Name= lines.
    in_main_section = True
    for line in text.splitlines():
        if line.startswith('[') and line.endswith(']'):
            in_main_section = (line == '[Desktop Entry]')
            out.append(line)
            continue
        if in_main_section and line.startswith('Name='):
            out.append(f'Name={name}')
            saw_name = True
        elif in_main_section and line.startswith('Icon='):
            # Stable icon-theme name. Resolves via XDG icon lookup to
            # ~/.local/share/icons/hicolor/128x128/apps/claude-usage.png
            # (written by generate-icon.py) with /usr/share/pixmaps/claude-usage.png
            # as the .deb-shipped baseline fallback.
            out.append('Icon=claude-usage')
            saw_icon = True
        else:
            out.append(line)
    # D-1 (pass-17): if a malformed/partial .desktop was missing the line,
    # the previous version silently dropped it too. Append so the tooltip
    # never disappears just because the file got corrupted.
    if not saw_name:
        out.append(f'Name={name}')
    if not saw_icon:
        out.append('Icon=claude-usage')
    new_text = '\n'.join(out) + '\n'
    if new_text == text:
        return
    tmp = DESKTOP.with_suffix(f'.desktop.tmp.{os.getpid()}.{time.time_ns()}')
    tmp.write_text(new_text)
    tmp.replace(DESKTOP)
