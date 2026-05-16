# Icon Cleanup Ordering — Write Then Delete

**Date:** 2026-05-16  
**Status:** Implemented

## Problem

`_next_icon_path()` deleted all `claude-usage-icon-*.png` files before returning the new
path. `main()` then wrote the new icon to that path. This left a brief window where no
icon file existed on disk — GNOME could flash a broken icon between the deletion and the
write.

Files were not accumulating (cleanup ran on every write), but the ordering was wrong.

## Change

**File:** `server/generate-icon.py`

Removed the deletion loop from `_next_icon_path()` — it now only generates and returns the
new timestamped path. Moved the cleanup into `main()`, after `generate()` writes the new
file, skipping the file just written:

```python
dest = _next_icon_path()
generate(all_pct, sonnet_pct, cfg, dest)
for old in CACHE_DIR.glob('claude-usage-icon-*.png'):
    if old != dest:
        try:
            old.unlink()
        except OSError:
            pass
update_desktop(meters, dest)
```

A valid icon is now always present on disk throughout the update cycle.

## Verification

```
$ python3 server/generate-icon.py && ls ~/.cache/claude-usage-icon-*.png | wc -l
Icon: All=6% Sonnet=10%
1
$ python3 server/generate-icon.py && ls ~/.cache/claude-usage-icon-*.png | wc -l
Icon: All=6% Sonnet=10%
1
```

Two runs, always exactly one file.
