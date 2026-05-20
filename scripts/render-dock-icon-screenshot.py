#!/usr/bin/env python3
"""Render docs/dock-icon-2rings-mockup.png — the live dock icon at a
representative usage level (outer ring ≈ 20 %, inner Sonnet ring ≈ 10 %).

Reuses server/generate-icon.py's _render() so the mockup is pixel-identical
to what GNOME would show in the dock for those values: same Cairo rendering,
same color ring thresholds, same baseline tile.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'server'))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


g = _load('generate_icon', REPO / 'server/generate-icon.py')


# Representative state showing the pacing-viz: outer ring is over-paced
# (50% raw used at 30% elapsed → pacing 167% → crit tier, green-then-red
# two-tone arc); inner Sonnet ring is under-paced (8% raw at 50% elapsed
# → pacing 16%, tick visible at the 50% angle). One image demonstrating
# both visual states the pacing-viz design introduced.
ALL_PCT          = 50
SONNET_PCT       = 8
ALL_ELAPSED      = 0.30     # 30 % into the period
SONNET_ELAPSED   = 0.50     # mid-period
ALL_PACING       = ALL_PCT / ALL_ELAPSED           # 167
SONNET_PACING    = SONNET_PCT / SONNET_ELAPSED     # 16
CFG              = dict(g.DEFAULTS)


def main():
    img = g._render(ALL_PCT, SONNET_PCT, CFG,
                    all_pacing=ALL_PACING, sonnet_pacing=SONNET_PACING,
                    all_elapsed=ALL_ELAPSED, sonnet_elapsed=SONNET_ELAPSED)
    # 128 px matches one of the hicolor sizes generate-icon.py emits at
    # runtime (~/.local/share/icons/hicolor/128x128/apps/claude-usage.png).
    # Big enough to read the rings, small enough to embed in MANUAL.md at
    # the existing width="96" without obvious upscaling artefacts.
    out = REPO / 'docs/dock-icon-2rings-mockup.png'
    img.resize((128, 128), g.RESAMPLE).save(out)
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
