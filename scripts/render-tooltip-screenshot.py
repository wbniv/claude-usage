#!/usr/bin/env python3
"""Render docs/tooltip-screenshot.png — the dock-icon hover tooltip.

GNOME shows the .desktop launcher's Name= field when you hover the dock
icon. The Name= field is rewritten on every fetch by
server/tooltip.py:update_desktop(), and its content is built by
format_tooltip(meters, anchor_ts). This script calls format_tooltip
directly with a synthetic meters list, draws the dock icon next to a
GNOME-styled tooltip strip, and screenshots the result via headless
Chrome.
"""
import base64
import importlib.util
import io
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'server'))
sys.path.insert(0, str(REPO / 'scripts'))

from _doc_render import html_to_png


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


g = _load('generate_icon', REPO / 'server/generate-icon.py')
t = _load('tooltip',       REPO / 'server/tooltip.py')


# Synthetic meters — chosen to match the popup-screenshot.py values so the
# docs read coherently across images (the tooltip is what hovering the
# dock-icon shows; the popup is what clicking the panel label shows; both
# come from the same cache).
NOW    = int(time.time())
METERS = [
    {'label': 'Current session', 'pct': 9,
     'reset_minutes': 227, 'reset': 'Resets in 3 hr 47 min'},
    {'label': 'All models', 'pct': 4,
     'reset_minutes': 5760, 'reset': 'Resets Tue 1:00 PM'},
    {'label': 'Sonnet only', 'pct': 6,
     'reset_minutes': 5759, 'reset': 'Resets Tue 12:59 PM'},
]
ALL_PCT    = 20  # mock dock-icon outer ring; doesn't have to match METERS
SONNET_PCT = 10  # mock dock-icon inner ring


def icon_data_uri():
    """Render the dock icon to an in-memory PNG and return a data URI."""
    img = g._render(ALL_PCT, SONNET_PCT, dict(g.DEFAULTS))
    img = img.resize((128, 128), g.RESAMPLE)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def main():
    tooltip = t.format_tooltip(METERS, anchor_ts=NOW)
    icon_uri = icon_data_uri()

    # GNOME tooltip styling: dark background, light text, small border-radius
    # + faint drop shadow. Approximates the system tooltip without trying to
    # match a specific shell theme exactly — themes vary across distros, but
    # the dark-pill-with-light-text idiom is universal.
    html = f'''<!doctype html>
<html><head><meta charset="utf-8">
<style>
  body {{
    margin: 0; padding: 16px;
    background: transparent;
    font-family: -apple-system, 'Segoe UI', sans-serif;
    display: inline-block;
  }}
  .row {{
    display: flex; align-items: center; gap: 14px;
  }}
  .icon {{
    width: 64px; height: 64px;
    border-radius: 12px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.18);
  }}
  .tooltip {{
    background: #2d2d2d;
    color: #f0f0f0;
    padding: 8px 14px;
    border-radius: 7px;
    font-size: 13px;
    font-weight: 400;
    letter-spacing: 0.1px;
    box-shadow: 0 3px 10px rgba(0,0,0,0.25);
    /* `pre` preserves the triple-space padding around `   |   ` and
       `   ✴   ` from format_tooltip — HTML's default whitespace collapse
       would erase it and crowd the separators against the text. */
    white-space: pre;
  }}
</style></head><body>
  <div class="row">
    <img class="icon" src="{icon_uri}">
    <div class="tooltip">{tooltip}</div>
  </div>
</body></html>
'''
    out = REPO / 'docs/tooltip-screenshot.png'
    html_to_png(html, out, viewport=(1200, 200))
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
