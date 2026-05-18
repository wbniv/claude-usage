# 2026-05-18 — Remove orphan Chrome extension registration from Preferences

## Context

The maintainer's Chrome profile holds an orphan extension registration at `~/.local/share/claude-usage/chrome-extension`, a path that no longer exists on disk (deleted when they switched from source-install to .deb-install some weeks ago). Chrome silently keeps the registration as a load-error entry. Pass-13 finding O‑1 added `claude-usage-status` detection for this case; the warning now fires:

```
Chrome ext: ⚠ orphan registration at /home/will/.local/share/claude-usage/chrome-extension
            Fix: chrome://extensions → remove "aofoofgc…"
```

The user tried to remove it via the UI but Chrome hid the error-state entry from `chrome://extensions`, so they accidentally removed the active `.deb`-installed extension (`idjiiff…`) instead. The orphan (`aofoofgc…`) is still in `Preferences`.

This change removes it directly via JSON edit, because the UI path isn't reliably exposing the orphan.

## Why this isn't a code change

Chrome doesn't expose a CLI or scripting API for unregistering an extension that wasn't installed through it (load-unpacked uses `location=4`). The only paths are:

1. The chrome://extensions UI (failed above — Chrome hides load-errored entries)
2. Direct edit of `~/.config/google-chrome/Default/Preferences`
3. Live in `chrome.management` API from another extension (out of scope)

(2) is what we're doing.

## Risk: integrity protection

Chrome stores per-extension HMACs at `protection.macs.extensions.settings.<extension_id>` to detect external tampering with the extensions dict. If we delete the orphan's settings entry without also removing its MAC, Chrome will detect the mismatch on next launch and may:

- Reset the entire `extensions.settings` dict to known-good (worst case — all 32 extensions wiped)
- Restore the orphan from MAC-derived state
- Just log a warning

Mitigation: remove BOTH the settings entry AND the matching MAC entry in the same write, so the dict and its integrity record stay consistent.

## Files modified

### `~/.config/google-chrome/Default/Preferences` (runtime data, not source)

Two keys deleted:
- `extensions.settings.aofoofgceohpheneebpjhcmklpamniep`
- `protection.macs.extensions.settings.aofoofgceohpheneebpjhcmklpamniep`

The python script:

```python
import json, shutil, time
from pathlib import Path

PREFS = Path.home() / '.config/google-chrome/Default/Preferences'
ORPHAN_ID = 'aofoofgceohpheneebpjhcmklpamniep'

# Backup first — JSON edits to Chrome's Preferences are unforgiving.
backup = PREFS.with_suffix(f'.bak.{int(time.time())}')
shutil.copy2(PREFS, backup)
print(f'backup: {backup}')

p = json.loads(PREFS.read_text())
removed_settings = p.get('extensions', {}).get('settings', {}).pop(ORPHAN_ID, None)
removed_mac = p.get('protection', {}).get('macs', {}).get('extensions', {}).get('settings', {}).pop(ORPHAN_ID, None)

print(f'extensions.settings.{ORPHAN_ID[:8]}…: {"removed" if removed_settings else "not present"}')
print(f'protection.macs....{ORPHAN_ID[:8]}…:  {"removed" if removed_mac else "not present"}')

PREFS.write_text(json.dumps(p, indent=2, sort_keys=False))
print('written')
```

## Procedure

1. **Confirm Chrome is fully quit** — `pgrep -c chrome` must return `0` (not just "no main process"; all helper processes must be gone). If non-zero, abort and ask the user to close all Chrome windows + verify with `pgrep`.
2. Run the script above. Verify both keys reported as `removed`.
3. **Verify on-disk state:** `claude-usage-status` should NOT show the orphan warning.
4. **User restarts Chrome.** Session restore should recover their tabs.
5. **User installs the 0.11.6 .deb:** `sudo dpkg -i /home/will/SRC/claude-usage/dist/claude-usage_0.11.6_all.deb` (already built; not run because dpkg needs sudo and that's the user's call).
6. **User loads unpacked:** `chrome://extensions` → Load unpacked → `/usr/share/claude-usage/chrome-extension`. This creates a fresh extension registration (new ID, properly MAC-stamped by Chrome).
7. `claude-usage-status` should now show neither the orphan warning nor the "predates 0.11.1" warning.

## Recovery if integrity check trips

If after restart Chrome warns about reset settings or `chrome://extensions` shows fewer extensions than before:

```bash
# Restore the backup written by the script (Chrome must be quit)
cp ~/.config/google-chrome/Default/Preferences.bak.<timestamp> \
   ~/.config/google-chrome/Default/Preferences
```

## Out of scope

- Any change to the source code or .deb contents — the bug is in runtime Chrome state, not the project.
- Installing the .deb (`sudo dpkg -i`) — user's call; Claude doesn't have sudo.
- Automating the entire flow end-to-end — quitting Chrome and restarting it are user-driven by design (session restore + UX preservation).

## Verification commands

Before the edit (sanity-check the orphan IS the only Claude registration):

```bash
python3 -c "
import json; from pathlib import Path
p = json.load(open('/home/will/.config/google-chrome/Default/Preferences'))
for eid, e in p.get('extensions', {}).get('settings', {}).items():
    path = e.get('path', '') or ''
    if 'claude' in path.lower():
        print(eid[:8], path, 'exists=' + str(Path(path).exists()))
"
```

After the edit + Chrome restart:

```bash
claude-usage-status
# Expect: no "orphan registration" line
```

After the user installs .deb + load-unpacks:

```bash
claude-usage-status
# Expect: no orphan, no "predates 0.11.1" — both cleared.
```
