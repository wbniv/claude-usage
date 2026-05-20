#!/usr/bin/env python3
"""Render docs/popup-screenshot.png — the basic Max-plan popup.

Mirrors what users see when they click the panel label: header (plan +
freshness), the visible meters with usage bars + reset hints, and the
"Open Usage Page" footer below a divider. Renders in production style
(matches the currently-shipped extension.js: single-tone bars, whole row
colored by pacing tier).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _doc_render import (
    html_to_png, load_popup_preview, production_popup, wrap_popup_html,
)

REPO = Path(__file__).resolve().parent.parent
pp = load_popup_preview()


# Synthetic snapshot — mid-week Max plan, healthy pacing, panel-marker on
# All models. Timestamp = time.time() so freshness reads "<1m ago". reset_minutes
# + period_lengths together determine the row tier color via pacing_pct.
CACHE = {
    '_timestamp': int(time.time()),
    'plan': 'Max',
    'meters': [
        {'label': 'Current session', 'pct': 9,
         'reset_minutes': 227, 'reset': 'Resets in 3 hr 47 min'},
        {'label': 'All models', 'pct': 4,
         'reset_minutes': 5760, 'reset': 'Resets Tue 1:00 PM'},
        {'label': 'Sonnet only', 'pct': 6,
         'reset_minutes': 5759, 'reset': 'Resets Tue 12:59 PM'},
        {'label': 'Claude Design', 'pct': 0,
         'reset_minutes': 5760, 'reset': 'Resets Tue 1:00 PM'},
        {'label': 'Daily included routine runs', 'pct': 0,
         'count': 0, 'total': 15, 'reset': ''},
    ],
    '_period_lengths': {
        'Current session': 300,      # 5 h
        'All models':       10080,   # 7 d
        'Sonnet only':      10080,
        'Claude Design':    10080,
        'Daily included routine runs': 1440,  # 1 d
    },
}

CFG = {
    'tWarn': 70, 'tCrit': 90,
    'popupNorm': '#2a9a2a', 'popupWarn': '#d07000', 'popupCrit': '#e03030',
    'panelNorm': '#ffffff', 'panelWarn': '#d07000', 'panelCrit': '#e03030',
    'barWidth': 10, 'panelMetric': 'All models',
}


def main():
    popup = production_popup(CACHE, CFG, pp=pp)
    html_doc = wrap_popup_html(popup, pp)
    out = REPO / 'docs/popup-screenshot.png'
    html_to_png(html_doc, out)
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
