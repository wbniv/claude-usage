# macOS Preferences Window

## Context

The macOS menu-bar app ([2026-06-18-macos-port.md](2026-06-18-macos-port.md)) reads its colours, thresholds, bar width, and popup font from `~/.config/claude-usage/config.json` via `usage_core.load_ui_config`, and picks up changes within its 2 s poll (each `_refresh` re-reads the config and the menu fingerprint includes it). v1 had no UI — you edited `config.json` by hand.

This adds a native **PyObjC preferences window** (`NSColorWell` + `NSStepper`) that round-trips the **same** `config.json`, matching the GNOME `prefs.js` (Gtk) and KDE `ConfigGeneral.qml` dialogs. No new config surface, no new schema key — it edits the neutral config the KDE port established, and the app's existing poll applies it (≤ 2 s, the macOS analog of GNOME's "settings apply instantly").

## Scope

**In scope** — the menu-bar-relevant keys the macOS app actually honours:

| Control | Keys | Widget |
|---|---|---|
| Pacing thresholds | `threshold_warning`, `threshold_critical` (1–500) | `NSStepper` + value field |
| Popup bar width | `bar_width` (1–20) | `NSStepper` |
| Popup font size | `popup_font_size` (8–20) | `NSStepper` |
| Menu-bar `%` label colour | `panel_color_normal/warning/critical` | `NSColorWell` |
| Popup bar/text colour | `popup_color_normal/warning/critical` | `NSColorWell` |

A **Preferences…** item (⌘,) in the status menu opens the window. Each control change writes `config.json` live; the app's 2 s poll re-renders.

**Out of scope (deferred, documented here):**
- **Dock-ring colours** (`weekly_color_*`, `sonnet_color`) — the menu bar renders no rings on macOS (menu-bar-only v1), so these are inert here. Revisit if/when a Dock-tile mode lands.
- **Font-family picker** — GNOME/KDE use a font dialog; defer the macOS `NSFontPanel` wiring. `popup_font_family` stays hand-editable in `config.json`.
- **`panel_font_size` / `panel_label_spacing` / `panel_icon_size`** — GNOME-panel concepts the macOS menu bar doesn't use (the status item uses the system menu-bar font/size), so omit.

## Implementation

1. **`server/usage_core.py` — `write_ui_config(updates)`.** Atomic merge-write to `config.json` (tmp + rename, 0600), validating each entry through a new shared `_coerce(key, val)` (hex colours via `hex_to_rgba`, ranged ints via `_SCHEMA_RANGES`, known keys only). Preserves other keys already in the file. Refactor `load_ui_config` to use the **same** `_coerce` — one validation path for reads and writes. Pure Python → unit-tested on Linux.

2. **`desktop/macos/prefs.py` — `PrefsController(NSObject)`.** Builds an `NSWindow` programmatically (no nib): one row per field — an `NSTextField` label plus an `NSColorWell` (colours) or `NSStepper` + value `NSTextField` (ints, min/max from the gschema range). Each control carries its field index as `.tag`; the action selectors `colorChanged_` / `stepperChanged_` read the tag, convert (`NSColor` ↔ `#RRGGBB`), and call `usage_core.write_ui_config`. Hex↔NSColor helpers are **module-level functions** and the only methods are the designated `init`, `show`, and the two `*_` action selectors — so no arg-taking helper becomes a selector (avoids the `@objc.python_method` / `BadPrototypeError` trap the port hit).

3. **Wire into `claude_usage_menubar.py`.** `import prefs`; add a **Preferences…** item (key-equivalent `,`) to `_addFooter` whose action `openPrefs_` lazily creates and `show()`s a retained `PrefsController` (`self._prefs`, initialised to `None` in `init`). No config-change signal needed — the existing 2 s poll re-reads `config.json`.

4. **`packaging/macos/build-app.sh`.** Stage `prefs.py` into the build tree and add `'prefs'` to the py2app `includes`.

5. **`packaging/macos/ci-smoke.py`.** Assert `prefs` imports under real PyObjC (transitively covered by importing the app, made explicit).

## Critical files

| File | Action |
|------|--------|
| `server/usage_core.py` | `write_ui_config()` + shared `_coerce()`; `load_ui_config` refactored onto `_coerce` |
| `server/tests/test_usage_core.py` | **Create** — write/load round-trip, preserve-other-keys, drop-invalid, 0600 |
| `desktop/macos/prefs.py` | **Create** — `PrefsController` (NSColorWell + NSStepper, writes config.json) |
| `desktop/macos/claude_usage_menubar.py` | Preferences… menu item + `openPrefs_` + retained `self._prefs` |
| `packaging/macos/build-app.sh` | Bundle `prefs.py`; add to py2app includes |
| `packaging/macos/ci-smoke.py` | Explicit `import prefs` check |
| `MANUAL.md` | macOS Configuration — mention the Preferences… window |

## Verification

1. **`task test`** — new `test_usage_core.py` passes (write→load round-trip; second write preserves the first key; out-of-range/bad-hex/unknown keys dropped; file is 0600); whole suite stays green.
2. **`py_compile`** `prefs.py` + `claude_usage_menubar.py`.
3. **Stubbed-PyObjC `ci-smoke`** on Linux imports `prefs` cleanly (via the app import).
4. **Codemagic `macos-test` green** — confirms `prefs.py` imports under real PyObjC (the build's `ci-smoke` step).
5. **`[verify][live]` (interactive Mac):** open **Preferences…** from the menu; change the critical colour and the warning threshold; confirm `config.json` updates and the menu-bar `%` / popup recolour within ~2 s; reopen Preferences and confirm persisted values load back into the wells/steppers.
