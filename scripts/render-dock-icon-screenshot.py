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


# Representative healthy-mid-week state: outer ring visible-but-not-alarming,
# Sonnet inner ring at a fraction of that. Uses DEFAULTS so the mockup
# reflects the shipped color/threshold defaults regardless of what the user
# may have customized via GSettings.
ALL_PCT    = 20
SONNET_PCT = 10
CFG        = dict(g.DEFAULTS)


def main():
    img = g._render(ALL_PCT, SONNET_PCT, CFG)
    # 128 px matches one of the hicolor sizes generate-icon.py emits at
    # runtime (~/.local/share/icons/hicolor/128x128/apps/claude-usage.png).
    # Big enough to read the rings, small enough to embed in MANUAL.md at
    # the existing width="96" without obvious upscaling artefacts.
    out = REPO / 'docs/dock-icon-2rings-mockup.png'
    img.resize((128, 128), g.RESAMPLE).save(out)
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
