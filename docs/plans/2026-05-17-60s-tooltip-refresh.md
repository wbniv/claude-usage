# Plan: 60 s tooltip-only refresh (in-process)

## Context

`server/generate-icon.py:211-225` writes the dock launcher's tooltip into
the `Name=` field of `~/.local/share/applications/claude-usage.desktop`.
That field is read by GNOME Shell when the launcher app-info is loaded
and re-read when the file changes — there is no per-hover hook for
ordinary `.desktop` entries (extending our panel indicator to override
dock-item tooltips would mean monkey-patching private GNOME Shell APIs
that change between versions — fragile, rejected).

Today the file is rewritten only when `generate-icon.py` runs, which
happens once per 15-minute POST cycle (`server/usage-server.py:125-127`).
The tooltip text includes a countdown like `current 23% ⏱4:23` whose
minute component is stale within seconds; over a 15-minute cycle it
drifts up to ~15 min from reality.

Fix: a 60 s tick in the already-running `usage-server.py` that recomputes
the tooltip and rewrites the `.desktop` Name= line in-process — no
subprocess, no fork+exec+python-startup. Per-tick cost drops from
~100 ms (subprocess) to <1 ms (function call), a ~100× reduction.

The change requires extracting the tooltip-rendering helpers
(`parse_reset`, `format_tooltip`, `update_desktop`) out of
`generate-icon.py` into a shared `server/tooltip.py` so both files
import them. `generate-icon.py` keeps using them for its 15 min full
regen; `usage-server.py` calls them directly for the 60 s tick.

## Files to modify

| File | Change |
|---|---|
| `server/tooltip.py` (new) | Houses `DESKTOP` path constant, `parse_reset`, `format_tooltip`, `update_desktop`; the latter takes optional `icon_path` (preserve existing Icon= line when None) |
| `server/generate-icon.py` | Delete the moved functions; `from tooltip import …` |
| `server/usage-server.py` | Daemon thread on startup: every 60 s, read cache JSON and call `tooltip.update_desktop(meters)` directly (no subprocess) |
| `packaging/build-deb.sh` | Ship `tooltip.py` alongside the existing server scripts |
| `install.sh` | Same — copy `tooltip.py` into the source-install destination |
| `packaging/test-deb-verify.sh` | Assert `tooltip.py` lands in `/usr/share/claude-usage/` |
| `packaging/control`, `chrome-extension/manifest.json` | Version 0.10.0 → 0.10.1 |

## Implementation

### `server/tooltip.py` (new)

Module-level constants and functions extracted verbatim from
`generate-icon.py:143-225`:

```python
"""Tooltip rendering shared between usage-server.py (60 s tick) and
generate-icon.py (15 min full POST regen)."""
import datetime, re
from pathlib import Path

DESKTOP = Path.home() / '.local/share/applications/claude-usage.desktop'

def parse_reset(reset):
    # ... (moved verbatim from generate-icon.py:143-171)

def format_tooltip(meters):
    # ... (moved verbatim from generate-icon.py:173-191)

def update_desktop(meters, icon_path=None):
    """If icon_path is None, preserve the existing Icon= line — that's
    the path the 60 s tick takes; the 15 min regen passes a fresh
    timestamped path."""
    if not DESKTOP.exists():
        return
    name = format_tooltip(meters).replace('\n', r'\n')
    lines = DESKTOP.read_text().splitlines()
    out = []
    for line in lines:
        if line.startswith('Name='):
            out.append(f'Name={name}')
        elif line.startswith('Icon='):
            out.append(line if icon_path is None else f'Icon={icon_path}')
        elif line.startswith('#'):
            out.append(line)
        elif line.startswith('[') or '=' in line or line == '':
            out.append(line)
    tmp = DESKTOP.with_suffix(DESKTOP.suffix + '.tmp')
    tmp.write_text('\n'.join(out) + '\n')
    tmp.replace(DESKTOP)
```

### `server/generate-icon.py`

Replace the moved function bodies with:

```python
from tooltip import parse_reset, format_tooltip, update_desktop, DESKTOP
```

(Top of file, after the existing `from PIL import Image` line.) Delete
the duplicate function bodies at lines 143-225. The main() call
`update_desktop(meters, dest)` still works (positional `icon_path`).

### `server/usage-server.py`

Two additions:

1. Import the shared module + `threading` at the top:

   ```python
   import threading
   import tooltip
   ```

2. Spawn the tick thread on startup. Insert after `print(f"Claude Usage server listening …")` (line ~148):

   ```python
   def _tooltip_tick():
       """Refresh the dock launcher tooltip every 60 s so the countdown
       stays current between 15-min scrape POSTs."""
       while True:
           time.sleep(60)
           try:
               if OUTPUT.exists():
                   data = json.loads(OUTPUT.read_text())
                   tooltip.update_desktop(data.get('meters', []))
           except Exception as e:
               print(f"tooltip tick: {e}", file=sys.stderr, flush=True)

   threading.Thread(target=_tooltip_tick, daemon=True).start()
   ```

   `daemon=True` ensures KeyboardInterrupt on the main thread tears the
   loop down cleanly. `time.sleep(60)` first so we don't double-fire
   right after a POST already refreshed the file. `if OUTPUT.exists()`
   handles the first-boot case before any scrape has landed.

### Packaging touchups

`packaging/build-deb.sh` line 31-33 currently:
```bash
cp "$REPO_DIR/server/usage-server.py" \
   "$REPO_DIR/server/generate-icon.py" \
   "$PKG/usr/share/claude-usage/"
```

Add `tooltip.py`:
```bash
cp "$REPO_DIR/server/usage-server.py" \
   "$REPO_DIR/server/generate-icon.py" \
   "$REPO_DIR/server/tooltip.py" \
   "$PKG/usr/share/claude-usage/"
```

`install.sh` does the equivalent copy for source installs — find the
matching block and add the file.

`packaging/test-deb-verify.sh` — add one line alongside the existing
server file assertions:
```bash
test -f /usr/share/claude-usage/tooltip.py
```

### Version bump

`packaging/control`: `Version: 0.10.0` → `0.10.1`
`chrome-extension/manifest.json`: `"version": "0.10.0"` → `"0.10.1"`

## Verification

1. **Syntax sanity**
    - `python3 -c 'import ast; ast.parse(open("server/tooltip.py").read()); ast.parse(open("server/generate-icon.py").read()); ast.parse(open("server/usage-server.py").read())'`

2. **Import resolves** (from server/ dir, where both modules sit):
    ```bash
    cd server && python3 -c 'import tooltip; print(tooltip.DESKTOP)'
    ```

3. **Refactor parity** — capture `.desktop` Name= line both before and after a single full `generate-icon.py` run; should be byte-identical to pre-refactor output for the same cache state:
    ```bash
    grep '^Name=' ~/.local/share/applications/claude-usage.desktop > /tmp/name.before
    python3 ~/.local/share/claude-usage/generate-icon.py
    grep '^Name=' ~/.local/share/applications/claude-usage.desktop > /tmp/name.after
    diff /tmp/name.before /tmp/name.after   # expect identical for steady cache
    ```

4. **Tick-only smoke** (no server restart):
    ```bash
    cd ~/.local/share/claude-usage && python3 -c '
    import json, tooltip
    from pathlib import Path
    data = json.loads(Path.home().joinpath(".cache/claude-usage/usage.json").read_text())
    tooltip.update_desktop(data.get("meters", []))
    '
    grep -E '^(Icon|Name)=' ~/.local/share/applications/claude-usage.desktop
    # Icon= preserved, Name= countdown reflects "now"
    ```

5. **Thread alive after restart**:
    ```bash
    systemctl --user restart claude-usage-fetch.service
    sleep 65
    stat -c '%Y %n' ~/.local/share/applications/claude-usage.desktop
    # mtime within last 60 s = tick fired
    ```

6. **`.deb` install regression**: `task test-deb-fast`. Catches the
   shipping of the new `tooltip.py`, the version bump, the import path
   in the installed location.

7. **Watch one minute live** — hover the dock launcher, watch the
   countdown decrement after the tick. (GNOME caches tooltip text
   within a single hover; move off and back on guarantees a re-read.)

## Follow-ups (separate plan)

- **Popup marker uses panel-icon graphic, tinted** (per user request).
  The Anthropic star PNG that the panel uses (`claude-22.png`) can't
  be tinted at runtime — needs a symbolic SVG version. Popup items
  also need to change from `PopupMenuItem` (text only) to a custom
  item with `St.Icon` + `St.Label` so a colored icon can prefix the
  active row. Non-trivial; own plan after this tooltip work ships.
