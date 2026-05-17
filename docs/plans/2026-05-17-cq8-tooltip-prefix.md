# CQ8 — Prefix tooltip with "Claude Usage  ✴  " for Activities search

**Date:** 2026-05-17  
**Status:** Complete  
**Triggered by:** CQ8 from pass-5/7 review; revisited after won't-fix reversal

## Context

`server/tooltip.py:update_desktop()` overwrites `Name=` in the GNOME `.desktop` file with live usage data (e.g. `current 72% ⏱1:23`). The `Name=` value also populates GNOME Activities search, so the app appeared as `current 72% ⏱1:23` instead of `Claude Usage`.

Previous verdict was "won't fix — live tooltip preferred" after ruling out the only-known fix: writing a static `Name=Claude Usage` and moving live data to `Comment=`. That approach was rejected because `Comment=` is not rendered in the dock hover tooltip (confirmed by screenshot). The obvious alternative — just prepend the app name as a prefix — was overlooked. Used `✴` (U+2734) as separator, matching the starburst already used in the GNOME extension popup (`extension.js:381`).

## Change

| File | Change |
|------|--------|
| `server/tooltip.py:89` | `format_tooltip` return prefixed with `'Claude Usage  ✴  '` when meters are present |
| `docs/wont-fix.md` | CQ8 entry removed |

```python
# Before
return '   |   '.join(parts) if parts else 'Claude Usage'

# After
return ('Claude Usage  ✴  ' + '   |   '.join(parts)) if parts else 'Claude Usage'
```

Tooltip now reads: `Claude Usage  ✴  current 72% ⏱1:23   |   all 45% Mon 09:00`

## Outcome

- Dock hover tooltip: prefixed with `Claude Usage  ✴  `
- GNOME Activities search: matches on both `claude` and `Claude Usage`
- Zero behaviour change when no meters are loaded (fallback remains `'Claude Usage'`)
- ✴ consistent with `extension.js:381` popup starburst
