#!/usr/bin/env python3
"""Render docs/panel-screenshot.png — the GNOME top-panel indicator.

extension.js (line 151) loads its panel St.Icon from the static
desktop/gnome/icons/claude-22.png — the bare Anthropic star, NOT the
ring-painted dock icon. The accompanying St.Label shows `{pct}%`,
colour-flipped via the panel-color-* triplet based on pacing tier.
On the broken tier the icon swaps to claude-22-red.png; this script
renders the normal-tier path.

74% is chosen as a representative warning-tier value (≥ schema-default
70 = warn, < 90 = crit) so the rendered strip exercises the colour
flip the surrounding MANUAL paragraph discusses.
"""
import base64
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'scripts'))
# RP-2 (pass-19): explicit path for schema_defaults. Previously the import
# only worked because `_doc_render` happens to perform `sys.path.insert` for
# the server/ dir as an import side effect. Don't rely on that.
sys.path.insert(0, str(REPO / 'server'))

from _doc_render import html_to_png
from PIL import Image
from schema_defaults import DEFAULTS as _SCHEMA


# Source-of-truth panel icon: the bare star bundled with the GNOME extension.
# extension.js loads this same file via Gio.icon_new_for_string at line 151.
PANEL_ICON  = REPO / 'desktop' / 'gnome' / 'icons' / 'claude-22.png'
# PCT_VALUE is chosen to land between the schema's warn/crit thresholds so
# the rendered strip exercises the colour-flip the surrounding MANUAL prose
# discusses. Reading the threshold from the schema means a future schema
# tweak still produces a warning-tier render.
# RP-1 (pass-18): cap at 99 so the rendered strip never reads "100%+" if
# threshold_warning ever climbs above 96 in a future schema edit.
PCT_VALUE = min(99, _SCHEMA['threshold_warning'] + 4)
PANEL_WARN_COLOR = _SCHEMA['panel_color_warning']


def icon_data_uri():
    """Embed claude-22.png upscaled to 64 px so it stays crisp at the larger
    HTML font-size; downscales cleanly when MANUAL.md displays at width=160."""
    img = Image.open(PANEL_ICON).convert('RGBA')
    img = img.resize((64, 64), Image.LANCZOS)
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
