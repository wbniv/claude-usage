| Date | Change |
|------|--------|
| [2026-06-19](https://github.com/wbniv/claude-usage/commit/c8e5d89) | feat(macos): preferences window (NSColorWell + NSStepper) round-tripping config.json |

<!--history-meta v1
c8e5d89	author	Will Norris
c8e5d89	added	58
c8e5d89	deleted	0
c8e5d89	files	1
c8e5d89	body	Native PyObjC prefs window (desktop/macos/prefs.py) — the GNOME prefs.js / KDE\nConfigGeneral.qml analog. Colour wells for the menu-bar % + popup colours and\nsteppers for warning/critical thresholds, popup bar width, and popup font size,\nall writing the SAME ~/.config/claude-usage/config.json the app polls (≤2s live\napply). Opened via a "Preferences…" (⌘,) item in the status menu; the controller\nis lazily created + retained.\n\n- usage_core: new write_ui_config() (atomic merge, 0600) + a shared _coerce()\n  validation path; load_ui_config refactored onto _coerce (one rule set for\n  reads and writes). New test_usage_core.py (7 tests): round-trip, preserve\n  other keys, drop invalid/unknown/out-of-range, 0600, str→int coercion. Suite\n  115→122.\n- prefs.py keeps only init/show + the two *_ action selectors as Obj-C methods\n  (hex↔NSColor are module functions) to avoid the BadPrototypeError trap.\n- build-app.sh bundles prefs.py (+ py2app include); ci-smoke imports it under\n  real PyObjC. Dock-ring colours + font-family picker deferred.\n\nPlan: docs/plans/2026-06-19-macos-prefs-window.md\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01SBMM6hGDjj6erCuffmAeqJ
-->
