# Remaining Pass-3 Review Fixes

**Date:** 2026-05-16  
**Status:** Planned

## Scope

All open items from `docs/investigations/2026-05-16-code-review-pass3.md` after BUG-P3-1
and BUG-P3-2 were closed.

---

## BUG-P3-3 — `.deb` initial dock icon path broken

**File:** `packaging/claude-usage-setup:15`

`claude-usage-setup` writes the user-level `.desktop` with an absolute path:

```
Icon=$HOME/.local/share/gnome-shell/extensions/claude-usage@indri.studio/icons/claude-64.png
```

On a `.deb` install the extension lands at `/usr/share/gnome-shell/extensions/`, not
`~/.local/share/`. The icon is broken until `generate-icon.py` updates it after the first
Chrome scrape.

**Fix:** Use the XDG icon theme name as the initial value — the `.deb` already installs the
icon to `/usr/share/pixmaps/` and `/usr/share/icons/hicolor/`:

```bash
Icon=claude-usage
```

---

## BUG-P3-5 — `.deb` `postinst` missing system glib schema

**Files:** `packaging/postinst`, `packaging/postrm`

`postinst` compiles the schema in the extension directory only. Plain `gsettings` commands
(documented in MANUAL.md) fail for `.deb` users without `GSETTINGS_SCHEMA_DIR`.

**Fix — `postinst`:** After the existing `glib-compile-schemas` line, add:

```bash
cp /usr/share/gnome-shell/extensions/claude-usage@indri.studio/schemas/*.xml \
   /usr/share/glib-2.0/schemas/ 2>/dev/null || true
glib-compile-schemas /usr/share/glib-2.0/schemas/ 2>/dev/null || true
```

**Fix — `postrm`:** Before the existing `glib-compile-schemas` line, add:

```bash
rm -f /usr/share/glib-2.0/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
```

---

## BUG-P3-6 — No concurrency guard on `fetchUsage()`

**File:** `chrome-extension/background.js`

Alarm and toolbar-click can call `fetchUsage()` simultaneously, opening two background
tabs and sending two POSTs. Benign (last-writer-wins) but wasteful.

**Fix:** Module-level in-flight flag:

```javascript
let _fetching = false;

async function fetchUsage() {
  if (_fetching) return;
  _fetching = true;
  try {
    /* existing body */
  } finally {
    if (tab) {
      try { await chrome.tabs.remove(tab.id); } catch (_) {}
    }
    _fetching = false;
  }
}
```

The `_fetching = false` reset moves to the bottom of the existing outer `finally` block,
after the tab-remove.

---

## Code quality — `server/generate-icon.py`

### Dead `bar_width` parameter

`bar_width` is loaded from GSettings, passed through to `update_desktop`, and accepted as
a parameter, but never used in the function body. Remove in three places:

- `load_config()`: delete `'bar_width': s.get_uint('bar-width')`
- `update_desktop` signature: drop `bar_width=10`
- `main()` call: drop the third argument `cfg.get('bar_width', 10)`

### `update_desktop` drops comment lines

The rewrite loop's allowlist silently discards `.desktop` lines starting with `#`. Add:

```python
elif line.startswith('#'):
    out.append(line)
```

between the `Icon=` branch and the general `'=' in line` branch.

---

## Code quality — `gnome-extension/prefs.js`

### Silence subprocess output in `regenIcon()`

`Gio.SubprocessFlags.NONE` inherits the prefs window's file descriptors. Use:

```javascript
Gio.Subprocess.new(
    ['python3', ICON_SCRIPT],
    Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
);
```

### Threshold cross-validation guidance

No runtime enforcement needed — inverted thresholds produce odd but non-crashing colouring.
Update subtitles to guide the user:

```javascript
addSpinRow(..., 'threshold-warning',
    'Warning threshold', '% at which color flips to warning (must be below Critical)');
addSpinRow(..., 'threshold-critical',
    'Critical threshold', '% at which color flips to critical (must exceed Warning)');
```

---

## Code quality — `Taskfile.yml`

### Release task tags before pushing branch

Unpushed commits are not reachable via the branch name on the remote after `git push origin "{{.TAG}}"` (tag-only push). Insert a branch push first:

```yaml
- git push origin HEAD
- git tag "{{.TAG}}"
- git push origin "{{.TAG}}"
```

---

## Verification

1. `python3 server/generate-icon.py` — exits 0
2. `grep bar_width server/generate-icon.py` — no matches
3. `grep 'Icon=' packaging/claude-usage-setup` → `Icon=claude-usage`
4. `grep glib-2.0 packaging/postinst` → schema copy present
5. `grep glib-2.0 packaging/postrm` → schema removal present
