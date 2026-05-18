# Broken/stale tier UX: age formatting + meter dimming

## Context

User saw a confusing popup state: "⚠ No data in 325 min · run claude-usage-status" alongside
meter rows showing stale data (including a garbage "sig-test" label injected during PD-1 testing).
Two problems:

1. "325 min" doesn't communicate urgency the way "5 h 25 min" would — raw minutes are hard to
   parse for large values.
2. Meter rows appear identical whether data is 30 seconds old or 5 hours old, giving no visual
   signal that what's shown is stale.

Both issues are in `gnome-extension/extension.js`.

## Files modified

### `gnome-extension/extension.js`

**UX‑1: `fmtAge(min)` helper** — converts raw minutes to human-readable "X h Y min" for ages
≥ 60 min. Add near the other helper functions (after `bar()`, before `pacingPct()`):

```js
function fmtAge(min) {
    if (min < 60) return `${min} min`;
    const h = Math.floor(min / 60);
    const m = min % 60;
    return m > 0 ? `${h} h ${m} min` : `${h} h`;
}
```

Apply in the tier-reason strings:
- Line ~395 (broken, age-based): `reason = \`⚠ No data in ${fmtAge(age)} · run claude-usage-status\`;`
- Line ~401 (stale): `reason = \`🕐 No update in ${fmtAge(age)}\`;`

**UX‑2: Meter opacity in stale/broken tier** — dim meter rows when data is known-old. The
stale/broken tier is already computed by the time the meter loop runs (line ~444 onwards). Add one
constant after computing `tier`:

```js
const meterOpacity = tier === 'broken' ? 80 : tier === 'stale' ? 140 : 255;
```

Then inside the meter item loop (line ~465), after `const item = new PopupMenu.PopupMenuItem(...)`:

```js
item.opacity = meterOpacity;
```

`PopupMenuItem` inherits from `St.BoxLayout` → `Clutter.Actor`, which has a 0–255 `opacity`
property. This dims the entire row (label + bar) without hiding it — the last-known data is still
readable but clearly secondary to the error message.

### Version bumps

- `packaging/control`: `0.11.8` → `0.11.9`
- `chrome-extension/manifest.json`: `0.11.8` → `0.11.9`

## Immediate fix for current "sig-test" cache corruption

The `sig-test` label got into `~/.cache/claude-usage/usage.json` when a test server was run during
PD-1 verification. As part of this change, delete the corrupted cache so the popup returns to the
clean "No data yet" state:

```bash
rm ~/.cache/claude-usage/usage.json
```

The extension's `_updateDisplay()` path at lines 311-317 already handles a missing/empty cache
gracefully — it shows "No data yet" and `--` in the panel. The next real scrape from the Chrome
extension repopulates it.

## Verification

1. `node --check gnome-extension/extension.js` — JS parses cleanly.
2. Version sync: `grep -E '0\.11\.[0-9]+' packaging/control chrome-extension/manifest.json` reports
   `0.11.9` in both.
3. **Age formatting:** verify `fmtAge` logic manually: `fmtAge(14)` → "14 min", `fmtAge(60)` → "1 h",
   `fmtAge(65)` → "1 h 5 min", `fmtAge(325)` → "5 h 25 min".
4. **Cache clear:** `rm ~/.cache/claude-usage/usage.json` → panel shows `--` and popup shows "No
   data yet". Popup should have no meter rows.
5. **Meter dimming (requires Wayland session restart):** with data aged > 20 min, open the popup —
   meter rows should be visibly dimmed (opacity 80/255 ≈ 31%). With fresh data they should be
   full-opacity.

## Out of scope

- Changing the "run claude-usage-status" hint text — the target audience knows this tool.
- Sub-row (spent/balance) dimming — covered automatically since sub-rows are regular `PopupMenuItem`
  instances and receive the same `item.opacity` assignment.
