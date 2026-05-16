#!/usr/bin/env python3
"""Generate dock icon PNG with two concentric rings from cached usage data."""
import cairo, math, json, re, sys, datetime
from pathlib import Path
from PIL import Image

CACHE_JSON   = Path.home() / '.cache' / 'claude-usage.json'
CACHE_ICON_A = Path.home() / '.cache' / 'claude-usage-icon-a.png'
CACHE_ICON_B = Path.home() / '.cache' / 'claude-usage-icon-b.png'
DESKTOP      = Path.home() / '.local/share/applications/claude-usage.desktop'

# Icon ships with the GNOME extension; check user-install path first, then system path.
_EXT_REL = Path('gnome-shell/extensions/claude-usage@indri.studio/icons/claude-64.png')
BASE_ICON = next(
    (p for p in [
        Path.home() / '.local/share' / _EXT_REL,
        Path('/usr/share') / _EXT_REL,
    ] if p.exists()),
    None,
)
if BASE_ICON is None:
    raise FileNotFoundError(
        "Base icon not found: checked ~/.local/share and /usr/share")

SCALE  = 4
ICON   = 44 * SCALE
CANVAS = 96 * SCALE

# Anthropic orange (sampled from claude-64.png background)
ANTHRO_ORANGE = (216/255, 119/255, 88/255, 1.0)
TRACK         = (0.0, 0.0, 0.0, 0.25)   # subtle dark on orange

DEFAULTS = {  # keep in sync with gschema.xml default= attributes
    'weekly_color_green': '#8cff8c',
    'weekly_color_amber': '#ffe033',
    'weekly_color_red':   '#ff5933',
    'sonnet_color':       '#4dbfff',
}

def load_config():
    try:
        from gi.repository import Gio
        s = Gio.Settings.new('org.gnome.shell.extensions.claude-usage')
        cfg = {
            'weekly_color_green': s.get_string('weekly-color-green'),
            'weekly_color_amber': s.get_string('weekly-color-amber'),
            'weekly_color_red':   s.get_string('weekly-color-red'),
            'sonnet_color':       s.get_string('sonnet-color'),
            'bar_width':          s.get_uint('bar-width'),
        }
        for key in ('weekly_color_green', 'weekly_color_amber', 'weekly_color_red', 'sonnet_color'):
            try:
                hex_to_rgba(cfg[key])
            except Exception:
                cfg[key] = DEFAULTS[key]
        return cfg
    except Exception:
        return dict(DEFAULTS)

def hex_to_rgba(h):
    h = h.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r/255, g/255, b/255, 1.0)

def ring_color(pct, cfg):
    if pct >= 80: return hex_to_rgba(cfg['weekly_color_red'])
    if pct >= 50: return hex_to_rgba(cfg['weekly_color_amber'])
    return             hex_to_rgba(cfg['weekly_color_green'])

def rounded_rect_path(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + r,     y + r,     r, math.pi,     3*math.pi/2)
    cr.arc(x + w - r, y + r,     r, 3*math.pi/2, 0)
    cr.arc(x + w - r, y + h - r, r, 0,           math.pi/2)
    cr.arc(x + r,     y + h - r, r, math.pi/2,   math.pi)
    cr.close_path()

def draw_ring(cr, cx, cy, radius, thick, pct, color, track=True):
    cr.set_line_width(thick)
    cr.set_line_cap(cairo.LINE_CAP_BUTT)
    if track:
        cr.set_source_rgba(*TRACK)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
    if pct > 0:
        cr.set_line_cap(cairo.LINE_CAP_BUTT)
        cr.set_source_rgba(*color)
        cr.arc(cx, cy, radius, -math.pi / 2,
               -math.pi / 2 + 2 * math.pi * (pct / 100))
        cr.stroke()

def generate(all_pct, sonnet_pct, cfg, dest):
    cx = cy = CANVAS // 2
    THICK_OUTER, THICK_INNER, GAP = 10 * SCALE, 8 * SCALE, 3 * SCALE
    R_INNER = ICON // 2 + GAP + THICK_INNER // 2
    R_OUTER = R_INNER + THICK_INNER // 2 + GAP + THICK_OUTER // 2

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS, CANVAS)
    cr = cairo.Context(surface)

    # Full Anthropic-orange background
    cr.rectangle(0, 0, CANVAS, CANVAS)
    cr.set_source_rgba(*ANTHRO_ORANGE)
    cr.fill()

    # Draw icon before rings so rings render on top (star arms may poke in slightly — intentional)
    icon_surf = cairo.ImageSurface.create_from_png(str(BASE_ICON))
    iw, ih = icon_surf.get_width(), icon_surf.get_height()
    scale = ICON / max(iw, ih)
    cr.save()
    cr.translate(cx - ICON // 2, cy - ICON // 2)
    cr.scale(scale, scale)
    cr.set_source_surface(icon_surf, 0, 0)
    cr.paint()
    cr.restore()

    draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER, all_pct, ring_color(all_pct, cfg))
    if sonnet_pct > 0:
        # Sonnet ring intentionally uses a fixed blue — color family distinguishes it from the outer ring.
        draw_ring(cr, cx, cy, R_INNER, THICK_INNER, sonnet_pct, hex_to_rgba(cfg['sonnet_color']))

    surface.flush()
    img = Image.frombytes('RGBA', (CANVAS, CANVAS),
                          bytes(surface.get_data()), 'raw', 'BGRA')
    img.resize((128, 128), Image.LANCZOS).save(dest)

def _next_icon_path():
    """Alternate between two paths so the .desktop Icon= field always changes,
    forcing GNOME to reload from disk instead of serving a cached pixbuf."""
    if DESKTOP.exists():
        m = re.search(r'^Icon=(.+)$', DESKTOP.read_text(), re.MULTILINE)
        if m and Path(m.group(1)) == CACHE_ICON_A:
            return CACHE_ICON_B
    return CACHE_ICON_A

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

def update_desktop(meters, icon_path, bar_width=10):
    if not DESKTOP.exists():
        return
    name = format_tooltip(meters).replace('\n', r'\n')
    lines = DESKTOP.read_text().splitlines()
    out = []
    for line in lines:
        if line.startswith('Name='):
            out.append(f'Name={name}')
        elif line.startswith('Icon='):
            out.append(f'Icon={icon_path}')
        elif line.startswith('[') or '=' in line or line == '':
            out.append(line)
        # else: skip orphaned lines from a previous broken write
    DESKTOP.write_text('\n'.join(out) + '\n')

def main():
    cfg = load_config()
    if not CACHE_JSON.exists():
        sys.exit(0)  # no data yet — not an error
    data   = json.loads(CACHE_JSON.read_text())
    meters = data.get('meters', [])
    find   = lambda kw: next(
        (m['pct'] for m in meters if kw in (m.get('label') or '').lower()), 0)
    all_pct    = find('all')
    sonnet_pct = find('sonnet')
    dest = _next_icon_path()
    generate(all_pct, sonnet_pct, cfg, dest)
    update_desktop(meters, dest, cfg.get('bar_width', 10))
    print(f'Icon: All={all_pct}% Sonnet={sonnet_pct}%', flush=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'generate-icon: {e}', file=sys.stderr, flush=True)
        sys.exit(1)
