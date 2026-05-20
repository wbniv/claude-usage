#!/usr/bin/env python3
"""Render docs/panel-screenshot.png — the GNOME top-panel indicator.

extension.js builds the panel widget from an St.Icon (`claude-usage`,
sized via the panel-icon-size gsetting — default 16) and an St.Label
(`{pct}%`, sized via panel-font-size — default 11, coloured by the
panel-color-* triplet according to the pacing tier).

This script reproduces that compose: generates the dock icon via
generate-icon.py:_render at the pct value, embeds it in an HTML strip
with a label coloured by tier, and screenshots via headless Chrome.

74% is chosen as a representative warning-tier value (≥ 70 = warn,
< 90 = not crit), so the rendering exercises the colour-flip the
section text discusses.
"""
import base64
import importlib.util
import io
import sys
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


# Match schema defaults for thresholds + colours (generate-icon.py's DEFAULTS
# drift from gschema.xml — schema is the user-facing source of truth).
PCT_VALUE = 74
CFG = dict(g.DEFAULTS, threshold_warning=70, threshold_critical=90)

PANEL_WARN_COLOR = '#d07000'   # schema panel-color-warning default


def icon_data_uri():
    img = g._render(PCT_VALUE, 10, CFG)
    img = img.resize((128, 128), g.RESAMPLE)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def main():
    icon_uri = icon_data_uri()
    # Pixel sizes are 2× the gschema defaults (icon: 16→32, label: 11→22,
    # spacing: 6→12) so the rendered image stays legible at the embedded
    # width=160 we use in MANUAL.md. Ratios match the live widget.
    # Body transparent so PIL.getbbox crops tight around the dark strip.
    # The strip itself carries the GNOME-top-bar background colour.
    html = f'''<!doctype html>
<html><head><meta charset="utf-8">
<style>
  body {{
    margin: 0; padding: 12px;
    background: transparent;
    display: inline-block;
  }}
  .panel {{
    display: inline-flex;
    align-items: center;
    gap: 12px;
    padding: 12px 18px;
    background: #1f1f1f;
    border-radius: 8px;
    font-family: -apple-system, 'Segoe UI', sans-serif;
  }}
  .icon  {{ width: 32px; height: 32px; }}
  .label {{ color: {PANEL_WARN_COLOR}; font-size: 22px; font-weight: 400; }}
</style></head><body>
  <div class="panel">
    <img class="icon" src="{icon_uri}">
    <span class="label">{PCT_VALUE}%</span>
  </div>
</body></html>
'''
    out = REPO / 'docs/panel-screenshot.png'
    html_to_png(html, out, viewport=(400, 200))
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
