# 2026-05-18 — Pass-13 follow-up batch: fix actionable findings, record won't-fix items

## Context

After L-1 + W-1 shipped in 0.11.5 (commit `5e1968d`), eleven pass-13 findings remain (`docs/investigations/2026-05-18-code-review-pass13.md`). Split into three groups:

1. **Fix in code (6 items, this change):** N‑1, N‑3, D‑2, S‑7, O‑1, A‑2. All small, no logout-cycle dependency to validate the source change itself.
2. **Record as won't-fix (3 items):** A‑3 (observational), N‑2 (by-design cost), D‑3 (auto-resolves with U‑1). Add to `docs/wont-fix.md` with the source link and verdict.
3. **Defer to separate larger changes (2 items):** U‑1 (`install.sh --dev` symlink mode), T‑5 (chrome.* API test shim + 5 tests, ~150 lines). Not in scope for this change.

## Files modified

### `chrome-extension/background.js` (N‑1, N‑3)

**N‑1** — make `onStartup` recreate the alarm so a wiped registry (profile corruption, uninstall/reinstall, storage quota purge) still recovers:

```js
chrome.runtime.onStartup.addListener(() => {
    chrome.alarms.create('fetch-usage', {
        delayInMinutes: INTERVAL_MINUTES,
        periodInMinutes: INTERVAL_MINUTES,
    });
    fetchUsage();
});
```

**N‑3** — log the `tabs.query` failure once per SW lifetime so future Chrome permission tightening is visible in the SW devtools instead of silently degrading to background-tab path:

```js
// Top of file, near other module-level state:
let _tabQueryWarned = false;

// Inside fetchUsage tab-reuse block:
} catch (e) {
    if (!_tabQueryWarned) {
        console.warn('Claude Usage: tabs.query failed, falling back to background tab:', e.message);
        _tabQueryWarned = true;
    }
}
```

### `gnome-extension/prefs.js` (D‑2)

**D‑2** — resolve the Chrome-ext path at runtime via the same candidate-probe pattern used for `ICON_SCRIPT` (lines 10-16). Replace the hardcoded `~/.local/share/...` subtitle:

```js
const _CHROME_EXT_CANDIDATES = [
    GLib.get_home_dir() + '/.local/share/claude-usage/chrome-extension',
    '/usr/share/claude-usage/chrome-extension',
];
const CHROME_EXT_PATH = _CHROME_EXT_CANDIDATES.find(
    p => GLib.file_test(p, GLib.FileTest.EXISTS)
) || _CHROME_EXT_CANDIDATES[0];

// In fillPreferencesWindow:
infoGroup.add(new Adw.ActionRow({
    title: 'Chrome extension',
    subtitle: `Load unpacked from: ${CHROME_EXT_PATH}`,
}));
```

### `gnome-extension/extension.js` (A‑2)

**A‑2** — two adjustments to the tier ladder:

1. Raise the stale threshold from 10 → 15 min. Tolerates one missed 7-min alarm cycle plus jitter:

   ```js
   } else if (age !== null && age > 15) {   // was age > 10; bumped to tolerate MV3 alarm jitter
       tier = 'stale';
       reason = `🕐 No update in ${age} min`;
   }
   ```

2. Only notify on entry to `broken`, not `stale`. Stale's icon-ghosting is already a visible signal; the toast adds noise without adding info. Keep the icon regen on all tier transitions:

   ```js
   if (tier !== this._lastTier) {
       if (tier === 'broken') {
           const now = Date.now();
           if (now - (this._lastNotifyTs || 0) > 5 * 60 * 1000) {
               Main.notify('Claude Usage', reason || `Status: ${tier}`);
               this._lastNotifyTs = now;
               try { GLib.file_set_contents(NOTIF_TS_FILE, String(now)); } catch (_) {}
           }
           this._spawnIconRegen(tier);
       } else if (tier === 'stale') {
           this._spawnIconRegen(tier);          // icon ghosts; no toast
       } else if (this._lastTier === 'stale' || this._lastTier === 'broken') {
           this._spawnIconRegen('normal');
       }
       this._lastTier = tier;
   }
   ```

### `scripts/claude-usage-status.py` (S‑7, O‑1)

**S‑7** — extend the existing version-mismatch block to also catch the "Chrome ext predates `_ext_version` stamping" case. The cache has data (so something IS posting) but `_ext_version` is absent → the Chrome ext is older than 0.11.1:

```python
ev = d.get('_ext_version')
if d.get('_ext_version_mismatch'):
    print(f'  Chrome ext: ⚠ v{ev or "?"} differs from server-expected version')
    print('              Fix: chrome://extensions → Claude Usage Tracker → Reload')
elif ev is None and d.get('_timestamp', 0) > 0:
    # Cache has data but no version stamp → Chrome ext predates 0.11.1's
    # _ext_version field. Most likely: user upgraded the .deb but Chrome
    # is still running the old loaded copy and was never reloaded.
    print('  Chrome ext: ⚠ running version predates 0.11.1 (no _ext_version stamp)')
    print('              Fix: chrome://extensions → Claude Usage Tracker → Reload')
```

**O‑1** — new function to enumerate Chrome's registered Claude Usage extensions and flag orphans (paths that no longer exist on disk). Called from the bottom of `__main__`:

```python
def _check_chrome_orphans():
    prefs = Path.home() / '.config/google-chrome/Default/Preferences'
    if not prefs.exists():
        return
    try:
        exts = json.loads(prefs.read_text())['extensions']['settings']
    except (KeyError, json.JSONDecodeError):
        return
    for eid, e in exts.items():
        path = e.get('path', '') or ''
        if 'claude-usage' in path and not Path(path).exists():
            print(f'  Chrome ext: ⚠ orphan registration at {path}')
            print(f'              Fix: chrome://extensions → remove "{eid[:8]}…"')
```

Add `_check_chrome_orphans()` call after `_check_extension()` in the `__main__` block.

### `docs/wont-fix.md` (record A‑3, N‑2, D‑3)

Append three entries following the existing format:

```markdown
## A‑3 — Three-install-path drift on the maintainer's machine (observational)

**Source:** [pass-13 review](investigations/2026-05-18-code-review-pass13.md)
**Verdict:** Observational — no code change

Pass-13 documented that the maintainer's live system has the source repo
4 commits ahead of the .deb install, while Chrome runs the .deb copy.
This is the symptom of U‑1 (the trap), not a separate bug. Closed when
U‑1's `install.sh --dev` mode ships in a separate change.

## N‑2 — `chrome.tabs.onActivated` listener runs on every tab activation

**Source:** [pass-13 review](investigations/2026-05-18-code-review-pass13.md)
**Verdict:** By design — cost is acceptable

The MV3 `tabs.onActivated` API doesn't accept a URL filter; the handler
must call `chrome.tabs.get(tabId)` to read the URL before deciding to
scrape. This means the SW wakes briefly on every tab switch, including
non-Claude tabs. The cost is ~µs per switch on modern hardware and the
30 s debounce inside `_autoScrapeIfEligible` caps the downstream work.

The alternative (no `onActivated` listener) means scraping doesn't
trigger when Chrome focuses an already-loaded Usage tab — which is the
specific case 0.11.4 was added to handle. Removing the handler would
re-introduce the user-visible bug it closed.

## D‑3 — Cache `plan: "Max plan"` proves source-vs-running drift

**Source:** [pass-13 review](investigations/2026-05-18-code-review-pass13.md)
**Verdict:** Evidentiary; auto-resolves with U‑1

The HEAD scraper at `chrome-extension/background.js:108` captures
`"Max"` or `"Max (5x)"`, never `"Max plan"`. A cache holding `"Max plan"`
is direct evidence the running Chrome ext is older than the comprehensive-
review JS‑6 fix. Self-resolves the moment a current Chrome ext POSTs
fresh data.
```

### Version bumps

- `packaging/control`: `0.11.5` → `0.11.6`
- `chrome-extension/manifest.json`: `0.11.5` → `0.11.6`
- `gnome-extension/metadata.json`: not bumped here — `task release` auto-increments on tag push

## Verification

1. `node --check chrome-extension/background.js gnome-extension/extension.js gnome-extension/prefs.js` — JS parses cleanly.
2. `python3 -m py_compile scripts/claude-usage-status.py` — Python parses cleanly.
3. `task test-scraper && task test-validate` — existing test suites pass.
4. **Live diagnostic check (S‑7 + O‑1):** run `claude-usage-status` on the current machine. Expect:
   - `Chrome ext: ⚠ running version predates 0.11.1` (because `_ext_version=None` in current cache, until a 0.11.x .deb is installed and reloaded)
   - `Chrome ext: ⚠ orphan registration at /home/will/.local/share/claude-usage/chrome-extension` (the known orphan)
5. **D‑2 visual check (requires Wayland session restart):** `gnome-extensions prefs claude-usage@indri.studio` shows the correct install path (e.g. `/usr/share/claude-usage/chrome-extension` on a .deb-installed system).
6. **A‑2 manual check (requires Wayland session restart):** wait for a stale tier to enter; expect no toast (icon ghosts grey instead). Wait for broken tier; expect one toast.
7. **N‑1 hard to verify locally** — requires a wiped alarm registry. Verify by code review: `onStartup` listener calls `chrome.alarms.create` before `fetchUsage`.
8. Version sync: `grep -E '0\.11\.[0-9]+' packaging/control chrome-extension/manifest.json` reports `0.11.6` in both.

## Out of scope

- **U‑1** `install.sh --dev` mode (symlink source repo into load-unpacked path) — separate change, ~30-50 lines plus uninstall handling.
- **T‑5** chrome.* API shim + fetch-orchestration tests — separate change, ~150-200 lines.
- No changes to existing tests (the changes here don't affect testable surfaces beyond the scraper, which is unchanged).
- No GNOME extension version metadata bump (handled by `task release`).
