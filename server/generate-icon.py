#!/usr/bin/env python3
"""Generate dock icon PNG with two concentric rings from cached usage data."""
import cairo, math, json, re, sys
from pathlib import Path
from PIL import Image

CACHE_JSON  = Path.home() / '.cache' / 'claude-usage.json'
CACHE_ICON  = Path.home() / '.cache' / 'claude-usage-icon.png'
CONFIG_JSON = Path.home() / '.config' / 'claude-usage' / 'config.json'
DESKTOP     = Path.home() / '.local/share/applications/claude-usage.desktop'

# Icon ships with the GNOME extension; check user-install path first, then system path.
_EXT_REL = Path('gnome-shell/extensions/claude-usage@wbnorris.gmail.com/icons/claude-64.png')
BASE_ICON = next(
    p for p in [
        Path.home() / '.local/share' / _EXT_REL,
        Path('/usr/share') / _EXT_REL,
    ]
    if p.exists()
)

SCALE  = 4
ICON   = 44 * SCALE
CANVAS = 96 * SCALE

# Anthropic orange (sampled from claude-64.png background)
ANTHRO_ORANGE = (216/255, 119/255, 88/255, 1.0)
TRACK         = (0.0, 0.0, 0.0, 0.25)   # subtle dark on orange

DEFAULTS = {
    'weekly_color_green': '#8cff8c',
    'weekly_color_amber': '#ffe033',
    'weekly_color_red':   '#ff5933',
    'sonnet_color':       '#4dbfff',
}

def load_config():
    try:
        cfg = json.loads(CONFIG_JSON.read_text())
        return {**DEFAULTS, **cfg}
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

def draw_ring(cr, cx, cy, radius, thick, pct, color):
    cr.set_line_width(thick)
    cr.set_line_cap(cairo.LINE_CAP_BUTT)
    cr.set_source_rgba(*TRACK)
    cr.arc(cx, cy, radius, 0, 2 * math.pi)
    cr.stroke()
    if pct > 0:
        cr.set_line_cap(cairo.LINE_CAP_BUTT)
        cr.set_source_rgba(*color)
        cr.arc(cx, cy, radius, -math.pi / 2,
               -math.pi / 2 + 2 * math.pi * (pct / 100))
        cr.stroke()

def generate(all_pct, sonnet_pct, cfg):
    cx = cy = CANVAS // 2
    THICK_OUTER, THICK_INNER, GAP = 10 * SCALE, 8 * SCALE, 3 * SCALE
    R_INNER = ICON // 2 + GAP + THICK_INNER // 2
    R_OUTER = R_INNER + THICK_INNER // 2 + GAP + THICK_OUTER // 2

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS, CANVAS)
    cr = cairo.Context(surface)

    # Full Anthropic-orange background with rounded corners
    corner_r = 18 * SCALE
    rounded_rect_path(cr, 0, 0, CANVAS, CANVAS, corner_r)
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

    draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER, all_pct,    ring_color(all_pct, cfg))
    draw_ring(cr, cx, cy, R_INNER, THICK_INNER, sonnet_pct, hex_to_rgba(cfg['sonnet_color']))

    surface.flush()
    img = Image.frombytes('RGBA', (CANVAS, CANVAS),
                          bytes(surface.get_data()), 'raw', 'BGRA')
    img.resize((128, 128), Image.LANCZOS).save(CACHE_ICON)

def update_desktop(all_pct, sonnet_pct):
    if not DESKTOP.exists():
        return
    text = DESKTOP.read_text()
    name = f'Claude Usage — {all_pct}% / {sonnet_pct}%'
    text = re.sub(r'^Name=.*$', f'Name={name}', text, flags=re.MULTILINE)
    DESKTOP.write_text(text)   # write triggers dock file monitor

def main():
    cfg    = load_config()
    data   = json.loads(CACHE_JSON.read_text())
    meters = data.get('meters', [])
    find   = lambda kw: next(
        (m['pct'] for m in meters if kw in (m.get('label') or '').lower()), 0)
    all_pct    = find('all')
    sonnet_pct = find('sonnet')
    generate(all_pct, sonnet_pct, cfg)
    update_desktop(all_pct, sonnet_pct)
    print(f'Icon: All={all_pct}% Sonnet={sonnet_pct}%', flush=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'generate-icon: {e}', file=sys.stderr, flush=True)
        sys.exit(1)
