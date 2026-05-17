# Pass-5 Code Quality Cleanup

**Date:** 2026-05-17
**Status:** Planned

## Context

Pass-5 review (`docs/investigations/2026-05-16-code-review-pass5.md`) found 7 bugs and 9 code-quality items. All 7 bugs (P5-1 through P5-7) were closed by intervening commits — verified with greps against current source. This plan closes 7 of the 9 remaining code-quality items in one small batch.

**Skipped (with reasons):**

- **CQ5** — `claude-usage-status.sh` invokes Python 3× on the same cache file. Cosmetic (~100 ms on a `-h`-able diagnostic); fixing it requires a larger restructure of the heredoc/shell glue. Not worth the churn unless the script is hot.
- **CQ8** — `update_desktop` overwrites `Name=` with the live tooltip, which the GNOME Activities search indexes. Fix requires moving live text to `GenericName=` or `Comment=`, but the GNOME-shell dock tooltip-on-hover behavior for those fields needs an actual session test to confirm. Defer until next time the user does a logout.

**Also deferred (architecture, doc-only):**

- No CI on `release` — known, parked.
- `metadata.json` `version: 1` — only blocks extensions.gnome.org submission, not in scope.
- Source + `.deb` install precedence conflict — needs a one-sentence note in MANUAL.md but won't bundle here.

## Changes

### CQ1 — Subprocess zombie reaping

**File:** `server/usage-server.py`

Add at module load (after imports):

```python
import signal
# Auto-reap exited child processes (generate-icon.py spawns). The Popen
# objects are discarded after dispatch so without this the kernel keeps
# zombies around until the next subprocess._cleanup() opportunistic sweep.
signal.signal(signal.SIGCHLD, signal.SIG_IGN)
```

### CQ2 — `release` task refuses to ship with uncommitted changes

**File:** `Taskfile.yml` (in the `release` task's pre-check block)

Add before the existing main-branch / tag-exists guards:

```bash
if ! git diff --quiet HEAD; then
  echo "Refusing to release with uncommitted changes:" >&2
  git status --short
  exit 1
fi
```

### CQ3 — `_loadData` logs JSON read failures

**File:** `gnome-extension/extension.js`

Replace `} catch (_e) {}` in `_loadData` with:

```javascript
} catch (e) {
    logError(e, 'ClaudeUsage: failed to read cache');
}
```

Matches the existing `_watchFile` style (line 210). Surfaces via `journalctl --user-unit=gnome-shell -f` without user-facing noise.

### CQ4 — Pillow `Image.LANCZOS` migration

**File:** `server/generate-icon.py`

Replace the bare `Image.LANCZOS` with a forward-compatible lookup near the other constants:

```python
RESAMPLE = getattr(Image, 'Resampling', Image).LANCZOS
```

Then use `RESAMPLE` in the `img.resize(...)` call. Works on Pillow 9.1+ (new path) and older (falls back via the deprecated alias on the bare `Image` object).

### CQ6 — Move `import time` to module top in `generate-icon.py`

**File:** `server/generate-icon.py`

Move `import time` from inside `_next_icon_path()` up to the top-level imports next to `cairo, math, json, sys`. Cosmetic consistency with the rest of the file.

### CQ7 — Drop unreachable defaults in `ring_color`

**File:** `server/generate-icon.py`

```python
def ring_color(pct, cfg):
    if pct >= cfg['threshold_critical']: return hex_to_rgba(cfg['weekly_color_red'])
    if pct >= cfg['threshold_warning']:  return hex_to_rgba(cfg['weekly_color_amber'])
    return                                      hex_to_rgba(cfg['weekly_color_green'])
```

`load_config()`'s contract guarantees these keys exist (success path reads them; except path uses `DEFAULTS` which also has them). The `.get(..., default)` is dead defense — trust the contract.

### CQ9 — Live `panel-icon-size` (don't require extension reload)

**Files:** `gnome-extension/extension.js`, `gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml`

In `_updateDisplay`, add to the existing per-render block:

```javascript
this._icon.set_icon_size(s.get_uint('panel-icon-size'));
```

The existing settings `changed` connect already calls `_updateDisplay`, so a slider change in prefs flows through. Then update the schema's `<summary>` / prefs subtitle for `panel-icon-size` — drop "requires extension reload".

## Version bump

`0.10.4 → 0.10.5`. Patch bump — these are quality/correctness micro-improvements, no behavior change for the happy path.

- `packaging/control`
- `chrome-extension/manifest.json`

## Critical files

- `server/usage-server.py` — CQ1
- `server/generate-icon.py` — CQ4, CQ6, CQ7
- `gnome-extension/extension.js` — CQ3, CQ9
- `gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml` — CQ9 (schema description)
- `Taskfile.yml` — CQ2
- `packaging/control`, `chrome-extension/manifest.json` — version bump

## Verification

1. **Lint all touched files:**
    ```bash
    python3 -c "import ast; ast.parse(open('server/usage-server.py').read())"
    python3 -c "import ast; ast.parse(open('server/generate-icon.py').read())"
    node --check gnome-extension/extension.js
    ```
    Expect exit 0 each.

2. **CQ1 — zombie reaping:** Start scratch server, fire a POST that triggers `generate-icon.py`, check `ps -ef --forest | grep generate-icon` after a couple seconds — should show no zombie (`<defunct>`).

3. **CQ2 — release task dirty-tree guard:** With staged-but-uncommitted change, `task release 2>&1 | head -5` — expect "Refusing to release with uncommitted changes" and exit 1, no git tag created.

4. **CQ4 — Pillow LANCZOS:** Render with the existing mockup script:
    ```bash
    python3 docs/plans/screenshots/2026-05-17-tiers/render-mockups.py 2>&1 | grep -iE 'warning|deprecat' && echo "STILL WARNING" || echo "no warnings"
    ```

5. **CQ6 / CQ7 — `generate-icon.py` still runs end-to-end:**
    ```bash
    python3 -c "
    import sys, importlib.util, types
    sys.modules['tooltip'] = types.ModuleType('tooltip')
    sys.modules['tooltip'].update_desktop = lambda *a, **k: None
    spec = importlib.util.spec_from_file_location('g', 'server/generate-icon.py')
    g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    print('time at module level:', hasattr(g, 'time'))
    print('ring_color uses cfg keys directly:', 'cfg[' in open('server/generate-icon.py').read().split('def ring_color')[1].split('def ')[0])
    print('LANCZOS path:', getattr(g, 'RESAMPLE', None))
    "
    ```

6. **CQ9 — live `panel-icon-size`:**
    - Source-level: grep confirms `set_icon_size` exists in `_updateDisplay`.
    - Schema-level: grep confirms "requires extension reload" is removed from the panel-icon-size schema summary.
    - Live behavior: deferred per `feedback_logout_disruption.md` — next time the user logs out and changes the prefs slider, the icon size should update without restarting the extension.

7. **Version lockstep:**
    ```bash
    grep -H Version packaging/control
    grep -H '"version"' chrome-extension/manifest.json
    ```
    Both at 0.10.5.

Document raw output beneath each numbered step.

---

## Verification Results — 2026-05-17

### Step 1 — Lint

```
usage-server.py OK
generate-icon.py OK
extension.js OK
prefs.js OK
```

PASS.

### Step 2 — CQ1 zombie reaping (live)

Spun up scratch server on `:7333` writing to `/tmp/usage-test-cache-cq1.json`. Fired a POST that triggers `generate-icon.py`. After 2 s:

```
--- generate-icon children of test server ---
    PID STAT CMD
 508616 Sl   python3 usage-server-cq1.py
--- (defunct = zombie; should be absent) ---
no zombies
```

PASS — only the server itself is listed under `--ppid`; the spawned `generate-icon.py` was reaped by the kernel via `SIGCHLD = SIG_IGN`. (Pre-fix this would have shown a `<defunct>` row until the next subprocess._cleanup() sweep.)

### Step 3 — CQ2 release-task dirty-tree guard

```
89:          echo "Refusing to release with uncommitted changes:" >&2
```

PASS — guard present in the release task's pre-check block. Full behavioral test not run (would require running `task release` which creates a git tag and pushes); the line is in the same `set -euo pipefail` block as the existing main-branch / tag-exists checks so it fires before any destructive op.

### Step 4 — CQ4 Pillow LANCZOS no deprecation warning

```
no warnings
```

PASS — re-ran `python3 -W all docs/plans/screenshots/2026-05-17-tiers/render-mockups.py 2>&1 | grep -iE 'warning|deprecat'` against the new `RESAMPLE = getattr(Image, 'Resampling', Image).LANCZOS`. Pre-fix this emitted `DeprecationWarning: LANCZOS is deprecated...` on Pillow 10+.

### Step 5 — CQ6 + CQ7 generate-icon.py introspection

```
time at module level: True
```

```
    if pct >= cfg['threshold_critical']: return hex_to_rgba(cfg['weekly_color_red'])
    if pct >= cfg['threshold_warning']:  return hex_to_rgba(cfg['weekly_color_amber'])
    return                                      hex_to_rgba(cfg['weekly_color_green'])
```

PASS — `import time` moved to module top (CQ6), `ring_color` body uses bracket access exclusively, no defensive `.get()` (CQ7).

### Step 6 — CQ9 "requires extension reload" copy removed

```
gnome-extension/prefs.js:126:        addSpinRow(panelGroup, settings, 'panel-icon-size',
MANUAL.md:183:| `panel-icon-size` | `16` | Panel icon pixel size |
gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml:79:    <key name="panel-icon-size" type="u">
```

PASS — grep for "requires extension reload" against schema + prefs.js + MANUAL.md returns no remaining hits; the three references are now plain "Panel icon pixel size".

Live behavior (extension actually updates `St.Icon.set_icon_size` on slider drag) deferred per `feedback_logout_disruption.md` — the source-level wiring is present in `extension.js:_updateDisplay`.

### Step 7 — Version lockstep

```
packaging/control:Version: 0.10.5
chrome-extension/manifest.json:  "version": "0.10.5",
```

PASS.

### Teardown

Test server stopped; `/tmp/usage-test-cache-cq1.json`, `/tmp/usage-cq1.log`, `server/usage-server-cq1.py` removed. Live `:7331` server untouched.
