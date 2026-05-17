#!/usr/bin/env python3
"""
Render dock-icon and panel-icon mockup PNGs for the three tier states
(normal / stale / broken). Run from anywhere; outputs land alongside this
script.

Reuses `generate()` from server/generate-icon.py for the dock icons so the
mockups are pixel-faithful to what production will actually render — only
the ring colors are overridden per tier.
"""
import importlib.util, json, sys, types
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]

# Stub the `tooltip` module before loading generate-icon.py
# (generate-icon.py imports update_desktop from it, which we don't need here).
stub = types.ModuleType('tooltip')
stub.update_desktop = lambda *a, **k: None
sys.modules['tooltip'] = stub

spec = importlib.util.spec_from_file_location('genicon', REPO / 'server/generate-icon.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

# Live data for realistic ring fills.
cache = json.loads((Path.home() / '.cache/claude-usage/usage.json').read_text())
period_lens = cache.get('_period_lengths', {}) or {}
def find(kw): return next((m for m in cache['meters'] if kw in (m.get('label') or '').lower()), None)
all_pct    = g.pacing_pct(find('all'),    period_lens)
sonnet_pct = g.pacing_pct(find('sonnet'), period_lens)
print(f'using live data: All={all_pct:.0f}%  Sonnet={sonnet_pct:.0f}%')

normal_cfg = g.load_config()
GREY = '#888888'
RED  = '#e03030'
stale_cfg  = {**normal_cfg, 'weekly_color_green': GREY, 'weekly_color_amber': GREY,
              'weekly_color_red': GREY, 'sonnet_color': GREY}
broken_cfg = {**normal_cfg, 'weekly_color_green': RED,  'weekly_color_amber': RED,
              'weekly_color_red': RED,  'sonnet_color': RED}

g.generate(all_pct, sonnet_pct, normal_cfg,  HERE / 'dock-normal.png')
g.generate(all_pct, sonnet_pct, stale_cfg,   HERE / 'dock-stale.png')
g.generate(all_pct, sonnet_pct, broken_cfg,  HERE / 'dock-broken.png')

# Per plan: stale variant also desaturates the whole baseline tile (not just rings).
# Convert RGB to luma-grey, keep alpha — mimics what generate-icon.py --tier stale will do.
from PIL import ImageOps
stale_img = Image.open(HERE / 'dock-stale.png').convert('RGBA')
r, gch, b, a = stale_img.split()
grey = ImageOps.grayscale(Image.merge('RGB', (r, gch, b)))
Image.merge('RGBA', (grey, grey, grey, a)).save(HERE / 'dock-stale.png')
print('dock variants written')

# Panel icon mockups — claude-22.png at 4x scale for visibility in the plan doc.
base = Image.open(REPO / 'gnome-extension/icons/claude-22.png').convert('RGBA')
scale = 4
out_size = (base.width * scale, base.height * scale)

base.resize(out_size, Image.LANCZOS).save(HERE / 'panel-normal.png')

# Stale: 40% alpha on the existing icon — what St.Icon.opacity=100 produces.
stale_img = base.copy()
stale_img.putalpha(stale_img.split()[3].point(lambda a: int(a * 0.4)))
stale_img.resize(out_size, Image.LANCZOS).save(HERE / 'panel-stale.png')

# Broken: red tint by multiplying RGB channels (preserve alpha).
def tint(img, tint_rgb):
    tr, tg, tb = tint_rgb
    px = img.load()
    out = Image.new('RGBA', img.size)
    op = out.load()
    for x in range(img.width):
        for y in range(img.height):
            pr, pg, pb, pa = px[x, y]
            op[x, y] = (pr * tr // 255, pg * tg // 255, pb * tb // 255, pa)
    return out

tint(base, (224, 48, 48)).resize(out_size, Image.LANCZOS).save(HERE / 'panel-broken.png')
print('panel variants written')

# Popup mockups — match docs/popup-screenshot.png layout (~564 wide).
# Only the status row at the top changes per tier; meter rows show last-known data.
from PIL import ImageDraw, ImageFont

MONO = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 14)
SANS = ImageFont.truetype('/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf', 14) if Path('/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf').exists() else MONO

POPUP_W   = 564
PAD_X     = 18
ROW_H     = 28
BG        = (250, 250, 250, 255)
FG        = (40,  40,  40,  255)
DIM       = (130, 130, 130, 255)
STALE_FG  = (110, 110, 110, 255)
BROKEN_FG = (224,  48,  48, 255)
SEP       = (220, 220, 220, 255)

import re
def fmt_reset(reset):
    """Port of gnome-extension/extension.js:formatReset()."""
    if not reset: return ''
    m = re.match(r'[Rr]esets? in (\d+) hr (\d+) min', reset)
    if m: return f'resets in {m[1]}:{m[2].zfill(2)}'
    m = re.match(r'[Rr]esets? in (\d+) min', reset)
    if m: return f'resets in 0:{m[1].zfill(2)}'
    m = re.match(r'[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)', reset)
    if m:
        day, h, mn, ap = m[1], int(m[2]), m[3], m[4]
        if ap == 'PM' and h != 12: h += 12
        elif ap == 'AM' and h == 12: h = 0
        return f'resets {day} {h:02d}:{mn}'
    return reset

def fmt_rows(meters, bar_w=10):
    """Mirror gnome-extension/extension.js:formatRows() output."""
    max_label = max(len(m.get('label', '')) for m in meters)
    max_col2  = max(4, *[(len(f"{m['count']}/{m['total']}") if 'count' in m and 'total' in m
                          else len(f"{m.get('pct', 0)}%")) for m in meters])
    rows = []
    for m in meters:
        label = m.get('label', '').ljust(max_label)
        if 'count' in m and 'total' in m:
            col2 = f"{m['count']}/{m['total']}".rjust(max_col2)
            col3 = ' ' * bar_w
            text = f"{label}  {col2}  {col3}"
        else:
            pct = m.get('pct', 0)
            filled = round(pct / 100 * bar_w)
            col2 = f"{pct}%".rjust(max_col2)
            col3 = '█' * filled + '░' * (bar_w - filled)
            reset = fmt_reset(m.get('reset'))
            col4 = f"  {reset}" if reset else ''
            text = f"{label}  {col2}  {col3}{col4}"
        rows.append(text)
    return rows

def render_popup(out_path, status_text, status_color, meter_fg=FG):
    rows = fmt_rows(cache['meters'])
    # Visible meters: skip Sonnet when 0%
    rows = [r for i, r in enumerate(rows) if not (
        'sonnet' in cache['meters'][i].get('label', '').lower()
        and cache['meters'][i].get('pct', 0) == 0)]
    n_rows = len(rows)
    height = PAD_X + ROW_H + ROW_H * n_rows + ROW_H + ROW_H  # status + meters + separator + open-link

    img = Image.new('RGBA', (POPUP_W, height), BG)
    d = ImageDraw.Draw(img)

    # Status row (top)
    d.text((PAD_X, PAD_X), status_text, font=SANS, fill=status_color)

    # Meter rows
    y = PAD_X + ROW_H
    primary_label = 'All models'
    for row, meter in zip(rows, [m for m in cache['meters']
                                  if not ('sonnet' in m.get('label', '').lower() and m.get('pct', 0) == 0)]):
        active = meter.get('label') == primary_label
        prefix = '✴ ' if active else '  '
        d.text((PAD_X, y), prefix + row, font=MONO, fill=meter_fg)
        y += ROW_H

    # Separator
    d.line([(PAD_X, y + 6), (POPUP_W - PAD_X, y + 6)], fill=SEP, width=1)
    y += ROW_H

    # Open link
    d.text((PAD_X, y), 'Open Usage Page', font=SANS, fill=FG)

    img.save(out_path)

render_popup(HERE / 'popup-stale.png',
             'Stale — No update in 12 min', STALE_FG, meter_fg=STALE_FG)
render_popup(HERE / 'popup-broken-local.png',
             'Error — No data in 24 min · run claude-usage-status', BROKEN_FG, meter_fg=STALE_FG)
render_popup(HERE / 'popup-broken-outage.png',
             'Outage — Anthropic reports: Elevated 5xx on Claude.ai', BROKEN_FG)
print('popup variants written')
