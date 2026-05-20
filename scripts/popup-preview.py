#!/usr/bin/env python3
"""Render an HTML preview of what the GNOME panel popup would show right now.

Reads the live cache + GSettings and mimics the layout/color rules from
gnome-extension/extension.js so popup changes can be eyeballed without a
Wayland logout/login cycle. Wire this up by pointing the .desktop file's
Exec= line at it (the dock-icon click then opens the preview in the
default browser instead of claude.ai/settings/usage).

This is debugging scaffolding — not shipped in the .deb, not in tests.
Mirrors extension.js by hand; the debug section at the bottom of the page
exposes the underlying numbers so deviations are obvious.
"""
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

# ── module imports for shared logic ─────────────────────────────────────────

REPO = Path('/home/will/SRC/claude-usage')
sys.path.insert(0, str(REPO / 'server'))

# Stub heavy imports we don't need (mirrors test_pacing.py + render-mockups.py).
for name in ('cairo',):
    sys.modules.setdefault(name, types.ModuleType(name))
_pil = types.ModuleType('PIL')
_pil_image = types.ModuleType('PIL.Image')
_pil_image.LANCZOS = 1
_pil.Image = _pil_image
_pil.ImageOps = types.ModuleType('PIL.ImageOps')
sys.modules.setdefault('PIL', _pil)
sys.modules.setdefault('PIL.Image', _pil_image)
sys.modules.setdefault('PIL.ImageOps', _pil.ImageOps)

# generate-icon.py raises FileNotFoundError if no base icon exists. The
# real one is at /usr/share/...; we don't open it, just need existence.
_data_home = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
_icon = _data_home / 'gnome-shell/extensions/claude-usage@indri.studio/icons/claude-64.png'
if not _icon.exists():
    sys_icon = Path('/usr/share/gnome-shell/extensions/claude-usage@indri.studio/icons/claude-64.png')
    if not sys_icon.exists():
        _icon.parent.mkdir(parents=True, exist_ok=True)
        _icon.touch()

spec = importlib.util.spec_from_file_location('gi_mod', REPO / 'server/generate-icon.py')
_g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_g)
pacing_pct = _g.pacing_pct
load_config = _g.load_config

spec = importlib.util.spec_from_file_location('tooltip', REPO / 'server/tooltip.py')
_t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_t)
parse_reset = _t.parse_reset
format_tooltip = _t.format_tooltip


# ── data ────────────────────────────────────────────────────────────────────

CACHE = Path.home() / '.cache/claude-usage/usage.json'

def read_cache():
    if not CACHE.exists():
        return None
    return json.loads(CACHE.read_text())


def read_gsettings():
    """Mirror gnome-extension's GSettings reads. Returns dict, all defaults
    on failure (matches the extension's fallback path)."""
    try:
        from gi.repository import Gio
        s = Gio.Settings.new('org.gnome.shell.extensions.claude-usage')
        return {
            'tWarn':       s.get_uint('threshold-warning'),
            'tCrit':       s.get_uint('threshold-critical'),
            'popupNorm':   s.get_string('popup-color-normal'),
            'popupWarn':   s.get_string('popup-color-warning'),
            'popupCrit':   s.get_string('popup-color-critical'),
            'panelNorm':   s.get_string('panel-color-normal'),
            'panelWarn':   s.get_string('panel-color-warning'),
            'panelCrit':   s.get_string('panel-color-critical'),
            'barWidth':    s.get_uint('bar-width'),
            'panelMetric': s.get_string('panel-metric'),
        }
    except Exception as e:
        return {
            'tWarn': 70, 'tCrit': 90,
            'popupNorm': '#cccccc', 'popupWarn': '#d07000', 'popupCrit': '#e03030',
            'panelNorm': '#cccccc', 'panelWarn': '#d07000', 'panelCrit': '#e03030',
            'barWidth': 10, 'panelMetric': '',
            '_gsettings_error': str(e),
        }


# ── rendering: popup ────────────────────────────────────────────────────────

def is_sonnet_hidden(m):
    """extension.js:458 — Sonnet rows with 0% are hidden from the popup."""
    label = (m.get('label') or '').lower()
    return 'sonnet' in label and (m.get('pct') or 0) == 0


def get_primary(meters, cfg):
    """Mirror extension.js _getPrimary: explicit panelMetric → 'all' label → first selectable."""
    label = cfg.get('panelMetric') or ''
    if label:
        found = next((m for m in meters if m.get('label') == label and not is_sonnet_hidden(m)), None)
        if found:
            return found
    return (
        next((m for m in meters if re.search(r'all', m.get('label') or '', re.I) and not is_sonnet_hidden(m)), None)
        or next((m for m in meters if not is_sonnet_hidden(m)), None)
        or (meters[0] if meters else None)
    )


def elapsed_fraction(meter, period_lens):
    """Mirror the pacing_pct floor. Returns 0..1, or None when the floor
    applies (suppresses tick + two-tone — early-period noise is hidden)."""
    rm = meter.get('reset_minutes')
    period = period_lens.get(meter.get('label'))
    if rm is None or not period:
        return None
    elapsed = period - rm
    if elapsed < max(15, period * 0.05):
        return None
    return elapsed / period


def pacing_segments(pct, elapsed_frac, width):
    """Decompose bar into (char, role) tuples. Role ∈ {on_pace, over_pace,
    tick, empty}. Caller maps roles to colors based on tier.

    Visual grammar (docs/plans/2026-05-20-pacing-viz-tick-overpace.md):
      under-pace: filled cells in on_pace + ┊ tick in first empty cell + ░ rest
      on-pace:    filled cells in on_pace + ┊ tick at fill boundary + ░ rest
      over-pace:  filled cells split (on_pace before elapsed_pos, over_pace
                  beyond), no tick — boundary is the color change.
    """
    pct = max(0, min(100, pct or 0))
    fill = round(pct * width / 100)
    elapsed_pos = (min(round(elapsed_frac * width), width)
                   if elapsed_frac is not None else None)

    out = []
    for i in range(width):
        if i < fill:
            if elapsed_pos is not None and i >= elapsed_pos:
                out.append(('█', 'over_pace'))
            else:
                out.append(('█', 'on_pace'))
        else:
            if (elapsed_pos is not None
                    and i == elapsed_pos
                    and fill <= elapsed_pos):
                out.append(('┊', 'tick'))
            else:
                out.append(('░', 'empty'))
    return out


def color_for(role, pacing, cfg):
    """Map a bar segment's role + the row's pacing tier to a CSS color."""
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


def reset_text(meter, anchor_ts):
    """Mirror tooltip.py reset rendering for the popup row's right-side hint."""
    r = parse_reset(
        meter.get('reset') or '',
        reset_minutes=meter.get('reset_minutes'),
        anchor_ts=anchor_ts,
    )
    if not r:
        return ''
    is_countdown, display = r
    return f'resets in ⏱{display}' if is_countdown else f'resets {display}'


def freshness(cache):
    ts = cache.get('_timestamp')
    if not ts:
        return '?'
    age = max(0, int(time.time()) - int(ts))
    if age < 60:
        return '<1m ago'
    if age < 3600:
        return f'{age // 60}m ago'
    return f'{age // 3600}h ago'


def header_line(cache):
    plan = cache.get('plan') or 'Unknown'
    return f'{plan} · {freshness(cache)}'


# ── render ──────────────────────────────────────────────────────────────────

CSS = """
:root {
  --bg: #f5f5f5;
  --popup-bg: #ffffff;
  --popup-border: #ccc;
  --muted: #666;
  --link: #2060c0;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, 'Segoe UI', sans-serif;
  background: var(--bg);
  color: #111;
  padding: 32px;
  margin: 0;
  font-size: 14px;
}
h2 { font-weight: 500; margin: 32px 0 12px; color: #555; font-size: 14px; }
h2:first-child { margin-top: 0; }
.popup {
  background: var(--popup-bg);
  border: 1px solid var(--popup-border);
  border-radius: 6px;
  padding: 12px 16px;
  width: fit-content;
  min-width: 500px;
  font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;
  font-size: 13px;
  white-space: pre;
}
.popup-header { color: var(--muted); margin-bottom: 8px; }
.popup-row { padding: 2px 0; }
.popup-divider {
  border-top: 1px solid #ccc;
  margin: 8px 0 4px;
}
.popup-footer { color: var(--link); padding: 2px 0; }
table.debug {
  border-collapse: collapse;
  font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;
  font-size: 12px;
}
table.debug th, table.debug td {
  padding: 4px 12px;
  border: 1px solid #ddd;
  text-align: left;
}
table.debug th { background: #eee; color: #555; font-weight: normal; }
.tier-crit { color: #cc1010; }
.tier-warn { color: #b05800; }
.tier-ok { color: #444; }
.tier-hidden { color: #aaa; font-style: italic; }
.panel-preview {
  display: inline-block;
  background: #222;
  padding: 6px 12px;
  font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;
  border-radius: 4px;
  margin-right: 12px;
}
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 20px; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; }
.regen-hint { color: var(--muted); font-size: 11px; margin-top: 32px; }
"""


def render_meter_row(m, cfg, primary, period_lens, anchor_ts, label_w):
    """Render one popup row. Pure HTML; no I/O. Used by both the live popup
    and the canonical-cases preview below."""
    label = (m.get('label') or '').ljust(label_w)
    pct = m.get('pct') or 0
    if m.get('count') is not None and m.get('total') is not None:
        col2 = f'{m["count"]}/{m["total"]}'
    else:
        col2 = f'{pct}%'
    elapsed_frac = elapsed_fraction(m, period_lens)
    pacing = pacing_pct(m, period_lens)
    segments = pacing_segments(pct, elapsed_frac, cfg['barWidth'])
    bar_html = ''.join(
        f'<span style="color: {color_for(role, pacing, cfg)}">{ch}</span>'
        for ch, role in segments
    )
    rt = reset_text(m, anchor_ts)
    prefix = '✴ ' if m is primary else '  '
    row_color = color_for('empty', pacing, cfg)
    head = f'{prefix}{label}  {col2:>6}  '
    tail = f'  {rt}'
    return (
        f'<div class="popup-row" style="color: {row_color}">'
        f'{html.escape(head)}{bar_html}{html.escape(tail)}'
        f'</div>'
    )


def render_popup(cache, cfg):
    meters = cache.get('meters') or []
    visible = [m for m in meters if not is_sonnet_hidden(m)]
    if not visible:
        return '<div class="popup">No meters</div>'
    label_w = max(len(m.get('label') or '') for m in visible)
    anchor_ts = cache.get('_timestamp')
    primary = get_primary(meters, cfg)
    period_lens = cache.get('_period_lengths') or {}

    rows_html = [f'<div class="popup-header">{html.escape(header_line(cache))}</div>']
    rows_html.extend(
        render_meter_row(m, cfg, primary, period_lens, anchor_ts, label_w)
        for m in visible
    )
    rows_html.append('<div class="popup-divider"></div>')
    rows_html.append('<div class="popup-footer">Open Usage Page</div>')
    return '<div class="popup">' + ''.join(rows_html) + '</div>'


# Canonical cases — synthetic meters that exercise every pacing state so the
# preview shows what each tier looks like visually, regardless of what the
# live cache happens to contain. Mirrors the verification table in
# docs/plans/2026-05-20-pacing-viz-tick-overpace.md.
CANONICAL_CASES = [
    # (label,         pct, reset_minutes) with period=100 for all rows:
    # elapsed = period - reset_minutes; floor triggers when elapsed < 15.
    ('under-pace',     9,  57),   # e=0.43, fill=1  → tick at idx 4
    ('on-pace',       50,  50),   # e=0.50, fill=5  → tick at idx 5
    ('over-pace',     80,  50),   # e=0.50, fill=8  → 5 normal + 3 hot
    ('way over',     100,  50),   # e=0.50, fill=10 → 5 normal + 5 hot
    ('floor',         50,  95),   # e=0.05 < 15/100 floor → suppressed
    ('zero',           0,  70),   # e=0.30, fill=0  → tick + all empty
    ('maxed',        100,   0),   # e=1.00, fill=10 → all on-pace
]


def render_canonical_cases(cfg):
    meters = [
        {'label': name, 'pct': pct, 'reset_minutes': rm}
        for name, pct, rm in CANONICAL_CASES
    ]
    period_lens = {name: 100 for name, _, _ in CANONICAL_CASES}
    label_w = max(len(m['label']) for m in meters)
    rows = ''.join(
        render_meter_row(m, cfg, None, period_lens, None, label_w)
        for m in meters
    )
    return f'<div class="popup">{rows}</div>'


def render_panel_label(cache, cfg):
    """The little label that lives in the GNOME top bar."""
    meters = cache.get('meters') or []
    primary = next((m for m in meters if m.get('label') == cfg.get('panelMetric')), None)
    if not primary:
        primary = next((m for m in meters if not is_sonnet_hidden(m)), None)
    if not primary:
        return '<span class="panel-preview">no data</span>'
    pct = primary.get('pct', 0)
    period_lens = cache.get('_period_lengths') or {}
    any_crit = any(
        pacing_pct(m, period_lens) >= cfg['tCrit']
        for m in meters
    )
    panel_pacing = pacing_pct(primary, period_lens)
    if any_crit:
        color = cfg['panelCrit']
    elif panel_pacing >= cfg['tWarn']:
        color = cfg['panelWarn']
    else:
        color = cfg['panelNorm']
    return f'<span class="panel-preview" style="color: {color}">✴ {pct}%</span>'


def render_debug(cache, cfg):
    meters = cache.get('meters') or []
    period_lens = cache.get('_period_lengths') or {}

    rows = []
    for m in meters:
        label = m.get('label') or '?'
        pct = m.get('pct', 0)
        rm = m.get('reset_minutes')
        period = period_lens.get(label)
        elapsed = (period - rm) if (rm is not None and period) else None
        floor = max(15, period * 0.05) if period else None
        pacing = pacing_pct(m, period_lens)
        if pacing >= cfg['tCrit']:
            tier_cls, tier = 'tier-crit', 'critical'
        elif pacing >= cfg['tWarn']:
            tier_cls, tier = 'tier-warn', 'warning'
        else:
            tier_cls, tier = 'tier-ok', 'normal'
        visible = '✗ hidden (Sonnet 0%)' if is_sonnet_hidden(m) else '✓'
        rows.append(
            f'<tr class="{tier_cls}">'
            f'<td>{html.escape(label)}</td>'
            f'<td>{pct}</td>'
            f'<td>{rm if rm is not None else "—"}</td>'
            f'<td>{period if period else "—"}</td>'
            f'<td>{elapsed if elapsed is not None else "—"}</td>'
            f'<td>{f"{floor:.0f}" if floor is not None else "—"}</td>'
            f'<td>{pacing:.1f}</td>'
            f'<td>{tier}</td>'
            f'<td>{visible}</td>'
            f'</tr>'
        )

    rows_html = ''.join(rows)
    return f'''
<table class="debug">
  <tr><th>label</th><th>pct</th><th>rm</th><th>period</th><th>elapsed</th><th>floor</th><th>pacing</th><th>tier</th><th>popup-visible</th></tr>
  {rows_html}
</table>
'''


def render_gsettings(cfg):
    keys = ('tWarn', 'tCrit', 'popupNorm', 'popupWarn', 'popupCrit',
            'panelNorm', 'panelWarn', 'panelCrit', 'barWidth', 'panelMetric')
    rows = ''.join(
        f'<dt>{k}</dt><dd>{html.escape(str(cfg.get(k, "?")))}</dd>'
        for k in keys
    )
    err = cfg.get('_gsettings_error')
    if err:
        rows = f'<dt>error</dt><dd style="color:#e03030">{html.escape(err)}</dd>' + rows
    return f'<dl class="kv">{rows}</dl>'


def render_html(cache, cfg):
    if cache is None:
        body = '<p>Cache not found at <code>~/.cache/claude-usage/usage.json</code>.</p>'
    else:
        body = (
            '<h2>Popup as it would appear</h2>'
            + render_popup(cache, cfg)
            + '<h2>Panel label</h2>'
            + render_panel_label(cache, cfg)
            + '<h2>Canonical pacing states</h2>'
            + '<p style="color:#666;font-size:12px;margin:0 0 6px">'
            + 'Synthetic meters (period=100) exercising each visual state. '
            + '┊ = elapsed-fraction tick (only shown when there is headroom). '
            + 'Two-tone fill = on-pace blocks followed by tier-color over-pace blocks.'
            + '</p>'
            + render_canonical_cases(cfg)
            + '<h2>Per-meter debug</h2>'
            + render_debug(cache, cfg)
            + '<h2>Live GSettings</h2>'
            + render_gsettings(cfg)
        )
    ts = time.strftime('%H:%M:%S')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Claude Usage popup preview</title>
<style>{CSS}</style>
</head><body>
{body}
<p class="regen-hint">Rendered at {ts}. Re-click the dock icon to regenerate · reads
{html.escape(str(CACHE))} + live GSettings + pacing_pct from
{html.escape(str(REPO / "server/generate-icon.py"))}.</p>
</body></html>
'''


# ── main ────────────────────────────────────────────────────────────────────

OUT = Path('/tmp/claude-usage-popup-preview.html')


def main():
    cache = read_cache()
    cfg = read_gsettings()
    OUT.write_text(render_html(cache, cfg))
    if shutil.which('xdg-open'):
        subprocess.Popen(['xdg-open', str(OUT)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
