# Scraper, Server & Install Fixes — 2026-05-16

Covers everything shipped between `fd7b2b6` (GSettings migration) and the
tooltip/popup UX work in `2026-05-16-tooltip-and-popup-ux.md`.

---

## 1. Chrome extension install-path bug

**Problem:** Chrome loads an unpacked extension from whichever directory was
selected at "Load unpacked" time. The user had pointed Chrome at
`~/.local/share/claude-usage/chrome-extension/` (the install copy), not the
repo source. Reloading the extension in `chrome://extensions` picked up the
install copy — changes to the repo source were silently ignored.

**Fix — `install.sh`:**
```bash
# 2b. Chrome extension install copy (Chrome loads unpacked from this path)
mkdir -p "$SERVER_DIR/chrome-extension"
cp "$REPO_DIR/chrome-extension/"* "$SERVER_DIR/chrome-extension/"
```
Every `install.sh` run now syncs the repo source to the install directory.
After running `install.sh`, a single ↺ Reload in `chrome://extensions` picks
up the latest code.

---

## 2. "Additional features" meter not scraped (`background.js`)

**Problem:** The scraper used an exact-equality check for the section header:
```javascript
const addlStart = lines.findIndex(l => l === 'Additional features');
```
The page renders the heading with different casing or surrounding whitespace in
some views, so `addlStart` was always −1 and "Daily included routine runs" was
never captured.

**Fix:**
```javascript
const addlStart = lines.findIndex(l => /^Additional features$/i.test(l));
```

**Debug instrumentation added** (permanent — helps diagnose future scraper
regressions without needing page DevTools):
```javascript
const addlIdx = lines.findIndex(l => /^Additional features$/i.test(l));
return { meters, plan, _timestamp: Math.floor(Date.now() / 1000),
         _debug: { addlIdx, addlLines: lines.slice(Math.max(0, addlIdx-1), addlIdx+8) } };
```
The service worker logs `Claude Usage debug: {...}` to the extension's service
worker console on every fetch. Harmless in production; invaluable when
something stops being scraped.

---

## 3. `_timestamp` always zero in cache (`usage-server.py`)

**Problem:** The server was normalising a legacy `timestamp` (epoch-ms) field
that no longer exists in the payload:
```python
ts = body.pop('timestamp', None)
body['_timestamp'] = int(ts / 1000) if ts else 0  # always 0
```
The extension has always sent `_timestamp` (epoch-s) directly.

**Fix:**
```python
if '_timestamp' not in body:
    ts = body.pop('timestamp', None)
    body['_timestamp'] = int(ts / 1000) if ts else 0
```
Pass `_timestamp` through unchanged when the extension sends it; only apply the
legacy conversion for hypothetical old clients.

---

## 4. Schema missing from user glib path (`install.sh`)

**Problem:** `gsettings` CLI (outside the GNOME Shell process) looks for
schemas in `~/.local/share/glib-2.0/schemas/`, not in the extension directory.
Running `gsettings get org.gnome.shell.extensions.claude-usage ...` from a
terminal failed with "No such schema".

**Fix — `install.sh`:**
```bash
GLIB_SCHEMA_DIR="$HOME/.local/share/glib-2.0/schemas"
mkdir -p "$GLIB_SCHEMA_DIR"
cp "$REPO_DIR/gnome-extension/schemas/"*.xml "$GLIB_SCHEMA_DIR/"
glib-compile-schemas "$GLIB_SCHEMA_DIR/"
```
Also added the reciprocal removal to the `--uninstall` path.

---

## 5. Dock icon: rectangular background

**Problem:** The icon had `border-radius: 18 * SCALE` applied via a
`rounded_rect_path` fill, producing a lozenge-shaped orange background.

**Fix — `generate-icon.py`:**
```python
# before
corner_r = 18 * SCALE
rounded_rect_path(cr, 0, 0, CANVAS, CANVAS, corner_r)
# after
cr.rectangle(0, 0, CANVAS, CANVAS)
```
The generated PNG now has fully-opaque corners. GNOME's dock (`border-radius:
999px` in Yaru-dark `.dash-label` CSS) still renders tooltips as pills — that
is a GNOME theme property, not ours to control.

---

## 6. `set_accessible_name` dead code removed (`extension.js`)

The plan called for using `set_accessible_name()` as the panel-icon hover
tooltip. This API targets screen readers, not visual tooltips, and GNOME Shell
on Wayland has no hover event on panel buttons anyway. All related code was
removed:

- The `tooltipLines` loop and `set_accessible_name(tooltipLines.join('\n'))` call
- The `set_accessible_name('Claude Usage')` fallback in the empty-data branch
- The `let sawExtra` variable was moved inside the popup section where it belongs

---

## Verification

1. Run `install.sh` → `~/.local/share/claude-usage/chrome-extension/background.js`
   contains the current repo version (grep for `_debug`).
2. Reload extension in `chrome://extensions` → click toolbar icon → service
   worker console shows `Claude Usage debug: {"addlIdx":NN,...}`.
3. Cache has 5 meters including `Daily included routine runs`.
4. `cat ~/.cache/claude-usage.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['_timestamp'])"` → non-zero epoch timestamp.
5. `gsettings get org.gnome.shell.extensions.claude-usage popup-color-normal` → returns a colour string without error.
6. Dock icon corners are opaque orange (no transparent rounded corners in the PNG).
