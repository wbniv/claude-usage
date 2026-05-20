"""Shared helper for the docs/ image-generation scripts.

Each scripts/render-*.py builds its synthetic popup state and HTML, then calls
html_to_png() to convert it to a tightly-cropped PNG via headless Chrome.

Out-of-band so the per-image scripts can stay focused on the data they
synthesize — the chrome invocation + bounding-box crop is identical across
all of them.

Requires google-chrome or chromium on PATH (already a Recommends: of the .deb).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


def html_to_png(html, dest, *, viewport=(800, 600), scale=2, padding=8):
    """Render `html` to `dest` via headless Chrome, crop trailing background.

    viewport: pixel size of the chrome window (logical pixels, pre-scale).
              Must be larger than the rendered popup or the crop will clip.
    scale: device-pixel ratio. 2 gives a crisp result when GitHub displays
           the image at ~half native width (which is what width=564 does
           on a ~1128-px-wide raw PNG).
    padding: extra transparent margin added around the cropped content."""
    browser = (shutil.which('google-chrome')
               or shutil.which('chromium-browser')
               or shutil.which('chromium'))
    if not browser:
        sys.exit('html_to_png: google-chrome / chromium not on PATH')

    dest = Path(dest)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        page = td / 'page.html'
        page.write_text(html, encoding='utf-8')
        raw = td / 'raw.png'
        subprocess.run([
            browser,
            '--headless=new',
            '--disable-gpu',
            '--no-sandbox',
            '--hide-scrollbars',
            '--default-background-color=00000000',
            f'--screenshot={raw}',
            f'--window-size={viewport[0]},{viewport[1]}',
            f'--force-device-scale-factor={scale}',
            page.as_uri(),
        ], check=True, capture_output=True)

        img = Image.open(raw).convert('RGBA')
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        if padding:
            w, h = img.size
            padded = Image.new('RGBA', (w + 2 * padding, h + 2 * padding),
                               (0, 0, 0, 0))
            padded.paste(img, (padding, padding), img)
            img = padded
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)
    return dest


def load_popup_preview():
    """Import scripts/popup-preview.py via importlib (hyphenated filename
    can't be a normal import). Returns the loaded module."""
    import importlib.util
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        'popup_preview', here / 'popup-preview.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── production-mode rendering ──────────────────────────────────────────────
#
# popup-preview.py's renderer emits per-cell spans for the pacing-viz
# prototype (tick + over-pace two-tone). Those visuals are not yet shipped in
# extension.js, so the docs/ screenshots use this simpler production path
# instead: whole row colored by pacing tier, plain single-tone █░ bars, no
# per-character coloring. Mirrors extension.js:formatRows exactly. When the
# prototype lands in extension.js, swap callers back to pp.render_popup and
# delete this block.

def _tier_color(pacing, cfg):
    if pacing >= cfg['tCrit']:
        return cfg['popupCrit']
    if pacing >= cfg['tWarn']:
        return cfg['popupWarn']
    return cfg['popupNorm']


def production_meter_row(m, cfg, *, primary, period_lens, anchor_ts, label_w, pp):
    """Render a single popup row in production style (single-color, no tick,
    no two-tone). `pp` is the popup-preview module (for header_line, reset_text,
    pacing_pct — the parts we still share with the prototype)."""
    import html
    label = (m.get('label') or '').ljust(label_w)
    pct = m.get('pct') or 0
    width = cfg['barWidth']
    if m.get('count') is not None and m.get('total') is not None:
        col2 = f'{m["count"]}/{m["total"]}'
        bar = ' ' * width                # count-only rows show no bar
    else:
        col2 = f'{pct}%'
        fill = round(max(0, min(100, pct)) * width / 100)
        bar = '█' * fill + '░' * (width - fill)
    # extension.js:formatReset (line 65) falls back to the raw `reset` field
    # verbatim when none of the recognized patterns match (e.g. "Resets Jun
    # 1"). pp.reset_text returns '' in that case — mirror the fallback so
    # unusual reset strings still appear, matching production. The capital
    # "R" of unknown-format resets vs lowercase "resets" of known-format
    # ones is also production behavior, not a bug.
    rt = pp.reset_text(m, anchor_ts) or (m.get('reset') or '')
    prefix = '✴ ' if m is primary else '  '
    pacing = pp.pacing_pct(m, period_lens)
    color = _tier_color(pacing, cfg)
    head = f'{prefix}{label}  {col2:>6}  '
    tail = f'  {rt}' if rt else ''
    text = f'{head}{bar}{tail}'
    return (
        f'<div class="popup-row" style="color: {color}">'
        f'{html.escape(text)}</div>'
    )


def production_popup(cache, cfg, *, pp, extra_sub_row_for=None):
    """Render the full popup div in production style.

    extra_sub_row_for: callable (meter) → (str, str) returning (text, color) or
    None. Called for each meter; lets the Extra-usage screenshot inject its
    `$X spent · $Y balance` sub-row directly under the corresponding meter."""
    import html
    meters = cache['meters']
    visible = [m for m in meters if not pp.is_sonnet_hidden(m)]
    label_w = max(len(m.get('label') or '') for m in visible)
    anchor_ts = cache['_timestamp']
    primary = pp.get_primary(meters, cfg)
    period_lens = cache.get('_period_lengths') or {}

    parts = [
        f'<div class="popup-header">{html.escape(pp.header_line(cache))}</div>'
    ]
    # Separator before the Extra section. Detected by spent/balance presence,
    # matching extension.js's isExtra flag.
    saw_extra_separator = False
    for m in visible:
        is_extra = m.get('spent') is not None or m.get('balance') is not None
        if is_extra and not saw_extra_separator:
            parts.append('<div class="popup-divider"></div>')
            saw_extra_separator = True
        parts.append(production_meter_row(
            m, cfg, primary=primary, period_lens=period_lens,
            anchor_ts=anchor_ts, label_w=label_w, pp=pp))
        if extra_sub_row_for is not None:
            sub = extra_sub_row_for(m)
            if sub:
                text, color = sub
                parts.append(
                    f'<div class="popup-row" style="color: {color}">'
                    f'{html.escape(text)}</div>'
                )

    parts.append('<div class="popup-divider"></div>')
    parts.append('<div class="popup-footer">Open Usage Page</div>')
    return '<div class="popup">' + ''.join(parts) + '</div>'


def wrap_popup_html(popup_html, pp):
    """Wrap a popup div in a minimal HTML page with transparent body so
    PIL.getbbox crops tight, plus an @font-face override for ✴ (Anthropic
    star). Used by every render-popup-*.py."""
    return f'''<!doctype html>
<html><head><meta charset="utf-8">
<style>
  {pp.CSS}
  body {{
    margin: 0; padding: 16px;
    background: transparent;
    display: inline-block;
  }}
  @font-face {{
    font-family: 'StarOverride';
    src: local('Noto Sans');
    unicode-range: U+2734;
  }}
  .popup {{
    font-family: 'StarOverride', 'JetBrains Mono',
                 'DejaVu Sans Mono', monospace;
  }}
</style></head><body>{popup_html}</body></html>
'''
