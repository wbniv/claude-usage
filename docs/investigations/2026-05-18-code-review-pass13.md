# Code Review — Pass 13 (post‑0.11.4, runtime‑evidence + new‑code focus)

**Date:** 2026-05-18 (late, after the chrome-ext latency-fix run that produced 0.11.2 → 0.11.3 → 0.11.4)
**Reviewer:** Claude (Opus 4.7, max effort, 1M context)
**Scope:** Full codebase, runtime evidence from the live system, deep look at the new code in commits `51acb16`, `e36c83a`, `c222817`
**Prior work:** Passes 1–12 + the [2026-05-18 comprehensive review](2026-05-18-code-review-comprehensive.md); permanent deferrals in [docs/wont-fix.md](../wont-fix.md)

This pass starts from a different frame than the previous twelve: it follows a **live failure** through the system. While the review was in progress, the GNOME indicator fired a `"No update in 11 min"` notification. The diagnosis exposed two real problems — one a UX trap that no prior pass has surfaced, the other a regression class the comprehensive review's V‑1 fix only half‑closes. It also produced 11 other findings, most rooted in the new code that hasn't seen a review yet.

---

## 1. Executive Summary

| Sev | # | ID | Title |
|-----|---|----|-------|
| High | 1 | **U‑1** | Chrome ext loaded from .deb install path is **two patch versions behind source** — `chrome://extensions → Reload` reloads the .deb copy, not the source repo. No visible warning to the user; manifests as 12-15 min POST gaps and spurious stale notifications. |
| High | 2 | **L‑1** | `_loadData()` async callback fires on torn-down wrapper if extension is disabled mid-read — same class as E-10 (pass 12) but for `load_contents_async`, untracked, throws on `set_text` against disposed `St.Label`. |
| Medium | 3 | **N‑1** | `chrome.runtime.onStartup` handler (new in 0.11.2) calls `fetchUsage()` but doesn't recreate the alarm — if Chrome's alarm registry is ever wiped (uninstall/reinstall sequences, profile corruption), periodic scrapes are dead until next install. |
| Medium | 4 | **O‑1** | Chrome's `Preferences` cached an orphan extension registration at a deleted path (`~/.local/share/claude-usage/chrome-extension/`). No automatic cleanup; user sees a permanent load error in `chrome://extensions` after switching from source-install to .deb. |
| Medium | 5 | **D‑2** | `prefs.js:148` advertises Chrome-extension path as `~/.local/share/...` regardless of how the user installed. A .deb-only user is given the wrong path. |
| Medium | 6 | **S‑7** | `claude-usage-status` reports `_ext_version_mismatch` only when the server detected one — silent on the path where the running extension is so old it predates `_ext_version` stamping (the most common failure mode after a .deb upgrade). |
| Medium | 7 | **A‑2** | Stale-tier notifications fire too eagerly. The 7-min Chrome alarm cycle plus MV3 dormancy plus 10-min stale threshold means a perfectly healthy install can produce stale notifications during normal use (observed live: 12 min gap between cache writes). |
| Low | 8 | **N‑2** | `chrome.tabs.onActivated` listener (new in 0.11.4) runs `chrome.tabs.get()` on every tab activation across the browser, even non-Claude tabs. Cost is small (~µs) but it's the only listener that wakes the SW for unrelated tab switching. |
| Low | 9 | **N‑3** | Tab-reuse path (new in 0.11.3) doesn't handle `chrome.tabs.query` returning an error — wrapped in `try/catch`, falls through to background-tab path, but the swallow is silent. Future query-permission changes would be invisible. |
| Low | 10 | **W‑1** | `extension.js::scroll-event` handler fires `set_string('panel-metric', ...)` on every scroll tick. The `_settingsId` listener then triggers a full `_updateDisplay` per tick. Touchpad inertia + scroll-wheel sensitivity = 10-20 renders per swipe. Not a bug, but expensive. |
| Low | 11 | **D‑3** | The plan tier label that the server stores from POSTs has type `"Max plan"` (string with " plan" suffix) for some user installs, but the scraper at HEAD captures only `"Max"` / `"Max (5x)"`. The `" plan"` suffix originates from an extension version much older than HEAD — the live system shows the field has been stuck at that value for 283+ min spans because Chrome was running outdated code. Carry as confirmation of U-1 above. |
| Low | 12 | **T‑5** | No test exists for the tab-reuse logic (0.11.3) or the `onActivated` handler (0.11.4). The scraper's 45-test suite covers `doScrape`/`parseResetMinutes` only; the fetch-orchestration path is still untested. |
| Info | 13 | **A‑3** | The "three install paths" architectural drift is no longer hypothetical — on the maintainer's own machine, Chrome's Preferences holds two registrations (orphan + .deb), the server runs the .deb copy, the GNOME extension runs the .deb copy, and the source repo is 4 commits ahead of all three. The system has no mechanism to detect this. |

**Bottom line:** the pass-12 fixes are all present in source code, but **the live system is not running them.** That single observation drives U-1, S-7, A-2, D-3, and A-3 — all variations on "the maintainer's own install is running stale code and the diagnostics don't notice." The cure is partly tooling (`claude-usage-status` should detect the orphan and the stale-Chrome-ext case) and partly documentation (the upgrade path needs to be clearer).

---

## 2. Live evidence (the failure that started this pass)

At ~09:22 a GNOME notification fired: `Claude Usage — No update in 11 min`. Investigation:

```
$ stat -c '%y' ~/.cache/claude-usage/usage.json
2026-05-18 09:11:43.259081836 +0700

$ date
2026-05-18 09:24:17

$ journalctl --user --since "30 min ago" | grep "Saved.*meters"
May 18 08:54:49  Saved 5 meters → ...
May 18 08:55:02  Saved 5 meters → ...
May 18 08:55:20  Saved 5 meters → ...
May 18 08:56:42  Saved 5 meters → ...   ← cluster from earlier ext reload
May 18 09:11:43  Saved 5 meters → ...   ← 15 min after; alarm fired
                                         ← then nothing for 13+ min
```

Cache contents at the moment the notification fired:

```
_timestamp=1779070303  age=12 min
_scrape_fail_count=None
_ext_version=None              ← Chrome ext predates V-1 (pass-12) field
_ext_version_mismatch=None     ← so no mismatch ever detected
_schema=None                   ← server-written field absent → server never overwrote since merge?
plan='Max plan'                ← scraper at HEAD produces "Max" / "Max (5x)", not "Max plan"
meters=5
```

Two cache fields are tells:
- `_ext_version=None` → no Chrome extension version stamp on POST. Running Chrome ext is older than the V-1 fix (i.e., older than 0.11.1).
- `plan='Max plan'` → captured by a regex variant that doesn't exist in any background.js commit at HEAD. The current regex (`background.js:108`) captures `"Max"` or `"Max (5x)"`, never `"Max plan"`. This value has been stuck in the cache merge for at least one full reload cycle.

The two together prove the running Chrome ext is older than the source. Checking install paths:

```
$ ls /home/will/.local/share/claude-usage/chrome-extension/
ls: cannot access ...: No such file or directory          ← source-install path is gone

$ ls /usr/share/claude-usage/chrome-extension/
background.js  manifest.json  scraper.js  test  icon{16,48,128}.png

$ grep version /usr/share/claude-usage/chrome-extension/manifest.json
"version": "0.11.0",                                       ← .deb-installed at v0.11.0
```

The .deb that's installed is **0.11.0**. Source code is at **0.11.4**. The Chrome ext the user reloaded earlier in the session is loading from the .deb path — so reloading at `chrome://extensions` reloaded the stale 0.11.0 code, not the source.

And:

```
$ python3 -c "import json; \
  p = json.load(open('/home/will/.config/google-chrome/Default/Preferences')); \
  exts = p.get('extensions', {}).get('settings', {}); \
  [print(eid, e.get('path')) for eid, e in exts.items() if 'claude' in (e.get('path') or '').lower()]"
aofoofgceohpheneebpjhcmklpamniep /home/will/.local/share/claude-usage/chrome-extension
idjiiffgjoecckdpdekhekmpjdfjaahh /usr/share/claude-usage/chrome-extension
```

**Two Chrome extensions are registered.** One points at a path that doesn't exist (left over from when `install.sh` was the install method); the other points at the .deb path. Chrome silently keeps the orphan registration — only the user notices via the "could not load" entry in `chrome://extensions`.

This is the structural failure that produces U-1, O-1, D-2, S-7, and A-2 — all variations on "the diagnostics don't catch the install/source/loaded-ext mismatch."

---

## 3. Verification of pass-12 fixes (source vs running)

Pass 12's 13 findings are all present **in source code**. They are **not all present in what's running.**

| ID | Source at HEAD | Running on live system | Notes |
|----|---|---|---|
| **I‑2** `install.sh` reset-failed | ✓ present (line 139) | n/a — user installed via .deb, not install.sh | source-install path now matches setup script |
| **E‑10** `_watchFile` retry tracked | ✓ present (line 253-257) | ✗ running ext is 0.11.0 (pre-fix) | live system has the leak |
| **E‑11** `_getPrimary` defer write | ✓ present (line 491-498) | ✗ running ext is 0.11.0 (pre-fix) | live system has the double-render |
| **K‑3** install.sh `cp -r` | ✓ present (line 123) | n/a — installed via .deb | |
| **K‑4** .deb excludes `test/` | ✓ present (build-deb.sh:40) | ✓ .deb at 0.11.0 also has the fix | |
| **V‑1** `_ext_version` handshake | ✓ present (background.js:10, usage-server.py:274-280) | ✗ running Chrome ext predates the stamp | live cache shows `_ext_version=None` |
| **S‑5** drop unknown `_anthropic_status` keys | ✓ present (usage-server.py:217-220) | ✓ live | |
| **S‑6** `_period_lengths` merge | ✓ present (usage-server.py:237-240) | ✓ live | |
| **J‑2** `ICON_SCRIPT` hoisted | ✓ present (extension.js:25-27) | ✗ running ext is 0.11.0 (pre-fix) | |
| **I‑3** install.sh distro detection | ✓ present (lines 63-86) | n/a | |
| **A‑1** `_schema` field | ✓ written (usage-server.py:285) | ✗ live cache has `_schema=None` | server runs 0.11.0 — pre-fix |
| **T‑4** validator tests | ✓ present (server/tests/test_validate.py, 267 lines) | n/a | tested in `task test-validate` |
| **C‑3** old-shape probe in live smoke | ✓ present (test-deb-live.sh:99-102) | n/a | runs in CI |

**5 of 13 pass-12 fixes are present in source but not on the running system** (E‑10, E‑11, V‑1, J‑2, A‑1). All of them require either rebuilding+installing the .deb or shipping a release. The maintainer is running their own old code. This is U-1's root cause.

---

## 4. New Findings

### U‑1 · Reloading at `chrome://extensions` reloads the .deb-installed code, not the source repo (High)

**Files:** `install.sh:118-125`, `packaging/build-deb.sh:39-40`, `prefs.js:148`, no diagnostic
**Discovered via:** live failure above

The maintainer has three Chrome-ext source paths in play:
- **Source repo:** `/home/will/SRC/claude-usage/chrome-extension/` (current HEAD, 0.11.4)
- **Source install (XDG):** `~/.local/share/claude-usage/chrome-extension/` (would be created by `install.sh`; deleted in current setup)
- **.deb install:** `/usr/share/claude-usage/chrome-extension/` (installed at 0.11.0)

Chrome loaded an extension from each of the first two paths. The first registration is now orphaned (path deleted). The second is the live one, frozen at the .deb's manifest version.

When the maintainer edits source and clicks **Reload** at `chrome://extensions`, Chrome reloads from `/usr/share/claude-usage/chrome-extension/` — not from `/home/will/SRC/claude-usage/chrome-extension/`. The reload is a no-op as far as the source repo is concerned. The maintainer thinks their changes are live; they're not.

**Concrete impact:** the entire chrome-ext patch chain `0.11.1 → 0.11.2 → 0.11.3 → 0.11.4` is committed but not running. The V-1 handshake (pass 12), the direct `fetchUsage()` on reload (0.11.2), the tab-reuse optimization (0.11.3), and the `onActivated` listener (0.11.4) are all dead code on the live system until someone rebuilds + installs the .deb.

**Why no prior pass caught this:** every prior pass assumed `source == running`. Pass 12's V-1 detects *server* / Chrome-ext version skew but doesn't detect *source* / running-Chrome-ext skew because the server is itself .deb-installed and matches.

**Fix (recommended):**
1. **Document the upgrade path** in `MANUAL.md` and the install.sh / setup-script output:
   > "Edits to chrome-extension/ in this repo do not take effect until you rebuild the .deb (`task build`) and reinstall (`sudo dpkg -i dist/claude-usage_<v>_all.deb`), then reload at chrome://extensions."
2. **Add a "dev mode" install path** (`install.sh --dev`): symlink the source repo into Chrome's load-unpacked path so reloads pick up edits without a .deb rebuild cycle.
3. **`claude-usage-status` should detect the case**: read `~/.config/google-chrome/Default/Preferences`, enumerate the registered Claude Usage extensions and their load paths, and check whether each path resolves to a manifest version equal to the server's `EXPECTED_EXT_VERSION`. Print warnings for mismatches and orphans.

---

### L‑1 · `_loadData()` async callback fires on disposed wrapper (High)

**File:** `gnome-extension/extension.js:261-282`

```js
_loadData() {
    const f = Gio.File.new_for_path(CACHE_FILE);
    f.load_contents_async(null, (_obj, result) => {
        try {
            const [ok, contents] = f.load_contents_finish(result);
            if (!ok) return;
            const text = new TextDecoder().decode(contents);
            this._data = JSON.parse(text);
            // ...
            this._updateDisplay();                              // ← throws on disposed St.Label
        } catch (e) {
            console.error('ClaudeUsage: failed to read cache', e);
        }
    });
}
```

`load_contents_async` queues the callback on the main loop. If the extension is disabled (user toggles extensions, reloads GNOME Shell, switches themes) between the call and the callback, `destroy()` runs and tears down `this._label`, `this._statusItem`, `this._metersSection`. The pending callback then fires and calls `_updateDisplay()`, which calls `this._label.set_text(...)` on a disposed `St.Label` — throws and the stack trace lands in `journalctl --user -t gnome-shell`.

This is the same shape as pass-12's E‑10 finding (the `_watchFile` retry callback), with the same fix structure. E‑10 was tracked because the retry source ID was stored; the async load callback doesn't have an analogous tracking handle (it's queued by GLib, not a timeout), so the fix uses a `_destroyed` flag:

```js
_loadData() {
    if (this._destroyed) return;
    const f = Gio.File.new_for_path(CACHE_FILE);
    f.load_contents_async(null, (_obj, result) => {
        if (this._destroyed) return;                            // ← guard
        try { /* unchanged */ } catch (e) { /* unchanged */ }
    });
}

destroy() {
    this._destroyed = true;                                     // ← set first
    /* existing cleanup */
}
```

**Cost of the unfixed case:** one stack trace per cache write that races a disable. Not catastrophic, but pollutes the journal and contributes to the "GNOME Shell logs are full of stuff that doesn't matter" problem.

---

### N‑1 · `chrome.runtime.onStartup` doesn't recreate the alarm (Medium)

**File:** `chrome-extension/background.js:407-410` (new in 0.11.2, commit `51acb16`)

```js
chrome.runtime.onStartup.addListener(() => {
    fetchUsage();
});
```

`onInstalled` (added at the same time) creates the alarm AND calls `fetchUsage()`. `onStartup` only does the latter. The reasoning at the time was "Chrome MV3 alarms persist across browser restarts, so we don't need to recreate it" — that's true in normal operation, but the alarm registry CAN be wiped:

- Profile corruption / Chrome crashes during write
- User clears extension data (chrome://extensions → "Details" → "Allow access to file URLs" toggle resets some state)
- Chrome's `chrome.storage` quota policy purges
- The extension is uninstalled and reinstalled within a single browser session — `onInstalled` fires once, but if the user then quits Chrome and restarts, the alarm storage might be in a transient state depending on whether Chrome had flushed the registry

The cost of adding the create call to `onStartup` is two lines and gives idempotent recovery:

```js
chrome.runtime.onStartup.addListener(() => {
    chrome.alarms.create('fetch-usage', {
        delayInMinutes: INTERVAL_MINUTES,
        periodInMinutes: INTERVAL_MINUTES,
    });
    fetchUsage();
});
```

Mirror to `onInstalled` for symmetry — both event handlers should leave the system in the same target state regardless of prior alarm registry state.

---

### O‑1 · Orphan Chrome extension registration is not cleaned up on path removal (Medium)

**Files:** none (this is an absence)
**Evidence:** live system has two Claude Usage entries in `~/.config/google-chrome/Default/Preferences`, one at a deleted path

When the user transitions install methods (e.g., source → .deb), the old registration in Chrome's `Preferences` file persists. Chrome shows it as a "could not load" entry. There's no mechanism in the project to detect or guide cleanup.

The set of "extension at a deleted path" registrations is the same as `{e for e in prefs.extensions.settings if e.path is not None and not os.path.exists(e.path)}`. `claude-usage-status` could enumerate these for the Claude Usage paths specifically:

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
        path = e.get('path', '')
        if 'claude-usage' in path and not Path(path).exists():
            print(f'  Chrome ext: ⚠ orphan registration at {path}')
            print(f'              Fix: chrome://extensions → remove "{eid[:8]}…"')
```

Cannot be automatically cleaned (Chrome doesn't expose a programmatic remove API for installed extensions). But surfacing it in `claude-usage-status` would close the gap.

---

### D‑2 · `prefs.js` advertises the wrong Chrome extension path on .deb installs (Medium)

**File:** `gnome-extension/prefs.js:147-149`

```js
infoGroup.add(new Adw.ActionRow({
    title: 'Chrome extension',
    subtitle: 'Load unpacked from: ~/.local/share/claude-usage/chrome-extension/',
}));
```

The subtitle is a hard-coded string pointing at the source-install path. A user who installed via .deb sees this exact text in the preferences UI and (correctly per the text) tries to load `~/.local/share/...` — which doesn't exist. They'd hit an error in Chrome, conclude the extension is broken, and either uninstall or open an issue.

The same probe pattern used elsewhere in the codebase (`extension.js:21-27`, `prefs.js:10-16` for `ICON_SCRIPT`) applies here:

```js
const _CHROME_EXT_CANDIDATES = [
    GLib.get_home_dir() + '/.local/share/claude-usage/chrome-extension',
    '/usr/share/claude-usage/chrome-extension',
];
const CHROME_EXT_PATH = _CHROME_EXT_CANDIDATES.find(
    p => GLib.file_test(p, GLib.FileTest.EXISTS)
) || _CHROME_EXT_CANDIDATES[0];

infoGroup.add(new Adw.ActionRow({
    title: 'Chrome extension',
    subtitle: `Load unpacked from: ${CHROME_EXT_PATH}`,
}));
```

---

### S‑7 · `claude-usage-status` is silent when the running Chrome ext predates `_ext_version` (Medium)

**File:** `scripts/claude-usage-status.py:63-66`

```python
if d.get('_ext_version_mismatch'):
    ev = d.get('_ext_version') or '?'
    print(f'  Chrome ext: ⚠ v{ev} differs from server-expected version')
    print('              Fix: chrome://extensions → Claude Usage Tracker → Reload')
```

This only fires when the server *detected* a mismatch — which requires the Chrome ext to send `_ext_version`. If the Chrome ext is so old it predates the field (pre-0.11.1), the server has nothing to compare and `_ext_version_mismatch` is never set. The diagnostic produces a clean output, even though the running ext is months out of date.

The S-7 case is the **most common upgrade failure mode**: user upgrades the .deb, server picks up the new EXPECTED_EXT_VERSION on restart, Chrome ext doesn't auto-reload, and the user has no visible signal until something else breaks. Pass 12's V-1 handshake catches the "Chrome is one version behind" case; it does not catch the "Chrome is many versions behind, before the handshake existed" case.

**Fix:** treat missing `_ext_version` as evidence of an old extension if `EXPECTED_EXT_VERSION` is set:

```python
ev = d.get('_ext_version')
if d.get('_ext_version_mismatch'):
    print(f'  Chrome ext: ⚠ v{ev or "?"} differs from server-expected version')
    print('              Fix: chrome://extensions → Claude Usage Tracker → Reload')
elif ev is None and d.get('_timestamp', 0) > 0:
    # The cache has data (so something is POSTing) but no version stamp.
    # That means the running Chrome ext is older than 0.11.1.
    print('  Chrome ext: ⚠ running version predates 0.11.1 (no _ext_version stamp)')
    print('              Fix: chrome://extensions → Claude Usage Tracker → Reload')
```

---

### A‑2 · Stale-tier notifications fire on healthy installs (Medium)

**File:** `gnome-extension/extension.js:378-410`

The tier-transition path notifies on entry to `stale` (age > 10 min) OR `broken` (age > 20 min). 5-min rate limit on notifications.

The 7-min Chrome alarm cycle + MV3 SW dormancy + occasional `tabs.create` slowness can produce 12-15 min gaps between successful POSTs even on a healthy install — confirmed live this session. Each gap that crosses 10 min produces a `stale` notification.

The user perceives this as "something's wrong" when actually the system just had a slow alarm. The 5-min rate limit prevents toast spam, but each slow cycle is one false alarm.

**Mitigations, in order of preference:**

1. **Raise the stale threshold to one full alarm cycle past target** — `2 × INTERVAL_MINUTES + 1` = 15 min. Catches actual problems while tolerating MV3 jitter.
2. **Only notify on entry to `broken`**, not `stale`. The icon-color signal (ghosted → grey for stale) is already visible; the toast is redundant for soft warnings.
3. **Distinguish "data is old" from "fetcher is stuck"** by tracking the time-since-last-successful-POST separately from data age. The current cache `_timestamp` is the scrape time, which conflates "scrape was old" with "we haven't tried recently."

Recommend option 1 + 2 together: raise threshold, notify on broken only.

---

### N‑2 · `tabs.onActivated` runs `chrome.tabs.get` for every tab activation (Low)

**File:** `chrome-extension/background.js:407-414` (new in 0.11.4, commit `c222817`)

```js
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
    try {
        const tab = await chrome.tabs.get(tabId);
        if (tab.status !== 'complete' || !tab.url) return;
        await _autoScrapeIfEligible(tabId, tab.url);
    } catch (_) {}
});
```

`onActivated` fires on every tab activation in the browser, regardless of URL. The handler calls `chrome.tabs.get(tabId)` to obtain the URL (the activation event itself only carries the tab ID). This is an inexpensive RPC, but it wakes the service worker on every alt-tab into a tab — including tabs that have nothing to do with Claude.

The intended use case is exactly one: focusing an already-loaded Usage tab. The chrome.tabs.get is the only way to filter (the URL pattern argument to `addListener` isn't accepted by `tabs.onActivated`). The cost is small enough that this is a design tradeoff rather than a bug — but worth noting in a comment that this fires on every tab switch by design.

**Mitigation (optional):** debounce by tab-ID + last-activation-time (cheap microtask-local), so very rapid tab switching doesn't wake the SW twice for the same tab. Not necessary at current usage scales.

---

### N‑3 · `tabs.query` failure silently falls through (Low)

**File:** `chrome-extension/background.js:300-307` (new in 0.11.3)

```js
let scrapeTabId = null;
try {
    const candidates = await chrome.tabs.query({ url: 'https://claude.ai/settings/usage*' });
    const reusable = candidates.find(t =>
        t.status === 'complete' && (t.url || '').split(/[?#]/)[0] === USAGE_URL);
    if (reusable) scrapeTabId = reusable.id;
} catch (_) {}
```

The `try/catch` swallows any error from `chrome.tabs.query`. If Chrome ever tightens the permission semantics (host_permissions for URL matching has been narrowed in past Chrome versions), the query would throw and the extension would silently fall through to the background-tab path forever. The user would see no visible effect (the fallback works), but the optimization wouldn't.

**Fix:** log the failure to the console once per SW lifetime so it's visible if the developer ever opens the SW devtools:

```js
} catch (e) {
    if (!self._tabQueryWarned) {
        console.warn('Claude Usage: tabs.query failed, falling back to background tab:', e.message);
        self._tabQueryWarned = true;
    }
}
```

---

### W‑1 · Scroll-event handler triggers a full render per scroll tick (Low)

**File:** `gnome-extension/extension.js:138-153`

```js
this.connect('scroll-event', (_actor, event) => {
    const dir = event.get_scroll_direction();
    if ((dir === Clutter.ScrollDirection.UP || dir === Clutter.ScrollDirection.DOWN) && this._data) {
        // ... find next/prev eligible meter ...
        this._settings.set_string('panel-metric', next.label);
        return Clutter.EVENT_STOP;
    }
});
```

Every scroll tick:
1. `set_string('panel-metric', ...)` writes GSettings.
2. The `_settingsId` listener at line 187 fires `_updateDisplay()` synchronously (GSettings dispatches changed signals sync).
3. `_updateDisplay()` reads 10+ GSettings keys, rebuilds the entire popup, recomputes pacing for every meter.

A trackpad swipe with momentum fires 10-20 scroll events. Each one re-renders the popup. The user doesn't see flicker (Clutter coalesces) but the CPU work is real, and on slower hardware (especially Wayland with software rendering), it's visible as scroll lag.

**Fix:** debounce the GSettings write with a short timeout (matching the PREFS-1 pattern from the comprehensive review):

```js
let _scrollTimer = null;
this.connect('scroll-event', (_actor, event) => {
    // ... compute next.label ...
    if (_scrollTimer) GLib.source_remove(_scrollTimer);
    _scrollTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
        _scrollTimer = null;
        this._settings.set_string('panel-metric', pendingLabel);
        return GLib.SOURCE_REMOVE;
    });
});
```

---

### D‑3 · Cache `plan: "Max plan"` proves the running ext is older than HEAD (Low, evidentiary)

This is not a bug per se — it's the smoking gun that confirms U-1 above. The HEAD scraper at `background.js:108` and `scraper.js:53` captures `"Max"` (with optional ` (5x)` suffix). It never captures the string `"Max plan"`. The cache currently holds `"Max plan"`, which means it was written by an extension version old enough that the regex shape differed — probably 0.9.x or earlier, before the comprehensive-review JS-6 fix.

Carry as confirmation. Resolved automatically when U-1 is addressed and the user upgrades.

---

### T‑5 · No tests for the new fetch-orchestration paths (Low)

**Files:** `chrome-extension/background.js:254-358` (fetchUsage), `chrome-extension/background.js:407-414` (onActivated)

The 45-test scraper suite (`chrome-extension/test/scraper.test.js`) covers `doScrape`, `parseResetMinutes`, `isHydrated`. It does not cover:

- The tab-reuse decision (`tabs.query` returns reusable tab → skip create)
- The `onActivated` listener filtering
- The orphan-tab-cleanup at the top of `fetchUsage`
- The offline-buffer flush at the top of `fetchUsage`
- The `onInstalled` direct-fetch path

The `chrome.*` API isn't easily mockable in node's test runner without a shim. But a thin test that mocks `chrome.tabs.query`, `chrome.tabs.create`, `chrome.tabs.get`, `chrome.scripting.executeScript`, `chrome.storage.local`, and `fetch` would catch regressions in the orchestration logic. Estimate ~150 lines of test for ~5 tests covering the decision branches.

---

### A‑3 · Three-install-path drift is no longer hypothetical (Informational)

The maintainer's live machine has:

| Component | Path | Version |
|-----------|------|---------|
| Source repo | `/home/will/SRC/claude-usage/` | HEAD = 0.11.4 |
| .deb install | `/usr/share/claude-usage/` | 0.11.0 |
| Running server | (.deb path) | 0.11.0 |
| Running Chrome ext | (.deb path) | 0.11.0 |
| Running GNOME ext | `/usr/share/gnome-shell/extensions/claude-usage@indri.studio/` | 0.11.0 |
| Chrome's orphan registration | `~/.local/share/claude-usage/chrome-extension` | (path deleted) |

Nothing in the project's diagnostics detects this — `claude-usage-status` reports "✓ present, plan: Max plan" with no indication that the running code is 4 commits behind. The maintainer caught it because the stale notification fired and led to investigation.

The architectural fix is the dev-mode install path proposed in U-1: a single canonical install method during development would eliminate the drift class. A weaker fix is the `claude-usage-status` enhancement (S-7 + O-1) which surfaces drift after the fact.

---

## 5. Items verified as non-issues

Sanity-checked during this pass. Recorded so they don't surface again.

| Item | Verdict | Why |
|------|---------|-----|
| Tab-reuse path includes user's tab in `_scrape_tabs` storage | Non-issue | Verified: `_scrape_tabs` is only written inside the `if (scrapeTabId === null)` branch (background.js:309), so reused user-tab IDs never enter storage. The orphan-cleanup loop cannot close a user tab. |
| `_loadData` race between concurrent file-change events | Non-issue at current scale | `Gio.FileMonitorEvent.CHANGES_DONE_HINT` coalesces rapid writes; even if two `_loadData` callbacks fire close together, last-write-wins assignment to `this._data` is correct semantics for "latest cache contents." |
| `_iconNormal` / `_iconRed` GIcon refs leak on destroy | Non-issue | GIcon objects are reference-counted; `destroy()` releases its references implicitly when the wrapper is GCed. No manual unref needed in GJS. |
| `_clearingMetric` flag never reset across enable/disable | Non-issue | It's `this._clearingMetric` (instance attribute); a new `ClaudeIndicator` instance after disable/enable starts with the property undefined → falsy. |
| `_check_extension` parsing `gnome-extensions show` is locale-dependent | Non-issue | Pass 12 confirmed; the `State:` prefix is stable across locales because the field name is part of the API contract. |
| `_validate` accepts `_schema` from POSTs (could be poisoned) | Non-issue | Server unconditionally overwrites `body['_schema'] = CACHE_SCHEMA` at usage-server.py:285 after merge. Any POST-supplied value is clobbered. |
| `{'_timestamp': False}` validation passes but treated as missing | Non-issue (by design) | usage-server.py:151 `or` chain treats falsy as absent; line 250 `not body.get(...)` reassigns to `time.time()`. Test (`test_timestamp_rejects_bool_subclass`) documents this. The asymmetry with `True` (which IS rejected) is because `True` would propagate as `time.time() - True = epoch - 1` if accepted — `False` is safe because it never reaches downstream consumers. |
| Live-smoke `grep 'State: active\|State: lingering'` regex | Non-issue | Basic regex with `\|` works in BRE (default for grep without `-E`). Tested live: matches. |
| `scraper.js:64` `parseInt(pctMatch[1], 10)` could return NaN | Non-issue | The regex `^(\d+)%\s*used$` guarantees group 1 is `\d+`, so `parseInt` always returns a valid integer. `Math.min/max` then bounds it. No NaN path. |
| `release.yml:84` version extraction has wrong cwd | Non-issue | The `task release` workflow runs from the repo root by default (no `defaults.run.working-directory` change), so `packaging/control` is relative to `$GITHUB_WORKSPACE`. Verified by reading the yml. |
| `install.sh:96` glob suppression hides errors | Non-issue | Same comment as W‑1 in pass-12 review; the icons glob can validly be empty during dev, and the surrounding flow already validates that `extension.js` and `prefs.js` copied. |

---

## 6. Recommended action order

| # | Priority | Effort | Action |
|---|----------|--------|--------|
| 1 | High | XS | **Immediate fix for the live system:** rebuild + install the .deb (`task build && sudo dpkg -i dist/claude-usage_0.11.4_all.deb`), then reload at chrome://extensions. Clears U-1 immediately. |
| 2 | High | S | **U-1 long-term:** add `install.sh --dev` that symlinks source into the load-unpacked path, OR document the rebuild-+-reload-on-every-edit cycle in MANUAL.md. |
| 3 | High | S | **L-1:** add `_destroyed` flag guard to `_loadData` async callback (5 lines, mirrors the E-10 pattern). |
| 4 | Medium | XS | **N-1:** add `chrome.alarms.create` to the `onStartup` handler. 2 lines. |
| 5 | Medium | S | **D-2:** make the prefs.js subtitle resolve at runtime via the candidate-probe pattern. Mirror `ICON_SCRIPT` resolution. |
| 6 | Medium | S | **S-7:** treat absent `_ext_version` as old-version evidence in `claude-usage-status`. ~10 lines. |
| 7 | Medium | S | **A-2:** raise stale threshold to ~15 min (`2 × INTERVAL_MINUTES + 1`) AND only notify on broken-tier entry. |
| 8 | Medium | M | **O-1:** add Chrome orphan-extension detection to `claude-usage-status`. Reads Chrome's Preferences, enumerates Claude paths, checks existence. ~20 lines. |
| 9 | Low | XS | **N-3:** log the `tabs.query` swallow once per SW lifetime. |
| 10 | Low | S | **N-2:** add an in-source comment explaining why `tabs.onActivated` fires on every tab switch. |
| 11 | Low | M | **W-1:** debounce the scroll-event handler with a 100 ms GLib timeout. |
| 12 | Low | L | **T-5:** add fetch-orchestration tests with a minimal chrome.* API shim. ~150 lines for 5 tests. |

**The first three items together close the entire "live system is running stale code" failure class** that prompted this pass. Items 4–8 close adjacent diagnostic / lifecycle gaps. Items 9–12 are polish.

---

## Appendix A — Verification commands

Reproducible verification of the new findings:

```bash
# U-1: confirm Chrome's Preferences holds two Claude entries, only one valid
python3 -c "
import json
from pathlib import Path
p = json.load(open('/home/will/.config/google-chrome/Default/Preferences'))
for eid, e in p['extensions']['settings'].items():
    path = e.get('path', '')
    if 'claude-usage' in path:
        ok = Path(path).exists()
        print(f'  {eid[:8]}  path={path}  exists={ok}')
"

# U-1 + D-3: confirm cache shows pre-0.11.1 indicators
python3 -c "
import json
d = json.load(open('/home/will/.cache/claude-usage/usage.json'))
print('_ext_version:', d.get('_ext_version'))           # None → old ext
print('_schema:', d.get('_schema'))                     # None → old server merge
print('plan:', d.get('plan'))                           # 'Max plan' → pre-JS-6 scraper
"

# L-1: confirm absence of _destroyed flag guard
grep -n '_destroyed' gnome-extension/extension.js
# expect: empty (regression if it has any matches now)

# N-1: confirm onStartup lacks alarms.create
sed -n '/onStartup.addListener/,/^})/p' chrome-extension/background.js
# expect: only fetchUsage(), no chrome.alarms.create

# D-2: confirm prefs.js path is hardcoded
grep -n 'Load unpacked from' gnome-extension/prefs.js
# expect: literal "~/.local/share/claude-usage/chrome-extension/"

# S-7: confirm claude-usage-status doesn't handle the absent-_ext_version case
grep -A1 '_ext_version_mismatch' scripts/claude-usage-status.py
# expect: only the if-branch, no elif for "version is None but timestamp is fresh"

# A-2: confirm 10-min threshold
grep -n 'age > 10' gnome-extension/extension.js
# expect: line 378 — too tight for MV3 alarm jitter
```

---

## Appendix B — What this pass cost vs. what it caught

This pass took ~25 min of focused attention: one full read of each source file (with the prior reviews as ground-truth lookup), one runtime probe triggered by an actual live notification, one cross-component trace through Chrome's `Preferences` cache, and one comparison of `source-at-HEAD` against `running-on-this-machine`.

It produced **13 new findings**. Two are High (U-1, L-1). The High ones are the kind that show up as user-visible problems — U-1 already did, twice in this session. The five Mediums are split between new code (N-1) and diagnostic gaps (O-1, D-2, S-7, A-2).

The single biggest delta from pass 12: **letting the live system be the source of truth, not the source code.** Pass 12 verified pass-11 fixes against the running system field by field; it found that all fixes had landed. It did not check whether the *Chrome extension* the user reloads is the same code as the *Chrome extension* in the repo. That blind spot produced U-1. The next pass should ask: "what other paths between source and running do we not check?"

Two candidates for that next pass:
- **The GNOME extension reload story.** `gnome-extensions reload claude-usage@indri.studio` reads from `/usr/share/gnome-shell/extensions/` for .deb installs and from `~/.local/share/gnome-shell/extensions/` for source installs. Same trap class as U-1. Verify both paths.
- **Schema migration on cache version bumps.** A-1 added `_schema: 1` writes. The reader at extension.js:273 warns on mismatch. But what does it do if the cache holds `_schema: 0` (or absent) — does it parse fields that may have moved? The current cache shape is stable, but the moment someone bumps `_schema`, the reader needs an explicit migration step.
