#!/usr/bin/env python3
"""Generate dock icon PNG with two concentric rings from cached usage data."""
import cairo, math, json, sys
from pathlib import Path
from PIL import Image

from tooltip import update_desktop  # parse_reset, format_tooltip used via update_desktop

CACHE_DIR    = Path.home() / '.cache' / 'claude-usage'
CACHE_JSON   = CACHE_DIR / 'usage.json'

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
    'threshold_warning':  50,
    'threshold_critical': 80,
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
            'threshold_warning':  s.get_uint('threshold-warning'),
            'threshold_critical': s.get_uint('threshold-critical'),
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
    if pct >= cfg.get('threshold_critical', 80): return hex_to_rgba(cfg['weekly_color_red'])
    if pct >= cfg.get('threshold_warning',  50): return hex_to_rgba(cfg['weekly_color_amber'])
    return                                             hex_to_rgba(cfg['weekly_color_green'])

def pacing_pct(meter, period_lens):
    """pct / fraction_elapsed — uncapped. 100 = on pace, > 100 = over pace.
    Falls back to raw pct when reset_minutes/period unknown or
    fraction_elapsed is too small to trust."""
    if not meter:
        return 0
    pct = meter.get('pct')
    if not isinstance(pct, int) or pct == 0:
        return pct or 0
    rm = meter.get('reset_minutes')
    period = period_lens.get(meter.get('label'))
    if rm is None or not period:
        return pct
    fraction = 1 - rm / period
    if fraction <= 0.01:
        return pct
    return pct / fraction

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

def generate(all_pct, sonnet_pct, cfg, dest, draw_rings=True):
    cx = cy = CANVAS // 2
    THICK_OUTER, THICK_INNER, GAP = 10 * SCALE, 8 * SCALE, 3 * SCALE
    R_INNER = ICON // 2 + GAP + THICK_INNER // 2
    R_OUTER = R_INNER + THICK_INNER // 2 + GAP + THICK_OUTER // 2

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS, CANVAS)
    cr = cairo.Context(surface)

    # Clip to rounded rect so corners are transparent (matches GNOME icon style)
    corner_r = 18 * SCALE
    rounded_rect_path(cr, 0, 0, CANVAS, CANVAS, corner_r)
    cr.clip()

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

    if draw_rings:
        draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER, all_pct, ring_color(all_pct, cfg))
        if sonnet_pct > 0:
            # Sonnet ring intentionally uses a fixed blue — color family distinguishes it from the outer ring.
            draw_ring(cr, cx, cy, R_INNER, THICK_INNER, sonnet_pct, hex_to_rgba(cfg['sonnet_color']))

    surface.flush()
    img = Image.frombytes('RGBA', (CANVAS, CANVAS),
                          bytes(surface.get_data()), 'raw', 'BGRA')
    img.resize((128, 128), Image.LANCZOS).save(dest)

def _next_icon_path():
    """Return a fresh timestamped path so GNOME never serves a cached pixbuf."""
    import time
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Nanosecond precision: two same-second invocations would otherwise collide
    # on the filename, silently dropping the second icon refresh.
    return CACHE_DIR / f'icon-{time.time_ns()}.png'

def main():
    cfg = load_config()
    if not CACHE_JSON.exists():
        sys.exit(0)  # no data yet — not an error
    data   = json.loads(CACHE_JSON.read_text())
    meters = data.get('meters', [])
    period_lens = data.get('_period_lengths', {}) or {}
    find_meter = lambda kw: next(
        (m for m in meters if kw in (m.get('label') or '').lower()), None)
    all_m    = find_meter('all')
    sonnet_m = find_meter('sonnet')
    all_pct    = pacing_pct(all_m,    period_lens)
    sonnet_pct = pacing_pct(sonnet_m, period_lens)
    dest = _next_icon_path()
    generate(all_pct, sonnet_pct, cfg, dest)
    for old in CACHE_DIR.glob('icon-*.png'):
        if old != dest:
            try:
                old.unlink()
            except OSError:
                pass
    update_desktop(meters, dest, scrape_ts=data.get('_timestamp'))
    print(f'Icon: All={all_pct:.0f}% Sonnet={sonnet_pct:.0f}% (pacing)', flush=True)

if __name__ == '__main__':
    try:
        # --baseline DEST: render the placeholder tile (rounded-rect + orange + star,
        # no rings) used as the system icon shipped in the .deb so the dock looks
        # consistent before any usage data has been fetched.
        if len(sys.argv) >= 2 and sys.argv[1] == '--baseline':
            if len(sys.argv) < 3:
                print('usage: generate-icon.py --baseline DEST', file=sys.stderr)
                sys.exit(2)
            generate(0, 0, dict(DEFAULTS), Path(sys.argv[2]), draw_rings=False)
            sys.exit(0)
        main()
    except Exception as e:
        print(f'generate-icon: {e}', file=sys.stderr, flush=True)
        sys.exit(1)
