# Code Review — Pass 3

**Date:** 2026-05-16  
**Scope:** Full re-read of every source file; verification of all pass‑2 findings  
**Prior art:** `2026-05-16-code-review.md` (pass 1), `2026-05-16-code-review-pass2.md` (pass 2)

---

## Pass‑2 Findings — Verified Current Status

| ID | Description | Status |
|----|-------------|--------|
| BUG-P2-1 | `claude-usage-setup` created config.json that nothing reads | ✓ Fixed — block removed; file no longer written |
| BUG-P2-2 | `packaging/control` version 0.9, Chrome manifest 1.0 | ✓ Both confirmed at 0.9 — in sync |
| BUG-P2-3 | Uninstall missed alternating icon files | ✓ Fixed — `install.sh` removes `claude-usage-icon*.png` glob |
| BUG-P2-4 | `claude-usage-setup` desktop icon used old filename | Partial — old path removed, new path introduced; see BUG-P3-3 below |
| `padStart(4)` overflow | Count column broke at double-digit values | ✓ Fixed — `formatRows` now computes `maxCol2` across all rows |
| `addlIdx` duplication | `findIndex` called twice for same result | ✓ Fixed — removed |
| `_debug` in production | Debug payload shipped permanently | ✓ Fixed — `_debug` field removed from extension return |
| Missing `build-chrome-zip` task | Task absent from Taskfile | ✓ Fixed — task present; `release` deps both `.deb` and zip |

---

## New Bugs

### ~~BUG-P3-1~~ — Medium: Dock icon ring color thresholds hardcoded, disconnected from GSettings ✓ Fixed

**File:** `server/generate-icon.py:66–68`

```python
def ring_color(pct, cfg):
    if pct >= 80: return hex_to_rgba(cfg['weekly_color_red'])
    if pct >= 50: return hex_to_rgba(cfg['weekly_color_amber'])
    return             hex_to_rgba(cfg['weekly_color_green'])
```

`load_config()` reads four color strings from GSettings (`weekly-color-*`, `sonnet-color`) but
does **not** read `threshold-warning` or `threshold-critical`. The 80 and 50 magic numbers
match the schema defaults, so the dock icon behaves correctly at default settings — but a user
who customises thresholds (e.g. warning=65, critical=90) will see the popup and panel label
change colour correctly while the dock icon ring continues switching at 50 and 80.

**Impact:** Silent user-visible inconsistency. The dock icon is the most prominent indicator;
having it disagree with the popup is confusing.

**Fix:** Add `threshold_warning` and `threshold_critical` to `load_config()`, then use them in
`ring_color`:

```python
# in load_config():
'threshold_warning':  s.get_uint('threshold-warning'),
'threshold_critical': s.get_uint('threshold-critical'),

# in ring_color():
def ring_color(pct, cfg):
    if pct >= cfg.get('threshold_critical', 80): return hex_to_rgba(cfg['weekly_color_red'])
    if pct >= cfg.get('threshold_warning',  50): return hex_to_rgba(cfg['weekly_color_amber'])
    return hex_to_rgba(cfg['weekly_color_green'])
```

---

### ~~BUG-P3-2~~ — Medium: Tab listener never removed on 30‑second timeout — accumulates across calls ✓ Fixed

**File:** `chrome-extension/background.js:27–36`

```javascript
await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('tab load timeout')), 30_000);
    chrome.tabs.onUpdated.addListener(function listener(tabId, info) {
        if (tabId !== tab.id) return;
        if (info.status === 'complete') {
            chrome.tabs.onUpdated.removeListener(listener);  // only called on success
            clearTimeout(timeout);
            resolve();
        }
    });
});
```

`chrome.tabs.onUpdated.removeListener(listener)` is called only in the success branch.
If the timeout fires (`reject` path), the listener is never removed. It remains globally
registered for the lifetime of the service worker. On each subsequent call where a timeout
occurs, another orphaned listener is added. Chrome service workers can be suspended and
resumed, partially resetting state, but the listener accumulation is real within a single
active session.

**Risk:** Chrome recycles tab IDs. A future tab whose ID matches a previously timed-out
`tab.id` will trigger stale listener(s) that attempt to resolve/reject an already-settled
promise. The actual effect depends on Chrome's internal promise state (typically a no-op),
but any code that runs after the stale `resolve()` (e.g. the script injection) is a concern.

**Fix:** Remove the listener unconditionally in the timeout callback:

```javascript
const timeout = setTimeout(() => {
    chrome.tabs.onUpdated.removeListener(listener);
    reject(new Error('tab load timeout'));
}, 30_000);
```

---

### ~~BUG-P3-3~~ — Medium: `.deb` path: `claude-usage-setup` writes user‑path icon that doesn't exist ✓ Fixed

**File:** `packaging/claude-usage-setup:15`

```bash
Icon=$HOME/.local/share/gnome-shell/extensions/claude-usage@indri.studio/icons/claude-64.png
```

On a `.deb` install the GNOME extension lands at `/usr/share/gnome-shell/extensions/`, not
at `~/.local/share/gnome-shell/extensions/`. The user-level `.desktop` created by
`claude-usage-setup` therefore points to a non-existent path. The user sees a generic broken
icon in the dock until `generate-icon.py` runs after the first Chrome scrape (~15 minutes).

The `.deb` already ships a system-level `.desktop` with `Icon=claude-usage` (a theme-resolved
name backed by `/usr/share/pixmaps/claude-usage.png` and
`/usr/share/icons/hicolor/64x64/apps/claude-usage.png`), but `claude-usage-setup` overwrites
it with the broken user-level entry.

**Fix:** Use the icon theme name as the initial value; `generate-icon.py` will replace it
on first run:

```bash
Icon=claude-usage
```

For source installs (where `~/.local/share/gnome-shell/extensions/` is valid), this is also
safe because `generate-icon.py` updates `Icon=` after the first scrape anyway.

---

### ~~BUG-P3-4~~ — Version mismatch resolved

**Files:** `packaging/control:2`, `chrome-extension/manifest.json:4`

Both files confirmed at `0.9` by direct read. The `dist/` directory contains a stale
`claude-usage_1.0_all.deb` artifact, but the source-of-truth files are in sync.
No action required.

---

### ~~BUG-P3-5~~ — Low: `.deb` path: `gsettings` CLI commands fail without `GSETTINGS_SCHEMA_DIR` ✓ Fixed

**File:** `packaging/postinst`

`postinst` runs `glib-compile-schemas` only in the GNOME extension's own schemas directory:

```bash
glib-compile-schemas \
    /usr/share/gnome-shell/extensions/claude-usage@indri.studio/schemas/
```

It does **not** install the schema to `/usr/share/glib-2.0/schemas/`. GNOME Shell finds the
schema via the extension path, so the preferences UI works. But the MANUAL.md documents
`gsettings set org.gnome.shell.extensions.claude-usage ...` commands that require the schema
to be in the default glib search path. For `.deb` users, those commands fail:

```
error: No such schema 'org.gnome.shell.extensions.claude-usage'
```

without `export GSETTINGS_SCHEMA_DIR=/usr/share/gnome-shell/extensions/claude-usage@indri.studio/schemas/`.

The source-install path handles this correctly — `install.sh:66–69` copies the schema to
`~/.local/share/glib-2.0/schemas/` and recompiles.

**Fix:** Add to `postinst`:

```bash
cp /usr/share/gnome-shell/extensions/claude-usage@indri.studio/schemas/*.xml \
   /usr/share/glib-2.0/schemas/
glib-compile-schemas /usr/share/glib-2.0/schemas/ 2>/dev/null || true
```

And add the inverse cleanup to `postrm`:

```bash
rm -f /usr/share/glib-2.0/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
glib-compile-schemas /usr/share/glib-2.0/schemas/ 2>/dev/null || true
```

---

### ~~BUG-P3-6~~ — Low: No concurrency guard — alarm + toolbar click can open two tabs simultaneously ✓ Fixed

**File:** `chrome-extension/background.js`

`fetchUsage()` is triggered by two independent sources: the Chrome alarm (every 15 minutes)
and `chrome.action.onClicked`. If a user clicks the toolbar icon while the 15-minute alarm's
fetch is already in flight, two concurrent `fetchUsage()` calls run independently. Each opens
a background tab, scrapes the page, and POSTs to the server. The second POST overwrites the
first (last-writer-wins on the cache), and both tabs are cleaned up in `finally`. The result
is correct but wastes a tab and a server round-trip.

**Fix:** Track an in-flight flag and early-return:

```javascript
let _fetching = false;
async function fetchUsage() {
  if (_fetching) return;
  _fetching = true;
  try { /* existing body */ }
  finally { _fetching = false; }
}
```

---

## Code Quality

### ~~`update_desktop` accepts `bar_width` but never uses it~~ ✓ Fixed

**File:** `server/generate-icon.py:186, 214`

```python
def update_desktop(meters, icon_path, bar_width=10):
    ...                        # bar_width never referenced in the body
    name = format_tooltip(meters).replace('\n', r'\n')
```

`main()` passes `cfg.get('bar_width', 10)`, `load_config()` reads `bar-width` from GSettings,
but `format_tooltip` doesn't accept or use it. Dead parameter in both the call and the
definition.

**Fix:** Remove `bar_width` from `update_desktop`'s signature, the call in `main()`, and the
`bar_width` key from `load_config()`.

---

### ~~`update_desktop` silently drops `.desktop` comment lines~~ ✓ Fixed

**File:** `server/generate-icon.py:195–199`

```python
elif line.startswith('[') or '=' in line or line == '':
    out.append(line)
# else: skip orphaned lines from a previous broken write
```

Lines starting with `#` (comments) don't match any branch and are silently dropped. The
`.desktop` files written by this project contain no comments, so there is no regression today.
However, if a user or other tool adds comments to the file, a subsequent icon update will
remove them without warning.

**Fix:** Add `elif line.startswith('#')` to the preserve-as-is branch, or replace the
allowlist with a denylist (only skip lines that match the "orphaned" heuristic).

---

### ~~No threshold cross-validation in prefs — warning can exceed critical~~ ✓ Fixed (subtitle guidance added)

**File:** `gnome-extension/prefs.js:91–94` / `gnome-extension/extension.js:53–56`

`threshold-warning` and `threshold-critical` are independent spinners with range `[1, 99]`.
Nothing prevents setting warning ≥ critical. When warning=80 and critical=50, `pctColor`
checks critical first (50); every value ≥ 50 returns the critical colour; warning colour is
unreachable. The dock icon `ring_color` would show the same pathology once fixed (BUG-P3-1).

There is no crash — the result is just confusing colouring. Worth adding a subtitle hint in
prefs ("must be below Critical threshold") or enforcing in the spinrow `value-changed`
callback.

---

### ~~`prefs.js:regenIcon()` spawns with `Gio.SubprocessFlags.NONE` — stdout/stderr inherited~~ ✓ Fixed

**File:** `gnome-extension/prefs.js:12`

```javascript
Gio.Subprocess.new(['python3', ICON_SCRIPT], Gio.SubprocessFlags.NONE);
```

`Gio.SubprocessFlags.NONE` inherits the parent's file descriptors. Any output from
`generate-icon.py` (including the `print(f'Icon: All={all_pct}%...')` status line) goes to
the prefs window's log. Use `STDOUT_SILENCE | STDERR_SILENCE` flags for cleanliness.

---

### ~~`release` Taskfile task tags before pushing the branch~~ ✓ Fixed

**File:** `Taskfile.yml:31–41`

```yaml
- git tag "{{.TAG}}"
- git push origin "{{.TAG}}"
- gh release create "{{.TAG}}" ...
```

The task pushes the tag but not the branch. If the current branch has unpushed commits,
`git push origin "{{.TAG}}"` succeeds but the commits behind the tag are unreachable via
the branch name on the remote until the developer pushes separately. A `git push origin HEAD`
before `git tag` would close this gap.

---

### `build-chrome-zip.sh` uses `cd` rather than an explicit source path for the zip

**File:** `packaging/build-chrome-zip.sh:9–10`

```bash
cd "$REPO_DIR/chrome-extension"
zip -r "$OUT" . -x "*.DS_Store" -x "__pycache__/*" -x "*.pyc"
```

Zipping from `.` after a `cd` is correct but fragile in error conditions — if `cd` fails,
`zip -r "$OUT" .` zips the caller's working directory instead of failing cleanly. With
`set -euo pipefail` in place, a failed `cd` would abort the script before the `zip` line,
so this is safe in practice. Cosmetic note only.

---

## Security

### No new attack surface found

All findings from passes 1 and 2 are confirmed present:
- Cache file 0o600 (`usage-server.py:65`)
- POST body schema validation via `_validate()` (415, 422, 400 returns)
- Percentage clamping at scrape time (`background.js:65, 83, 102`)
- Server bound to 127.0.0.1 only

Minor addition: the `plan`, `spent`, and `balance` string fields from the Chrome extension
are written to the cache without length limits. A malicious local process could POST
arbitrarily long strings. Impact is limited to GNOME popup display corruption and `.desktop`
Name= bloat. Not worth adding a length check given the loopback-only binding, but noted.

---

## Architecture Observations

### Silent failure cascade is the primary operational risk

If the Chrome service worker is suspended (browser closed, Chrome crash), there is no
alerting mechanism until the data age crosses 30 minutes. The GNOME extension then fires one
`Main.notify()` desktop notification and sets the `⚠` prefix — both require the user to
notice. For a usage indicator whose purpose is to surface approaching limits, a user who
closes Chrome for an evening could miss a quota threshold entirely.

This is a design-level trade-off: the current approach is correct given that the extension
deliberately avoids background-always-on network calls. Documenting it in MANUAL.md's
Troubleshooting section ("If the panel shows ⚠...") would help users understand the expected
failure mode.

### Data flow is unidirectional and clear

```
Chrome Extension (alarm/click)
    │  POST {meters[], plan, _timestamp}
    ▼
usage-server.py (127.0.0.1:7331)
    │  write ~/.cache/claude-usage.json (0o600)
    ├──▶ spawn generate-icon.py
    │         ├── read GSettings (colors, thresholds)
    │         ├── render PNG (Cairo → PIL resize)
    │         ├── timestamped filename (GNOME pixbuf cache bust)
    │         └── update Icon= in ~/.local/share/applications/claude-usage.desktop
    │
    └──▶ GLib.FileMonitor fires in GNOME Shell
              │
              ▼
         extension.js (panel label, popup, poll timer)
```

No shared mutable state between processes; each reads the same `claude-usage.json`. The
timestamped-filename approach for GNOME pixbuf cache busting guarantees a cache miss on every
write; old files are cleaned up by the generator on each run.

### `.deb` install creates three `.desktop` files at different stages

1. `build-deb.sh` embeds `/usr/share/applications/claude-usage.desktop` with `Icon=claude-usage`
2. `claude-usage-setup` overwrites with `~/.local/share/applications/claude-usage.desktop` using an absolute path (see BUG-P3-3)
3. `generate-icon.py` subsequently updates `Icon=` in that same user-level file on each fetch

The user-level entry always wins (higher XDG precedence). Step 2 should emit
`Icon=claude-usage` (step 1's value) rather than a hardcoded path, making the three-stage
sequence coherent.

---

## Verified-OK (pass 1+2 fixes, confirmed in current source)

| Item | File:Line | Status |
|------|-----------|--------|
| UUID fix | `packaging/claude-usage-setup:29` | ✓ `claude-usage@indri.studio` |
| Cache guard | `generate-icon.py:204` | ✓ `if not CACHE_JSON.exists(): sys.exit(0)` |
| StopIteration | `generate-icon.py:14–23` | ✓ `next(..., None)` + explicit None check |
| File permissions | `usage-server.py:65` | ✓ `os.chmod(OUTPUT, 0o600)` |
| Schema validation | `usage-server.py:12–31` | ✓ `_validate()`, returns 422/415/400 |
| Pct clamping | `background.js:65,83,102` | ✓ `Math.min(100, Math.max(0,...))` |
| Stale-data warning | `extension.js:211–217` | ✓ `⚠` + `Main.notify` on fresh→stale |
| Offline flush | `background.js:7–20` | ✓ `chrome.storage.local` flush at top of `fetchUsage` |
| Sonnet ring track | `generate-icon.py:117–121` | ✓ No `track=False`; full ring visible at low pct |
| DEFAULTS sync comment | `generate-icon.py:33` | ✓ `# keep in sync with gschema.xml` |
| Schema in user glib path | `install.sh:66–69` | ✓ `~/.local/share/glib-2.0/schemas/` installed |
| Diagnostics script | `scripts/claude-usage-status.sh` + `install.sh:77–80` | ✓ symlinked to `~/.local/bin/` |
| `formatRows maxCol2` | `extension.js:60–63,70` | ✓ dynamic width, no overflow |
| `_debug` removed | `background.js:116` | ✓ `return {meters, plan, _timestamp}` only |
| config.json removed | `packaging/claude-usage-setup` | ✓ no config.json written |
| Alternating icon cleanup | `install.sh:33–35` | ✓ removes -icon.png, -a.png, -b.png |
| Taskfile chrome zip task | `Taskfile.yml:17–22` | ✓ present; `release` deps both |

---

## Priority Summary

| Priority | Count | Items |
|----------|-------|-------|
| Medium | 0 | — all closed |
| Low | 0 | — all closed |
| Code quality | 0 | — all closed |

---

## Overall Assessment

**Grade: A (unchanged)**

All pass‑1 and pass‑2 findings are verified resolved. Pass 3 finds no regressions in the
core data pipeline (Chrome → server → cache → GNOME extension + dock icon): the path is
correct, validated, and secure.

The three medium bugs all live in the `.deb` install path or in an edge case (scrape timeout)
that does not affect normal operation. The most impactful new finding is BUG-P3-1: the dock
icon ring ignores user-configured thresholds. Fixing it is a two-line change to `load_config`
and a two-line change to `ring_color`.

What would move this to A+:
1. BUG-P3-1 (ring color threshold consistency) — one-liner fix, visible correctness improvement
2. BUG-P3-2 (tab listener cleanup on timeout) — one-liner fix, prevents listener accumulation
3. BUG-P3-3 + BUG-P3-5 (`.deb` install polish) — `Icon=claude-usage` placeholder + schema in glib path
4. Chrome Web Store publication (open from pass 1 — external process gap, not a code defect)
