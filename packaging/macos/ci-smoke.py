#!/usr/bin/env python3
"""macOS CI smoke test for the menu-bar port (run by codemagic.yaml).

Imports the real modules with the system PyObjC (no stubs) and exercises the
pure display logic that mirrors desktop/gnome/extension.js. This validates,
on a real Mac, that:
  - PyObjC (AppKit/Foundation) bindings resolve and the NSObject controller
    subclass + module-level imports load without a window server;
  - usage_core imports and schema_defaults locates the gschema XML;
  - the hand-ported helpers produce the expected values.

It does NOT launch the GUI (NSStatusItem needs an interactive Aqua session);
that stays a manual on-device check. Exits non-zero on any mismatch so the
Codemagic build fails loudly.
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / 'server'))
sys.path.insert(0, str(REPO / 'desktop' / 'macos'))

import usage_core  # noqa: E402  — real import; fails loudly if schema XML missing
import claude_usage_menubar as A  # noqa: E402  — real PyObjC import
import prefs  # noqa: E402  — real PyObjC import of the preferences window module

ok = True


def check(desc, got, exp):
    global ok
    flag = 'OK ' if got == exp else 'FAIL'
    if got != exp:
        ok = False
    print(f'  [{flag}] {desc}: {got!r}' + ('' if got == exp else f' (expected {exp!r})'))


now = time.time()

# Shared pacing core loaded and computes (single source of truth).
check('usage_core.load_ui_config returns dict', isinstance(usage_core.load_ui_config(), dict), True)
check('pacing_pct on-pace=200', usage_core.pacing_pct({'label': 'x', 'pct': 50, 'reset_minutes': 50}, {'x': 100}), 100.0)

# Ported display helpers (mirror extension.js).
check('fmt_countdown(90)', A.fmt_countdown(90), '⏱1:30')
check('fmt_countdown(1500)', A.fmt_countdown(1500), '⏱1d 1h')
check('live_remaining rm=100 @10min', A.live_remaining({'reset_minutes': 100}, now - 600), 90)
check('live_remaining bool→None', A.live_remaining({'reset_minutes': True}, now), None)
check('is_selectable Sonnet 0%→False', A.is_selectable({'label': 'Sonnet', 'pct': 0}), False)
check('is_selectable All 5%→True', A.is_selectable({'label': 'All models', 'pct': 5}), True)

meters = [{'label': 'Sonnet', 'pct': 0}, {'label': 'All models', 'pct': 5}]
check("get_primary ''→All models", (A.get_primary(meters, '') or {}).get('label'), 'All models')
check('reset_hint session 0%', A.reset_hint({'label': 'Current session', 'pct': 0}, now), '  (not started)')

# prefs window module loaded under real PyObjC (NSColorWell/NSStepper/NSWindow resolved).
check('prefs.PrefsController present', hasattr(prefs, 'PrefsController'), True)
check('prefs.FIELDS non-empty', len(prefs.FIELDS) > 0, True)

print('\nci-smoke: ALL PASS' if ok else '\nci-smoke: FAILURES')
sys.exit(0 if ok else 1)
