#!/usr/bin/env python3
"""Generate dock icon PNG with two concentric rings from cached usage data."""
import cairo, math, json, sys
from pathlib import Path
from PIL import Image

CACHE_JSON = Path.home() / '.cache' / 'claude-usage.json'
CACHE_ICON = Path.home() / '.cache' / 'claude-usage-icon.png'
BASE_ICON  = (Path.home() / '.local/share/gnome-shell/extensions'
              / 'claude-usage@wbnorris.gmail.com/icons/claude-64.png')
DESKTOP    = Path.home() / '.local/share/applications/claude-usage.desktop'

SCALE  = 4
ICON   = 44 * SCALE
CANVAS = 96 * SCALE

TRACK       = (0.20, 0.20, 0.20, 0.60)
BLUE_SONNET = (0.30, 0.75, 1.00, 1.00)

def ring_color(pct):
    if pct >= 80: return (1.00, 0.40, 0.27, 1.0)
    if pct >= 50: return (1.00, 0.73, 0.12, 1.0)
    return             (0.53, 1.00, 0.53, 1.0)

def draw_ring(cr, cx, cy, radius, thick, pct, color):
    cr.set_line_width(thick)
    cr.set_line_cap(cairo.LINE_CAP_BUTT)
    cr.set_source_rgba(*TRACK)
    cr.arc(cx, cy, radius, 0, 2 * math.pi)
    cr.stroke()
    if pct > 0:
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgba(*color)
        end = -math.pi / 2 + 2 * math.pi * (pct / 100)
        cr.arc(cx, cy, radius, -math.pi / 2, end)
        cr.stroke()

def generate(all_pct, sonnet_pct):
    cx = cy = CANVAS // 2
    THICK_OUTER, THICK_INNER, GAP = 10 * SCALE, 8 * SCALE, 3 * SCALE
    R_INNER = ICON // 2 + GAP + THICK_INNER // 2
    R_OUTER = R_INNER + THICK_INNER // 2 + GAP + THICK_OUTER // 2

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS, CANVAS)
    cr = cairo.Context(surface)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()

    draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER, all_pct,    ring_color(all_pct))
    draw_ring(cr, cx, cy, R_INNER, THICK_INNER, sonnet_pct, BLUE_SONNET)

    # Paste base icon
    icon_pil = Image.open(BASE_ICON).convert('RGBA').resize((ICON, ICON), Image.LANCZOS)
    b_ch, g_ch, r_ch, a_ch = icon_pil.split()         # PIL RGBA → Cairo BGRA
    raw = Image.merge('RGBA', (b_ch, g_ch, r_ch, a_ch)).tobytes()
    icon_surf = cairo.ImageSurface.create_for_data(
        bytearray(raw), cairo.FORMAT_ARGB32, ICON, ICON)
    cr.set_source_surface(icon_surf, cx - ICON // 2, cy - ICON // 2)
    cr.paint()

    surface.flush()
    img = Image.frombytes('RGBA', (CANVAS, CANVAS),
                          bytes(surface.get_data()), 'raw', 'BGRA')
    img.resize((128, 128), Image.LANCZOS).save(CACHE_ICON)

    # Touch .desktop file so the dock re-reads and reloads the icon
    if DESKTOP.exists():
        DESKTOP.touch()

def main():
    data    = json.loads(CACHE_JSON.read_text())
    meters  = data.get('meters', [])
    find    = lambda kw: next(
        (m['pct'] for m in meters if kw in (m.get('label') or '').lower()), 0)
    all_pct    = find('all')
    sonnet_pct = find('sonnet')
    generate(all_pct, sonnet_pct)
    print(f'Icon: All={all_pct}% Sonnet={sonnet_pct}%', flush=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'generate-icon: {e}', file=sys.stderr, flush=True)
        sys.exit(1)
