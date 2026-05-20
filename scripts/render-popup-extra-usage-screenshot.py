#!/usr/bin/env python3
"""Render docs/popup-extra-usage-screenshot.png — the Max-plan popup with
the Extra usage section active.

Mirrors the popup the user sees once they enable Extra usage on
claude.ai/settings/usage: the standard meters at the top, then a divider,
then the Extra usage row (with usage bar + reset) followed by a sub-row
showing `$X spent · $Y balance`. Renders in production style (matches the
currently-shipped extension.js: single-tone bars, whole row colored by
pacing tier).
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


CACHE = {
    '_timestamp': int(time.time()),
    'plan': 'Max',
    'meters': [
        {'label': 'Current session', 'pct': 12,
         'reset_minutes': 157, 'reset': 'Resets in 2 hr 37 min'},
        {'label': 'All models', 'pct': 4,
         'reset_minutes': 5760, 'reset': 'Resets Tue 1:00 PM'},
        {'label': 'Sonnet only', 'pct': 6,
         'reset_minutes': 5760, 'reset': 'Resets Tue 1:00 PM'},
        {'label': 'Claude Design', 'pct': 8,
         'reset_minutes': 5760, 'reset': 'Resets Tue 1:00 PM'},
        {'label': 'Daily included routine runs', 'pct': 0,
         'count': 0, 'total': 15, 'reset': ''},
        # Extra usage: spent/balance trigger the divider + sub-row injection.
        # pct=100 with a long reset puts the row in crit tier (over-pace),
        # matching the existing screenshot's red bar.
        {'label': 'Extra usage', 'pct': 100,
         'reset_minutes': 17280, 'reset': 'Resets Jun 1',
         'spent': '$4.11', 'balance': '$0.90'},
    ],
    '_period_lengths': {
        'Current session': 300,
        'All models':       10080,
        'Sonnet only':      10080,
        'Claude Design':    10080,
        'Daily included routine runs': 1440,
        'Extra usage':      21600,    # ~15 d
    },
}

CFG = {
    'tWarn': 70, 'tCrit': 90,
    'popupNorm': '#2a9a2a', 'popupWarn': '#d07000', 'popupCrit': '#e03030',
    'panelNorm': '#ffffff', 'panelWarn': '#d07000', 'panelCrit': '#e03030',
    'barWidth': 10, 'panelMetric': 'All models',
}


def extra_sub_row(m):
    """Inject the `$X spent · $Y balance` sub-row directly under the
    Extra usage meter. Indented to align under the meter label."""
    if m.get('spent') is None and m.get('balance') is None:
        return None
    parts = []
    if m.get('spent'):   parts.append(f'{m["spent"]} spent')
    if m.get('balance'): parts.append(f'{m["balance"]} balance')
    label_w = max(len(x.get('label') or '') for x in CACHE['meters'])
    text = ' ' * (2 + label_w) + '  ' + ' · '.join(parts)
    return text, '#666'


def main():
    popup = production_popup(CACHE, CFG, pp=pp, extra_sub_row_for=extra_sub_row)
    html_doc = wrap_popup_html(popup, pp)
    out = REPO / 'docs/popup-extra-usage-screenshot.png'
    html_to_png(html_doc, out)
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
