# Ring Color Thresholds — Connect Dock Icon to GSettings

**Date:** 2026-05-16  
**Status:** Implemented

## Problem

`generate-icon.py::ring_color()` used hardcoded thresholds of 50 (warning) and 80
(critical) to pick the outer ring colour on the dock icon. These numbers matched the
GSettings defaults for `threshold-warning` and `threshold-critical`, so the dock icon
looked correct out of the box — but silently diverged from the popup and panel label
colours whenever a user changed those thresholds in the preferences UI.

## Change

**File:** `server/generate-icon.py`

1. Added `threshold_warning: 50` and `threshold_critical: 80` to `DEFAULTS` (the
   GSettings-unavailable fallback dict).

2. Added `threshold_warning` and `threshold_critical` to the dict returned by
   `load_config()` via `s.get_uint('threshold-warning')` / `s.get_uint('threshold-critical')`.

3. Updated `ring_color()` to use `cfg.get('threshold_critical', 80)` and
   `cfg.get('threshold_warning', 50)` instead of the magic numbers.

## Verification

```
$ python3 server/generate-icon.py
Icon: All=6% Sonnet=9%
exit 0
```

To confirm threshold responsiveness:

```bash
gsettings set org.gnome.shell.extensions.claude-usage threshold-warning 30
python3 server/generate-icon.py   # ring turns amber at 30% instead of 50%
gsettings reset org.gnome.shell.extensions.claude-usage threshold-warning
```
