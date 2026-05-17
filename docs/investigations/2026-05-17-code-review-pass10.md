# Code Review — Pass 10

**Date:** 2026-05-17  
**Scope:** Full codebase — Chrome extension, GNOME extension, Python server, packaging  
**Prior passes:** 1–9 (all actionable items closed; see `docs/wont-fix.md` for permanent deferrals)

---

## Findings

### E-7 · `_lastCritNotifyTs` not persisted across extension reloads (High)

**File:** `gnome-extension/extension.js` line 303

E-6 persisted `_lastNotifyTs` (the cooldown for stale/broken tier toasts) to
`~/.cache/claude-usage/notif-ts`, but there are **two** notification cooldowns and only
one was fixed. The critical-pacing notification uses a separate field:

```js
if (now - (this._lastCritNotifyTs || 0) > 5 * 60 * 1000) {
    Main.notify('Claude Usage', `⚠ ${critMeter.label} is at …`);
    this._lastCritNotifyTs = now;
```

`_lastCritNotifyTs` still resets to undefined on every extension reload, so a GNOME
Shell restart mid-outage fires a duplicate critical toast.

**Fix:** Persist to a second file (e.g. `notif-crit-ts`) with the same read/write
pattern used for E-6.

---

### E-8 · CSS injection via `popup-font-family` GSettings value (Medium)

**File:** `gnome-extension/extension.js` lines 384–385, 409

The user-controlled `popup-font-family` setting is interpolated directly into a CSS
rule with no validation:

```js
const popupFont = s.get_string('popup-font-family');
const style     = `font-family: ${popupFont}; font-size: ${popupSize}px;`;
// …
item.label.set_style(`${style} color: ${color};`);
```

A value like `monospace; font-size: 99px; background` breaks out of the declaration and
injects arbitrary CSS into every popup row, corrupting the menu layout. This is
self-inflicted (the user controls their own GSettings), but it means a typo in prefs
can silently break the menu.

**Fix:** Validate the value to a safe subset before use — accept only font-family-safe
characters:

```js
const rawFont = s.get_string('popup-font-family');
const popupFont = /^[\w\s,'"-]+$/.test(rawFont) ? rawFont : 'monospace';
```

Alternatively, validate in prefs.js on save so the bad value never lands in GSettings.

---

### K-1 · `test/` directory bundled in the published Chrome Web Store zip (Medium)

**File:** `packaging/build-chrome-zip.sh` line 10

```bash
zip -r "$OUT" . -x "*.DS_Store" -x "__pycache__/*" -x "*.pyc"
```

The zip is built from the entire `chrome-extension/` directory with only a handful of
exclusions. `test/scraper.test.js` and `test/` are included in the uploaded extension.
Chrome Web Store reviews may flag test files as unused code; more concretely, they add
~6 KB to the extension size for no user benefit.

**Fix:** Add the exclusion:

```bash
zip -r "$OUT" . -x "*.DS_Store" -x "__pycache__/*" -x "*.pyc" -x "test/*"
```

---

### B-5 · `parseInt` called without radix throughout Chrome extension (Low / Style)

**Files:** `chrome-extension/background.js` lines 52, 54, 58, 115, 131, 132, 152  
**Files:** `chrome-extension/scraper.js` lines 15, 17, 22

All `parseInt` calls omit the radix argument. The `\d+` regex ensures only decimal
digits reach these calls so the behavior is correct, but `parseInt` without radix is
a longstanding JS lint warning and leaves a subtle footgun if the regex ever changes.

**Fix:** Append `, 10` to every `parseInt` call in both files.

---

### M-2 · `host_permissions` broader than necessary (Low / Security hygiene)

**File:** `chrome-extension/manifest.json` lines 8–10

```json
"host_permissions": [
  "https://claude.ai/*",
  "https://status.claude.com/*",
  "http://127.0.0.1:7331/*"
]
```

The extension only ever navigates to and scrapes `https://claude.ai/settings/usage`.
Declaring `https://claude.ai/*` grants implicit `tabs` and `scripting` access to every
claude.ai page (conversations, projects, etc.), which widens the blast radius if the
extension is ever compromised.

**Fix:** Tighten to the paths actually used:

```json
"host_permissions": [
  "https://claude.ai/settings/usage*",
  "https://status.claude.com/api/v2/*",
  "http://127.0.0.1:7331/*"
]
```

---

### K-2 · `postinst` and `postrm` use `set -e` only (Low)

**Files:** `packaging/postinst` line 2, `packaging/postrm` line 2

Both scripts open with `set -e` but omit `-u` (undefined variable error) and
`-o pipefail` (pipeline failure propagation). While no pipes or variable expansions
currently trigger these guards, adding them now is cheap insurance against future edits.

**Fix:** Change `set -e` to `set -euo pipefail` in both files.

---

### E-9 · `_watchFile` failure leaves extension without live cache updates (Low)

**File:** `gnome-extension/extension.js` lines 229–231

If `monitor_file()` throws (e.g. the cache directory doesn't exist at extension load
time — possible on a fresh install before the server has run), the catch block logs and
exits:

```js
} catch (e) {
    console.error('ClaudeUsage: file monitor failed', e);
}
```

The initial `_loadData()` still runs and loads whatever is cached, but from that point
the extension never sees updates — the panel stays frozen until the extension is
reloaded.

**Fix:** Schedule a retry from the catch block:

```js
} catch (e) {
    console.error('ClaudeUsage: file monitor failed, retrying in 30 s', e);
    GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 30, () => {
        this._watchFile();
        return GLib.SOURCE_REMOVE;
    });
}
```

---

### S-4 · Orphan `.desktop.tmp.*` cleanup can delete a live writer's temp file (Low)

**File:** `server/usage-server.py` — `_sweep_orphan_tmps()` function

The sweep globs for `claude-usage.desktop.tmp.*` and unlinks all matches. Temp files are
named `claude-usage.desktop.tmp.{PID}.{time_ns}`. If `generate-icon.py` and
`usage-server.py` both write the desktop file near-simultaneously and the sweep fires
mid-write, it could unlink a file that a live process is still writing to, leaving the
writer to call `tmp.replace(DESKTOP)` on a path it no longer owns.

**Fix:** Check PID liveness before unlinking — skip files whose PID is still running:

```python
for orphan in apps.glob('claude-usage.desktop.tmp.*'):
    try:
        pid = int(orphan.name.split('.')[-2])
        if Path(f'/proc/{pid}').exists():
            continue  # process still alive — not an orphan
    except (ValueError, IndexError):
        pass
    try:
        orphan.unlink()
    except OSError:
        pass
```

---

## Summary table

| ID | Sev | Effort | File | Description |
|----|-----|--------|------|-------------|
| E-7 | High | XS | extension.js | `_lastCritNotifyTs` not persisted (E-6 missed this field) |
| E-8 | Med | XS | extension.js | CSS injection via `popup-font-family` GSettings value |
| K-1 | Med | XS | build-chrome-zip.sh | `test/` dir bundled in CWS zip |
| B-5 | Low | XS | background.js, scraper.js | `parseInt` missing radix 10 |
| M-2 | Low | XS | manifest.json | `host_permissions` broader than needed |
| K-2 | Low | XS | postinst, postrm | `set -e` only — missing `-uo pipefail` |
| E-9 | Low | S | extension.js | `_watchFile` failure not retried |
| S-4 | Low | S | usage-server.py | Orphan sweep races with live `.tmp.*` writer |

**Effort key:** XS = 1–5 min, S = 15–30 min

---

## Items explicitly verified as non-issues

The following were raised during analysis and ruled out:

- **autoScrapeIfEligible race** — JS is single-threaded; `_fetching` guard and debounce
  check are synchronous (no await between them), so two concurrent calls can't both pass.
- **`critMeter` null dereference** — `critMeter` is only accessed inside the `else if (!this._anyCrit)` branch, which is only entered when `anyCrit` (computed by `some()` on the same `d.meters`) is `true`. `find()` is guaranteed to succeed.
- **`pacingPct` division by zero** — `!period` check at line 63 guards `period === 0`;
  negative `fraction` is caught by `fraction <= 0.01` at line 65.
- **`_period_lengths` DoS across requests** — already closed by S-2 (eviction to current
  meter labels only) and S-3 (100-key cap validated on every POST).
- **`build-chrome-zip.sh` VERSION failure** — script has `set -euo pipefail`; python3
  failure exits non-zero and propagates correctly.
