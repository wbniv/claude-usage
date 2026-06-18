"""Shared, importable core: pacing / color / tier math + frontend config.

Extracted (pass-31, macOS port) from `generate-icon.py` — whose hyphenated
filename cannot be `import`ed by a sibling module — and from
`scripts/popup-preview.py`, so the GNOME dock-icon renderer, the popup
preview, the doc-screenshot renderer, the parity lints, AND the macOS
menu-bar app all read ONE implementation of the pacing visualisation.

Pure Python only — no cairo / PIL / Gio imports — so any consumer
(including PyObjC on macOS and the pytest suite) can import it without the
heavy rendering or desktop-toolkit dependencies.

The functions here are kept in sync BY HAND with their JS twins in
`desktop/gnome/extension.js`; `scripts/lint-scraper-parity.py` compares the
numeric + string literals of each pair and fails CI on drift:

    extension.js          ↔  usage_core.py
    pacingPct             ↔  pacing_pct
    elapsedFraction       ↔  elapsed_fraction
    pacingSegments        ↔  pacing_segments
    colorFor              ↔  color_for
"""
import json
import os
from pathlib import Path

# Single source of truth for gschema-tied constants (defaults + ranges).
from schema_defaults import DEFAULTS as _SCHEMA_DEFAULTS, RANGES as _SCHEMA_RANGES

# 6-key subset the dock-ring renderer needs (generate-icon.py's contract).
# Pulled from the gschema at import time so it can never drift from the schema.
DEFAULTS = {k: _SCHEMA_DEFAULTS[k] for k in (
    'weekly_color_green', 'weekly_color_amber', 'weekly_color_red',
    'sonnet_color', 'threshold_warning', 'threshold_critical',
)}


def hex_to_rgba(h):
    h = h.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # BASE-5 (2026-05-30 review): honour an 8-digit #RRGGBBAA alpha instead of
    # silently forcing opacity — a user-set translucent ring colour now renders.
    a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
    return (r/255, g/255, b/255, a)


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

    Kept in sync by hand with desktop/gnome/extension.js:pacingPct.
    """
    if not meter:
        return 0
    pct = meter.get('pct')
    # BASE-5 (2026-05-30 review): accept float as well as int to match
    # extension.js's `typeof pct === 'number'` — the server emits ints, but a
    # foreign/corrupt cache may carry a float, and Python must not silently fall
    # back to raw pct where JS would pace. bool ⊂ int in Python, so exclude it
    # (JS `typeof true === 'boolean'`).
    if isinstance(pct, bool) or not isinstance(pct, (int, float)) or pct == 0:
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
    # Kept in sync by hand with desktop/gnome/extension.js:pacingPct.
    if elapsed < max(15, period * 0.05):
        return pct
    return pct / (elapsed / period)


def elapsed_fraction(meter, period_lens):
    """Fraction of period elapsed for a meter, or None if the pacing floor
    applies (early-period noise). Mirrors extension.js:elapsedFraction.

    Kept in sync by hand with desktop/gnome/extension.js:elapsedFraction
    — the parity lint also checks the numeric constants."""
    if not meter:
        return None
    rm = meter.get('reset_minutes')
    period = period_lens.get(meter.get('label'))
    if rm is None or not period:
        return None
    elapsed = period - rm
    if elapsed < max(15, period * 0.05):
        return None
    return elapsed / period


def viz_colors(pacing, cfg):
    """Return (on_pace, over_pace) rgba pairs for the dock ring's pacing-viz
    rendering. Mirrors color_for() / extension.js:
      on_pace  = always the safe ("green") tier color
      over_pace = warn or crit color depending on pacing"""
    on_pace = hex_to_rgba(cfg['weekly_color_green'])
    if pacing >= cfg['threshold_critical']:
        return on_pace, hex_to_rgba(cfg['weekly_color_red'])
    return on_pace, hex_to_rgba(cfg['weekly_color_amber'])


def pacing_segments(pct, elapsed_frac, width):
    """Decompose bar into (char, role) tuples. Role ∈ {on_pace, over_pace,
    tick, empty}. Caller maps roles to colors based on tier.

    Visual grammar (docs/plans/2026-05-20-pacing-viz-tick-overpace.md):
      under-pace: filled cells in on_pace + ┊ tick in first empty cell + ░ rest
      on-pace:    filled cells in on_pace + ┊ tick at fill boundary + ░ rest
      over-pace:  filled cells split (on_pace before elapsed_pos, over_pace
                  beyond), no tick — boundary is the color change.

    Kept in sync by hand with desktop/gnome/extension.js:pacingSegments.
    """
    pct = max(0, min(100, pct or 0))
    fill_frac = pct / 100
    # PVS-1 (pass-26): decide over-pace on raw fractions BEFORE rounding.
    # When fill_frac and elapsed_frac round to the same cell index the old
    # code emitted a tick (on-pace signal) even when fill_frac > elapsed_frac.
    over_pace_raw = elapsed_frac is not None and fill_frac > elapsed_frac
    fill = round(fill_frac * width)
    elapsed_pos = (min(round(elapsed_frac * width), width)
                   if elapsed_frac is not None else None)

    out = []
    for i in range(width):
        if i < fill:
            # When over_pace_raw and fill == elapsed_pos (both rounded same),
            # color all filled cells over_pace so the user sees the signal.
            over_here = over_pace_raw and (
                elapsed_pos is None or fill == elapsed_pos or i >= elapsed_pos)
            out.append(('█', 'over_pace' if over_here else 'on_pace'))
        else:
            if (not over_pace_raw
                    and elapsed_pos is not None
                    and i == elapsed_pos
                    and fill <= elapsed_pos):
                out.append(('┊', 'tick'))
            else:
                out.append(('░', 'empty'))
    return out


def color_for(role, pacing, cfg):
    """Map a bar segment's role + the row's pacing tier to a CSS color.

    Kept in sync by hand with desktop/gnome/extension.js:colorFor."""
    if role == 'on_pace':
        return cfg['popupNorm']
    if role == 'over_pace':
        return cfg['popupCrit'] if pacing >= cfg['tCrit'] else cfg['popupWarn']
    if role == 'tick':
        return '#888'
    # empty cell + row label/numbers — match the row's tier color
    if pacing >= cfg['tCrit']:
        return cfg['popupCrit']
    if pacing >= cfg['tWarn']:
        return cfg['popupWarn']
    return cfg['popupNorm']


def derive_tier(data):
    """Decide the tier from cache fields (status-page + scrape-fail count).

    Time-based stale/broken is the frontend's job — the GNOME extension and
    the macOS menu-bar app detect age by reading the cache's `_timestamp`.
    This function handles the two signals already encoded in the cache itself.
    """
    astat = data.get('_anthropic_status') or {}
    # V-3 (pass-17): normalize ''/None to the safe value via `or` so an
    # empty-string field doesn't silently trigger the broken tier.
    indicator = astat.get('indicator') or 'none'
    if indicator != 'none':
        return 'broken'
    component = astat.get('claude_ai_component_status') or 'operational'
    if component != 'operational':
        return 'broken'
    # DT-1 (pass-18): isinstance guard before the comparison so a pre-existing
    # corrupt cache (`"5" >= 2`) can't raise TypeError on every render.
    sfc = data.get('_scrape_fail_count')
    if isinstance(sfc, int) and not isinstance(sfc, bool) and sfc >= 2:
        return 'broken'
    return 'normal'


# ── frontend config (config.json → schema defaults; no GSettings) ────────────
#
# generate-icon.py keeps its own GSettings-aware load_config() (the GNOME dock
# icon reads dconf). Frontends that aren't GNOME — the macOS menu-bar app — use
# load_ui_config(): the neutral ~/.config/claude-usage/config.json the KDE port
# established, overlaid on the gschema defaults. Returns EVERY UI key (snake_case),
# unlike the 6-key icon config.

_COLOR_KEYS = frozenset(k for k in _SCHEMA_DEFAULTS if 'color' in k)
_SKIP = object()  # _coerce sentinel: value invalid/unknown → caller skips it


def _coerce(key, val):
    """Validate/coerce a raw config value for `key`. Returns the value to store,
    or _SKIP if the key is unknown or the value is invalid (bad hex, non-int or
    out-of-range number, wrong type). Single source of validation shared by
    load_ui_config (reads) and write_ui_config (writes)."""
    if key not in _SCHEMA_DEFAULTS:
        return _SKIP
    default = _SCHEMA_DEFAULTS[key]
    if key in _COLOR_KEYS:
        try:
            hex_to_rgba(val)              # validates 6/8-digit hex
            return val
        except Exception:
            return _SKIP
    if isinstance(default, bool):         # bool ⊂ int — check first
        return val if isinstance(val, bool) else _SKIP
    if isinstance(default, int):
        try:
            iv = int(val)
        except (TypeError, ValueError):
            return _SKIP
        lo, hi = _SCHEMA_RANGES.get(key, (None, None))
        if lo is not None and not (lo <= iv <= hi):
            return _SKIP
        return iv
    return val if isinstance(val, str) else _SKIP


def config_path():
    return (Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
            / 'claude-usage' / 'config.json')


def load_ui_config():
    """Full UI config for non-GNOME frontends: schema defaults overlaid with
    ~/.config/claude-usage/config.json. Invalid values (bad color, out-of-range
    or non-int threshold, wrong type) fall back to the schema default per key —
    never raises, so a hand-edited config can't wedge the menu bar."""
    cfg = dict(_SCHEMA_DEFAULTS)
    p = config_path()
    raw = {}
    if p.exists():
        try:
            loaded = json.loads(p.read_text())
            if isinstance(loaded, dict):
                raw = loaded
        except Exception:
            raw = {}
    for key in _SCHEMA_DEFAULTS:
        if key in raw:
            v = _coerce(key, raw[key])
            if v is not _SKIP:
                cfg[key] = v
    return cfg


def write_ui_config(updates):
    """Merge `updates` into ~/.config/claude-usage/config.json and write it
    atomically (tmp + rename, 0600). Only known keys with valid values are
    applied (via _coerce — same rules as load_ui_config); unknown/invalid
    entries are dropped, and other keys already in the file are preserved. Used
    by the macOS preferences window. Returns the merged dict written."""
    p = config_path()
    current = {}
    if p.exists():
        try:
            loaded = json.loads(p.read_text())
            if isinstance(loaded, dict):
                current = loaded
        except Exception:
            current = {}
    for key, val in (updates or {}).items():
        v = _coerce(key, val)
        if v is not _SKIP:
            current[key] = v
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(current, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(p)
    return current
