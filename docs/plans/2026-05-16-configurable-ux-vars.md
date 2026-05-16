# Plan: Move all UX variables to GSettings

## Context

Popup colors in the GNOME extension were hardcoded and illegible on light themes. Every visual constant in `extension.js` requires a GNOME Shell restart to change on Wayland. The extension already uses GSettings for `poll-interval` — extending it to cover all UX variables is the idiomatic GNOME approach and eliminates the file-watcher complexity. The existing `config.json` (used for dock icon colors) is replaced entirely.

---

## Schema — `org.gnome.shell.extensions.claude-usage.gschema.xml`

Add all new keys. GSettings key names use hyphens.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `weekly-color-green` | `s` | `#8cff8c` | Dock icon outer ring, usage < warning threshold |
| `weekly-color-amber` | `s` | `#ffe033` | Dock icon outer ring, usage ≥ warning threshold |
| `weekly-color-red` | `s` | `#ff5933` | Dock icon outer ring, usage ≥ critical threshold |
| `sonnet-color` | `s` | `#4dbfff` | Dock icon inner (Sonnet) ring |
| `popup-color-normal` | `s` | `#2a9a2a` | Popup text, usage < warning threshold |
| `popup-color-warning` | `s` | `#d07000` | Popup text, usage ≥ warning threshold |
| `popup-color-critical` | `s` | `#e03030` | Popup text, usage ≥ critical threshold |
| `threshold-warning` | `u` | `50` | % at which color flips to warning |
| `threshold-critical` | `u` | `80` | % at which color flips to critical |
| `bar-width` | `u` | `10` | █░ bar character count in popup |
| `panel-font-size` | `u` | `11` | Panel label font size (px) |
| `popup-font-size` | `u` | `10` | Popup meter row font size (px) |
| `popup-font-family` | `s` | `monospace` | Popup meter row font family |
| `panel-icon-size` | `u` | `16` | Panel icon pixel size |

---

## `gnome-extension/extension.js`

1. **Remove** `CONFIG_FILE`, the module-level `_config`/`DEFAULTS`, and `loadConfig()` — no longer needed.

2. **`pctColor(pct)`** — reads from `this._settings` (already available on the indicator); change the function to a method or pass settings as a parameter. Use `get_uint('threshold-critical')`, `get_uint('threshold-warning')`, `get_string('popup-color-*')`.

3. **Live updates** — replace config file watching with `this._settings.connect('changed', (_s, key) => { this._updateDisplay(); })`. No `_watchConfig()` needed. Store the handler ID; disconnect in `destroy()`.

4. **`bar(pct)`** call — pass `this._settings.get_uint('bar-width')`.

5. **Panel label styles** — use `get_uint('panel-font-size')`.

6. **Popup item style** — use `get_uint('popup-font-size')` and `get_string('popup-font-family')`.

7. **`icon_size`** — use `get_uint('panel-icon-size')` at construction time. No live-reload (note in prefs subtitle).

8. **Remove `_watchConfig()`** and `_configMonitor` entirely.

---

## `gnome-extension/prefs.js`

1. **Remove** `CONFIG_PATH`, `COLOR_DEFAULTS`, `readConfig()`, `writeConfig()`. All reads/writes go through `settings` (already passed to `fillPreferencesWindow`).

2. **Remove** `regenIcon()` call from color change handlers — icon regeneration is now triggered by the settings `changed` signal in `extension.js`. *(Or keep it if generate-icon.py still needs an explicit trigger — see below.)*

3. **Update existing "Dock Icon Colors" group** — replace `cfg[key]` / `writeConfig()` with `settings.get_string(key)` / `settings.set_string(key, value)` using hyphenated key names.

4. **Add "Popup Colors" group** — 3 `Gtk.ColorDialogButton` rows for `popup-color-normal`, `popup-color-warning`, `popup-color-critical`.

5. **Add "Popup Display" group** — `Adw.SpinRow` entries for `threshold-warning`, `threshold-critical`, `bar-width`, `popup-font-size`.

6. **Add "Popup Font" group** — `Adw.EntryRow` for `popup-font-family`.

7. **Add "Panel" group** — `Adw.SpinRow` for `panel-font-size`; `Adw.SpinRow` for `panel-icon-size` (subtitle: "requires reloading the extension").

---

## `server/generate-icon.py`

Replace `json.load(config_file)` with GSettings read:

```python
from gi.repository import Gio
settings = Gio.Settings.new('org.gnome.shell.extensions.claude-usage')
cfg = {
    'weekly_color_green': settings.get_string('weekly-color-green'),
    'weekly_color_amber': settings.get_string('weekly-color-amber'),
    'weekly_color_red':   settings.get_string('weekly-color-red'),
    'sonnet_color':       settings.get_string('sonnet-color'),
}
```

Remove all config file reading. The rest of the script is unchanged.

---

## `install.sh`

After copying the schema, run:
```sh
glib-compile-schemas ~/.local/share/gnome-shell/extensions/claude-usage@wbnorris.gmail.com/schemas/
```
(This is likely already there — verify and add if not.)

---

## Critical files

- `gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml`
- `gnome-extension/extension.js`
- `gnome-extension/prefs.js`
- `server/generate-icon.py`
- `install.sh` — verify `glib-compile-schemas` step

---

## `gnome-extension/extension.js` — row formatting (tooltip + popup)

Both tooltip and popup use the same 4-column aligned format:

```
Col 1  label      padEnd(maxLabelLen across all meters)
Col 2  pct/count  padStart(4)  →  " 1%", "100%", "0/15"
Col 3  bar        fixed width (bar-width setting); blank for count meters
Col 4  reset      plain left-align
```

**Popup mockup — no extra usage:**
```
Max plan · 2m ago
──────────────────────────────────────────────────────────────
● All models                  1%  ░░░░░░░░░░  Resets Tue 1:00 PM
  Sonnet only                 2%  ░░░░░░░░░░  Resets Tue 1:00 PM
  Current session             8%  ████░░░░░░  Resets in 2h 50m
  Claude Design               0%  ░░░░░░░░░░
  Daily included routine runs  0/15
──────────────────────────────────────────────────────────────
Open Usage Page
```

**Popup mockup — extra usage enabled** (GNOME `PopupSeparatorMenuItem` between sections):
```
Max plan · 2m ago
──────────────────────────────────────────────────────────────
● All models                  1%  ░░░░░░░░░░  Resets Tue 1:00 PM
  Sonnet only                 2%  ░░░░░░░░░░  Resets Tue 1:00 PM
  Current session             8%  ████░░░░░░  Resets in 2h 50m
  Claude Design               0%  ░░░░░░░░░░
  Daily included routine runs  0/15
  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
  Extra usage                100%  ██████████  Resets Jun 1
  $4.11 spent · $0.90 balance
──────────────────────────────────────────────────────────────
Open Usage Page
```

**Tooltip mockup — no extra usage:**
```
All models                  1%  ░░░░░░░░░░  Resets Tue 1:00 PM
Sonnet only                 2%  ░░░░░░░░░░  Resets Tue 1:00 PM
Current session             8%  ████░░░░░░  Resets in 2h 50m
Claude Design               0%  ░░░░░░░░░░
Daily included routine runs  0/15
```

**Tooltip mockup — extra usage enabled** (blank line as divider):
```
All models                  1%  ░░░░░░░░░░  Resets Tue 1:00 PM
Sonnet only                 2%  ░░░░░░░░░░  Resets Tue 1:00 PM
Current session             8%  ████░░░░░░  Resets in 2h 50m
Claude Design               0%  ░░░░░░░░░░
Daily included routine runs  0/15

Extra usage                100%  ██████████  Resets Jun 1
$4.11 spent · $0.90 balance
```

The extra usage meter row uses the same 4-column format; the spend/balance line is appended as a plain sub-line (not a meter row — no bar). In the popup it's a second non-reactive `PopupMenuItem`; in the tooltip it's an extra `\n`-separated line.

Build a `formatRows(meters, barWidth)` helper that returns `{lines: string[], hasExtra: bool}`. Use it in both:
- `_updateDisplay()` for popup menu items (monospace, looks perfect); insert `PopupSeparatorMenuItem` before extra usage if present
- `set_accessible_name(rows.join('\n'))` for the tooltip (best-effort; falls back to `'Claude Usage'` when no data)

---

## `chrome-extension/background.js` — extended scraper

Currently stops at `Additional features` and `Extra usage`. Extend to capture all three sections.

**Section 1 — Plan usage limits** (unchanged): `N% used` meters → `{label, pct, reset}`

**Section 2 — Additional features**: scan until `Extra usage` or end. Parse count meters:
- Pattern: `N / M` on a line, label 2 lines before, optional subtitle 1 line before
- Store as `{label, count, total, pct: Math.round(count/total*100), reset: null}`
- Example: `{label: 'Daily included routine runs', count: 0, total: 15, pct: 0}`

**Section 3 — Extra usage**: only captured if the toggle is enabled. Check for the toggle state by looking for the text `"Turn on extra usage"` — if present, the toggle is **off** (the CTA text disappears when it's on). If off, skip section 3 entirely. If on, scan for:
- `$N.NN spent` line → `spent`
- `N% used` line → `pct` + look back for `Resets ...` reset string
- `$N.NN` line followed by `Current balance` → `balance`
- Store as a single `{label: 'Extra usage', pct, spent, balance, reset}`

No changes to the local server or cache file format — the extra fields are just added to the meter objects; extension.js and generate-icon.py ignore unknown fields.

---

## Docs

Update `README.md` and `MANUAL.md` in the same commit:
- Replace config.json references with GSettings / prefs UI
- Update popup mockup to show aligned columns + new meters
- Update tooltip description (multi-line hover)
- Add "Additional features" and "Extra usage" sections to What you see
- Update Configuration section with full settings table
- Update Troubleshooting: remove config.json tip, add `gsettings` debugging

---

## Verification

1. After install, run `gsettings get org.gnome.shell.extensions.claude-usage popup-color-normal` — returns `'#2a9a2a'`.
2. Run `gsettings set org.gnome.shell.extensions.claude-usage popup-color-normal '#0000ff'` — popup meter rows turn blue immediately, no restart.
3. Run `gsettings set org.gnome.shell.extensions.claude-usage threshold-warning 5` — "All models" row (~1–2%) immediately shows in warning color.
4. Run `gsettings set org.gnome.shell.extensions.claude-usage bar-width 5` — bars shrink to 5 chars.
5. Open GNOME Extensions preferences → Claude Usage → verify all new groups render with current values.
6. Use a color picker in prefs → value updates in extension immediately.
7. Run `python3 server/generate-icon.py` — icon regenerates using colors from GSettings.
