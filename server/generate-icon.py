#!/usr/bin/env python3
"""Generate dock icon PNG with two concentric rings from cached usage data."""
import cairo, math, json, os, sys, time
from pathlib import Path
from PIL import Image, ImageOps

# Forward-compat: Pillow 9.1+ moved LANCZOS under Image.Resampling and
# deprecated the top-level alias. getattr fallback keeps older Pillow happy.
RESAMPLE = getattr(Image, 'Resampling', Image).LANCZOS

from tooltip import update_desktop  # parse_reset, format_tooltip used via update_desktop

_CACHE_HOME  = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
_DATA_HOME   = Path(os.environ.get('XDG_DATA_HOME')  or Path.home() / '.local' / 'share')
CACHE_DIR    = _CACHE_HOME / 'claude-usage'
CACHE_JSON   = CACHE_DIR / 'usage.json'

# TF-1 (pass-16 §13): write the dynamic icon to the user icon-theme dir
# under a stable name so the .desktop file's Icon=claude-usage (already the
# install-time default in build-deb.sh and claude-usage-setup) resolves to
# the latest dynamic version. Lives outside ~/.cache so `rm -rf ~/.cache`
# (a documented uninstall step) doesn't strand the launcher with a missing
# icon — and when the user file is missing, GNOME falls back to the system
# baseline at /usr/share/pixmaps/claude-usage.png shipped by the .deb.
#
# Multi-size emission: we write the live ring-painted icon to several
# hicolor size buckets. XDG icon-theme lookup picks the directory whose size
# is closest to what the consumer requested, so without 64x64 + 48x48
# user-local variants the dock (which typically asks for ~32–48 px) would
# fall through to /usr/share/icons/hicolor/64x64/apps/claude-usage.png —
# the ringless baseline shipped by the .deb — and the dock would show no
# rings. Emitting at every plausible size keeps the live version winning.
ICON_SIZES = (48, 64, 96, 128, 256)

def icon_path_for(size):
    return _DATA_HOME / f'icons/hicolor/{size}x{size}/apps/claude-usage.png'

ICON_OUT = icon_path_for(128)  # back-compat alias; main() emits all sizes

# Icon ships with the GNOME extension; check user-install path first, then system path.
_EXT_REL = Path('gnome-shell/extensions/claude-usage@indri.studio/icons/claude-64.png')
BASE_ICON = next(
    (p for p in [
        _DATA_HOME / _EXT_REL,
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
                print(f"warning: invalid color for {key!r}, using default", file=sys.stderr, flush=True)
                cfg[key] = DEFAULTS[key]
        return cfg
    except Exception:
        return dict(DEFAULTS)

def hex_to_rgba(h):
    h = h.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r/255, g/255, b/255, 1.0)

def ring_color(pct, cfg):
    # load_config() unconditionally populates both threshold keys (live or DEFAULTS),
    # so the previous .get(default) was dead defense.
    if pct >= cfg['threshold_critical']: return hex_to_rgba(cfg['weekly_color_red'])
    if pct >= cfg['threshold_warning']:  return hex_to_rgba(cfg['weekly_color_amber'])
    return                                      hex_to_rgba(cfg['weekly_color_green'])

def pacing_pct(meter, period_lens):
    """pct / fraction_elapsed — uncapped. 100 = on pace, > 100 = over pace.
    Falls back to raw pct when reset_minutes/period unknown or too few
    minutes have elapsed for one user action to be statistical noise.

    Kept in sync by hand with gnome-extension/extension.js:pacingPct.
    """
    if not meter:
        return 0
    pct = meter.get('pct')
    if not isinstance(pct, int) or pct == 0:
        return pct or 0
    rm = meter.get('reset_minutes')
    period = period_lens.get(meter.get('label'))
    if rm is None or not period:
        return pct
    elapsed = period - rm
    # Floor = max(15 min, 5% of period). WP-1 (pass-16 §6): flat 15-min was
    # right for the 5h session bucket (15/300=5% elapsed) but for 7d weekly
    # buckets meant any usage > ~0.14% in the first 16 min paced > critical.
    # Period-scaled component gives the weekly bucket ~8.4h suppression. The
    # session bucket sees max(15, 14.75)=15 — unchanged from 0.11.14.
    # Kept in sync by hand with gnome-extension/extension.js:pacingPct.
    if elapsed < max(15, period * 0.05):
        return pct
    return pct / (elapsed / period)

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

def _render(all_pct, sonnet_pct, cfg, draw_rings=True, tier='normal'):
    """Cairo + PIL pipeline; returns the rendered PIL Image at CANVAS px.
    No I/O. Callers resize and save."""
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
        if tier == 'broken':
            # Both rings rendered in a solid alarm-red, baseline tile unchanged
            # so the Claude brand stays recognisable.
            red = hex_to_rgba('#e03030')
            draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER, max(all_pct, 100), red)
            draw_ring(cr, cx, cy, R_INNER, THICK_INNER, max(sonnet_pct, 100), red)
        else:
            draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER, all_pct, ring_color(all_pct, cfg))
            if sonnet_pct > 0:
                # Sonnet ring intentionally uses a fixed blue — color family distinguishes it from the outer ring.
                draw_ring(cr, cx, cy, R_INNER, THICK_INNER, sonnet_pct, hex_to_rgba(cfg['sonnet_color']))

    surface.flush()
    img = Image.frombytes('RGBA', (CANVAS, CANVAS),
                          bytes(surface.get_data()), 'raw', 'BGRA')
    # Stale tier: desaturate the whole tile (rings + baseline orange + star)
    # so the icon reads as "data is suspect" at a glance.
    if tier == 'stale':
        r, g, b, a = img.split()
        grey = ImageOps.grayscale(Image.merge('RGB', (r, g, b)))
        img = Image.merge('RGBA', (grey, grey, grey, a))
    return img


def generate(all_pct, sonnet_pct, cfg, dest, draw_rings=True, tier='normal'):
    """Render and save to a single dest at 128×128. Kept for --baseline mode
    and for any external callers that pass an arbitrary path."""
    img = _render(all_pct, sonnet_pct, cfg, draw_rings, tier)
    img.resize((128, 128), RESAMPLE).save(dest)


def derive_tier(data):
    """Decide the tier from cache fields (status-page + scrape-fail count).

    Time-based stale/broken is the GNOME extension's job — it detects age by
    reading the cache's `_timestamp` and spawns generate-icon.py --tier=stale
    or --tier=broken explicitly. This function handles the two signals that
    are already encoded in the cache itself.
    """
    astat = data.get('_anthropic_status') or {}
    if astat.get('indicator') not in (None, 'none'):
        return 'broken'
    if astat.get('claude_ai_component_status') not in (None, 'operational'):
        return 'broken'
    if (data.get('_scrape_fail_count') or 0) >= 2:
        return 'broken'
    return 'normal'

def _atomic_write_multisize(img, sizes=ICON_SIZES):
    """Write `img` to every hicolor size bucket atomically (tmp + rename per
    size). The Cairo pipeline runs once; only the PIL resize per size repeats.

    TF-1: stable filenames under the user icon-theme dir replace the previous
    per-invocation ns-precision scheme in ~/.cache. Atomic rename gives
    crash-safety + mtime-bump on every refresh (which is what GtkIconTheme
    monitors to invalidate cached pixbufs). PID+ns infix in the tmp name
    avoids collisions when two generate-icon.py invocations race (POST
    handler + GNOME extension tier-transition spawn)."""
    for size in sizes:
        dest = icon_path_for(size)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(
            f'.claude-usage.tmp.{os.getpid()}.{time.time_ns()}.{size}.png'
        )
        try:
            img.resize((size, size), RESAMPLE).save(tmp)
            tmp.replace(dest)
        except Exception:
            try: tmp.unlink()
            except OSError: pass
            raise

def main(tier_override=None):
    cfg = load_config()
    if not CACHE_JSON.exists():
        sys.exit(0)  # no data yet — not an error
    data   = json.loads(CACHE_JSON.read_text())
    meters = data.get('meters', [])
    period_lens = data.get('_period_lengths', {}) or {}
    # substring match — works for current labels; revisit if Anthropic adds "overall" etc.
    find_meter = lambda kw: next(
        (m for m in meters if kw in (m.get('label') or '').lower()), None)
    all_m    = find_meter('all')
    sonnet_m = find_meter('sonnet')
    all_pct    = min(100.0, pacing_pct(all_m,    period_lens))
    sonnet_pct = min(100.0, pacing_pct(sonnet_m, period_lens))
    tier = tier_override or derive_tier(data)
    img = _render(all_pct, sonnet_pct, cfg, tier=tier)
    _atomic_write_multisize(img)
    update_desktop(meters, scrape_ts=data.get('_timestamp'))
    print(f'Icon: All={all_pct:.0f}% Sonnet={sonnet_pct:.0f}% (pacing) tier={tier} sizes={ICON_SIZES}', flush=True)

if __name__ == '__main__':
    # --baseline DEST: render the placeholder tile (rounded-rect + orange + star,
    # no rings) used as the system icon shipped in the .deb so the dock looks
    # consistent before any usage data has been fetched.
    # --tier {normal,stale,broken}: override the cache-derived tier. Used by
    # the GNOME extension for time-based stale/broken (it knows the cache
    # is N minutes old; generate-icon.py only sees the cache contents).
    USAGE = (
        "Usage: generate-icon.py                                # render from cache\n"
        "       generate-icon.py --baseline DEST                # render placeholder tile\n"
        "       generate-icon.py --tier {normal,stale,broken}   # override cache-derived tier"
    )
    args = sys.argv[1:]
    if args and args[0] in ('-h', '--help'):
        print(USAGE)
        sys.exit(0)
    try:
        if args and args[0] == '--baseline':
            if len(args) != 2:
                print(USAGE, file=sys.stderr)
                sys.exit(2)
            generate(0, 0, dict(DEFAULTS), Path(args[1]), draw_rings=False)
            sys.exit(0)
        tier_override = None
        if args and args[0] == '--tier':
            if len(args) != 2 or args[1] not in ('normal', 'stale', 'broken'):
                print(USAGE, file=sys.stderr)
                sys.exit(2)
            tier_override = args[1]
        elif args:
            # Anything else is a usage error rather than a silent fall-through to
            # main(): the old "unknown args silently ignored" path made dev-time
            # typos invisible.
            print(USAGE, file=sys.stderr)
            sys.exit(2)
        main(tier_override)
    except Exception as e:
        print(f'generate-icon: {e}', file=sys.stderr, flush=True)
        sys.exit(1)
