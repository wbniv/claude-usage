#!/usr/bin/env python3
"""Generate dock icon PNG with two concentric rings from cached usage data."""
import cairo, math, json, os, shutil, subprocess, sys, time
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
THEME_DIR  = _DATA_HOME / 'icons/hicolor'

def icon_path_for(size):
    return THEME_DIR / f'{size}x{size}/apps/claude-usage.png'

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

# Pacing/color/tier math + the gschema-derived DEFAULTS now live in the
# importable usage_core module — generate-icon.py's hyphenated name can't be
# imported by the macOS menu-bar app, popup-preview, or the parity lints.
# This file keeps only the cairo/PIL rendering pipeline + the GSettings-aware
# load_config() below. Pass-31 (macOS port).
from schema_defaults import RANGES as _SCHEMA_RANGES
from usage_core import (
    DEFAULTS, hex_to_rgba, ring_color, pacing_pct, elapsed_fraction,
    viz_colors, derive_tier,
)

def _gsettings_or_none():
    """Return a Gio.Settings bound to our schema, or None when GSettings is
    unusable (python3-gi absent, or the gschema not registered).

    SRV-1 (pass-29): Gio.Settings.new() on an UNREGISTERED schema id calls
    glib's g_error() → the process aborts with SIGTRAP, which `except Exception`
    cannot catch (the interpreter is already gone). Reachable on a KDE-only
    source install (install.sh skips glib-compile-schemas for the GNOME schema
    there) or any dev checkout before install, whenever
    ~/.config/claude-usage/config.json also doesn't exist yet — then load_config
    falls through to here. SettingsSchemaSource.lookup() returns None for a
    missing schema instead of aborting, so we fall back to DEFAULTS cleanly.
    """
    try:
        from gi.repository import Gio
    except Exception as e:
        print(f"warning: python3-gi unavailable ({e}); using DEFAULTS",
              file=sys.stderr, flush=True)
        return None
    src = Gio.SettingsSchemaSource.get_default()
    if src is None or src.lookup('org.indri.claude-usage', True) is None:
        print("warning: gschema org.indri.claude-usage not registered; using DEFAULTS",
              file=sys.stderr, flush=True)
        return None
    return Gio.Settings.new('org.indri.claude-usage')


def load_config():
    _cfg_json = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') \
                / 'claude-usage' / 'config.json'
    if _cfg_json.exists():
        try:
            raw = json.loads(_cfg_json.read_text())
            cfg = dict(DEFAULTS)
            for key in DEFAULTS:
                if key in raw:
                    cfg[key] = raw[key]
            for key in ('weekly_color_green', 'weekly_color_amber', 'weekly_color_red', 'sonnet_color'):
                try:
                    hex_to_rgba(cfg[key])
                except Exception:
                    print(f"warning: invalid color for {key!r} in config.json, using default",
                          file=sys.stderr, flush=True)
                    cfg[key] = DEFAULTS[key]
            # DIFF-4 (2026-05-30 review): thresholds must be ints. The GSettings
            # path gets that for free from get_uint(), but config.json values are
            # trusted verbatim — a non-int (e.g. "high") would raise TypeError in
            # ring_color's `pct >= cfg[...]` and abort every icon render.
            for key in ('threshold_warning', 'threshold_critical'):
                try:
                    cfg[key] = int(cfg[key])
                except (TypeError, ValueError):
                    print(f"warning: invalid {key!r} in config.json, using default",
                          file=sys.stderr, flush=True)
                    cfg[key] = DEFAULTS[key]
                    continue
                # ICN-1 (pass-29): the KDE SpinBox clamps to the gschema range,
                # but a hand-edited config.json could carry e.g. threshold_warning:0
                # → ring_color() then reads every meter as warning. Reject
                # out-of-range values the same way invalid colors fall back.
                lo, hi = _SCHEMA_RANGES.get(key, (None, None))
                if lo is not None and not (lo <= cfg[key] <= hi):
                    print(f"warning: {key!r}={cfg[key]} out of range [{lo},{hi}] "
                          f"in config.json, using default", file=sys.stderr, flush=True)
                    cfg[key] = DEFAULTS[key]
            return cfg
        except Exception as e:
            print(f"warning: config.json load failed ({e}); falling through to GSettings",
                  file=sys.stderr, flush=True)
    s = _gsettings_or_none()
    if s is None:
        return dict(DEFAULTS)
    try:
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
    except Exception as e:
        # DG-2 (pass-17): silent fallback hid bugs. Log so a broken Gio binding
        # surfaces a reason rather than silently ignoring colour edits.
        print(f"warning: GSettings load failed ({e}); using DEFAULTS",
              file=sys.stderr, flush=True)
        return dict(DEFAULTS)

# hex_to_rgba, ring_color, pacing_pct → moved to usage_core (imported above).

def rounded_rect_path(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + r,     y + r,     r, math.pi,     3*math.pi/2)
    cr.arc(x + w - r, y + r,     r, 3*math.pi/2, 0)
    cr.arc(x + w - r, y + h - r, r, 0,           math.pi/2)
    cr.arc(x + r,     y + h - r, r, math.pi/2,   math.pi)
    cr.close_path()

def draw_ring(cr, cx, cy, radius, thick, pct, color, track=True,
              elapsed_frac=None, over_pace_color=None):
    """Draw a percentage arc.

    Pacing-viz port (post-pass-21):
      • elapsed_frac=None      → legacy single-color arc (backwards-compat,
                                 used for the broken-tier red rendering).
      • elapsed_frac + under-pace (fill < elapsed) → arc in `color`, plus a
                                 thin radial tick at the elapsed angle.
      • elapsed_frac + over-pace (fill > elapsed)  → arc 0→elapsed in
                                 `color`, then elapsed→fill in `over_pace_color`.
    """
    cr.set_line_width(thick)
    cr.set_line_cap(cairo.LINE_CAP_BUTT)
    if track:
        cr.set_source_rgba(*TRACK)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
    if pct <= 0:
        # RV-1 (pass-26): popup-preview pacing_segments emits a tick at
        # elapsed_pos even when fill==0 (the 'zero' canonical case). Draw
        # the tick here too so popup bar and dock ring agree at 0% mid-period.
        if elapsed_frac is not None and 0 < elapsed_frac < 1:
            _start = -math.pi / 2
            elapsed_angle = _start + 2 * math.pi * elapsed_frac
            tick_inner = radius - thick / 2
            tick_outer = radius + thick / 2
            cr.set_source_rgba(0.55, 0.55, 0.55, 0.85)
            cr.set_line_width(max(1.5, thick * 0.18))
            cr.move_to(cx + tick_inner * math.cos(elapsed_angle),
                       cy + tick_inner * math.sin(elapsed_angle))
            cr.line_to(cx + tick_outer * math.cos(elapsed_angle),
                       cy + tick_outer * math.sin(elapsed_angle))
            cr.stroke()
        return

    start = -math.pi / 2
    fill_angle = start + 2 * math.pi * (pct / 100)

    if elapsed_frac is None:
        # Legacy single-color arc.
        cr.set_source_rgba(*color)
        cr.arc(cx, cy, radius, start, fill_angle)
        cr.stroke()
        return

    elapsed_angle = start + 2 * math.pi * elapsed_frac
    fill_frac = pct / 100.0
    over_pacing = fill_frac > elapsed_frac

    if over_pacing and over_pace_color is not None:
        # Over-pace: split arc — on-pace portion in `color`, over-pace
        # portion in `over_pace_color`. The boundary IS the spatial cue;
        # no separate tick needed.
        cr.set_source_rgba(*color)
        cr.arc(cx, cy, radius, start, elapsed_angle)
        cr.stroke()
        cr.set_source_rgba(*over_pace_color)
        cr.arc(cx, cy, radius, elapsed_angle, fill_angle)
        cr.stroke()
        return

    # Single-color arc otherwise.
    cr.set_source_rgba(*color)
    cr.arc(cx, cy, radius, start, fill_angle)
    cr.stroke()

    if over_pacing:
        # Fill is past the elapsed boundary but the caller asked for
        # color-invariant rendering (Sonnet ring: blue stays blue per the
        # wont-fix BUG-5 design rule). No tick — the tick would land
        # inside the filled portion and read as visual noise.
        return

    # Under-pace or on-pace: short radial tick at the elapsed-angle
    # position so the user can see "where you'd be at sustainable burn".
    # Slightly transparent grey so it reads as a marker, not another ring.
    tick_inner = radius - thick / 2
    tick_outer = radius + thick / 2
    cr.set_source_rgba(0.55, 0.55, 0.55, 0.85)
    cr.set_line_width(max(1.5, thick * 0.18))
    cr.move_to(cx + tick_inner * math.cos(elapsed_angle),
               cy + tick_inner * math.sin(elapsed_angle))
    cr.line_to(cx + tick_outer * math.cos(elapsed_angle),
               cy + tick_outer * math.sin(elapsed_angle))
    cr.stroke()

# elapsed_fraction, viz_colors → moved to usage_core (imported above).


def _render(all_pct, sonnet_pct, cfg, draw_rings=True, tier='normal',
            all_pacing=None, sonnet_pacing=None,
            all_elapsed=None, sonnet_elapsed=None):
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
            # so the Claude brand stays recognisable. No pacing-viz on broken
            # tier — the tier IS the message.
            # GI-1 (pass-26): was hex_to_rgba('#e03030') — hardcoded literal
            # that ignored custom GSettings color. Read from cfg so the broken
            # ring respects the same critical color as the normal pacing ring.
            red = hex_to_rgba(cfg['weekly_color_red'])
            draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER, max(all_pct, 100), red)
            draw_ring(cr, cx, cy, R_INNER, THICK_INNER, max(sonnet_pct, 100), red)
        else:
            # Pacing-viz port (post-pass-21): all_pct is now RAW pct, not
            # paced. The arc fills to raw, the color is tier-driven via
            # all_pacing, and elapsed_frac drives the tick / two-tone split.
            ap = all_pacing if all_pacing is not None else all_pct
            on_pace, over_pace = viz_colors(ap, cfg)
            # Backwards-compat: if main() didn't compute elapsed_frac (legacy
            # callers), fall back to the pre-viz behavior — single arc in
            # ring_color(pacing).
            if all_elapsed is None:
                draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER, all_pct, ring_color(ap, cfg))
            else:
                draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER, all_pct, on_pace,
                          elapsed_frac=all_elapsed, over_pace_color=over_pace)
            if sonnet_pct > 0:
                # Sonnet ring intentionally uses fixed blue (wont-fix BUG-5).
                # Pass elapsed_frac to get the tick when under-pace, but no
                # over_pace_color — draw_ring will show single-color when
                # over (the tick disappears, blue stays blue).
                draw_ring(cr, cx, cy, R_INNER, THICK_INNER, sonnet_pct,
                          hex_to_rgba(cfg['sonnet_color']),
                          elapsed_frac=sonnet_elapsed)

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


# derive_tier → moved to usage_core (imported above).

def _refresh_user_icon_cache():
    """Rebuild the user-local hicolor icon cache. Needed when we create new
    size directories (first install, or upgrade adds a new ICON_SIZES entry):
    without an index, GtkIconTheme falls back to a full filesystem walk on
    every lookup — correct but slow — and on some GNOME versions doesn't
    pick up new size dirs at all until logout. Steady-state (cache exists,
    sizes stable) we skip the refresh: mtime bumps from atomic rename are
    enough for GtkIconTheme's inotify watches to invalidate cached pixbufs.

    MS-2 (pass-17): log timeout to stderr — silent swallow meant a slow
    rebuild on a large theme dir (Yaru-style themes can ship 800+ files)
    would leave the user with a stale cache and no diagnostic."""
    if not shutil.which('gtk-update-icon-cache'):
        return
    try:
        subprocess.run(
            ['gtk-update-icon-cache', '-f', '-t', str(THEME_DIR)],
            check=False, capture_output=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        print(f"warning: gtk-update-icon-cache timed out on {THEME_DIR}; "
              f"cache may be stale until next rebuild",
              file=sys.stderr, flush=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass  # cache is an optimization; lookups still work via fs walk


def _atomic_write_multisize(img, sizes=ICON_SIZES):
    """Write `img` to every hicolor size bucket atomically (tmp + rename per
    size). The Cairo pipeline runs once; only the PIL resize per size repeats.

    TF-1: stable filenames under the user icon-theme dir replace the previous
    per-invocation ns-precision scheme in ~/.cache. Atomic rename gives
    crash-safety + mtime-bump on every refresh (which is what GtkIconTheme
    monitors to invalidate cached pixbufs). PID+ns infix in the tmp name
    avoids collisions when two generate-icon.py invocations race (POST
    handler + GNOME extension tier-transition spawn).

    M-1 (pass-17, refined pass-18 MD-1): two-phase commit. Phase 1 writes
    every tmp (the slow work — PIL resize at 5 sizes). Phase 2 renames all
    into place back-to-back. If any save fails in phase 1, no destinations
    are touched yet. The cross-size inconsistency window shrinks from
    "PIL save + rename" (hundreds of ms) to "5 sequential renames"
    (microseconds) — not zero: a SIGKILL between renames in phase 2 still
    leaves N committed and (5-N) on the old vintage. Self-corrects on the
    next icon render.

    MS-1 (pass-17): use BaseException + finally so SIGINT/SIGTERM during
    the loop don't leak tmp files."""
    new_dir = False
    staged = []
    try:
        for size in sizes:
            dest = icon_path_for(size)
            new_dir = new_dir or not dest.parent.exists()
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(
                f'.claude-usage.tmp.{os.getpid()}.{time.time_ns()}.{size}.png'
            )
            img.resize((size, size), RESAMPLE).save(tmp)
            staged.append((tmp, dest))
        # Phase 2: rename. Each individual replace is atomic; doing them all
        # together with no slow work in between minimizes the cross-size
        # observable-inconsistency window.
        for tmp, dest in staged:
            tmp.replace(dest)
        staged = []  # everything committed — nothing to clean up below
    finally:
        # MS-1: also handles BaseException (SIGINT, SIGTERM-then-raise during
        # cleanup). Any tmps left staged were never renamed, so unlink them.
        for tmp, _ in staged:
            try: tmp.unlink()
            except OSError: pass

    # First install (no cache yet) or new size dir (upgrade added an entry to
    # ICON_SIZES) → rebuild so GtkIconTheme indexes the new files. Steady-
    # state: cache present + sizes stable → skip; mtime bumps suffice.
    if new_dir or not (THEME_DIR / 'icon-theme.cache').exists():
        _refresh_user_icon_cache()

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
    # Pacing-viz port (post-pass-21): arc fill = RAW pct (0..100); color and
    # over-pace split decision = pacing; tick/two-tone position = elapsed_frac.
    all_raw     = (all_m or {}).get('pct') or 0
    sonnet_raw  = (sonnet_m or {}).get('pct') or 0
    all_pacing  = pacing_pct(all_m,    period_lens)
    sonnet_pacing = pacing_pct(sonnet_m, period_lens)
    all_elapsed    = elapsed_fraction(all_m,    period_lens)
    sonnet_elapsed = elapsed_fraction(sonnet_m, period_lens)
    tier = tier_override or derive_tier(data)
    img = _render(all_raw, sonnet_raw, cfg, tier=tier,
                  all_pacing=all_pacing, sonnet_pacing=sonnet_pacing,
                  all_elapsed=all_elapsed, sonnet_elapsed=sonnet_elapsed)
    _atomic_write_multisize(img)
    update_desktop(meters, scrape_ts=data.get('_timestamp'))
    print(f'Icon: All={all_raw}%/{all_pacing:.0f}p Sonnet={sonnet_raw}%/{sonnet_pacing:.0f}p '
          f'tier={tier} sizes={ICON_SIZES}', flush=True)

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
