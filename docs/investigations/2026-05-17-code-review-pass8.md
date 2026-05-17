# Code Review — Pass 8

**Date:** 2026-05-17  
**Scope:** Full codebase — GNOME extension, Chrome extension, Python server, packaging, CI  
**Reviewer:** Claude (automated multi-agent pass)  
**Prerequisite:** See [docs/wont-fix.md](../wont-fix.md) — items there are NOT re-raised.

---

## Summary

| ID | Severity | Subsystem | Title |
|----|----------|-----------|-------|
| ~~P8‑1~~ | ~~Critical~~ | ~~GNOME ext~~ | ~~Menu `open-state-changed` signal never disconnected~~ |
| ~~P8‑2~~ | ~~Critical~~ | ~~Chrome ext~~ | ~~Alarm handler not async — MV3 SW can be killed mid-scrape~~ |
| ~~P8‑3~~ | ~~Critical~~ | ~~Chrome ext~~ | ~~Click handler not async — same issue~~ |
| ~~P8‑4~~ | ~~High~~ | ~~GNOME ext~~ | ~~Scroll returns `EVENT_STOP` unconditionally~~ |
| ~~P8‑5~~ | ~~High~~ | ~~GNOME ext~~ | ~~Scroll idx=−1 when `panel-metric` not in eligible list~~ |
| ~~P8‑6~~ | ~~High~~ | ~~Python server~~ | ~~Icon-path race: tick overwrites `generate-icon.py`'s `Icon=` update~~ |
| ~~P8‑7~~ | ~~Medium~~ | ~~GNOME ext~~ | ~~`bar()` overflows when pct > 100~~ |
| ~~P8‑8~~ | ~~Medium~~ | ~~Chrome ext~~ | ~~Offline-buffered data never ages out~~ |
| ~~P8‑9~~ | ~~Medium~~ | ~~Chrome ext~~ | ~~`parseResetMinutes` hour/minute range not validated~~ |
| ~~P8‑10~~ | ~~Medium~~ | ~~Python server~~ | ~~`_anthropic_status.indicator` not whitelisted~~ |
| ~~P8‑11~~ | ~~Medium~~ | ~~Python server~~ | ~~JSON / unicode / memory errors all return 400~~ |
| ~~P8‑12~~ | ~~Low~~ | ~~Chrome ext~~ | ~~`innerText` triggers layout recalculation~~ |
| ~~P8‑13~~ | ~~Low~~ | ~~Chrome ext~~ | ~~3 s scrape delay unexplained~~ |
| ~~P8‑14~~ | ~~Low~~ | ~~Python server~~ | ~~Silent degradation when `generate-icon.py` not found~~ |
| ~~P8‑15~~ | ~~Low~~ | ~~CI~~ | ~~`VERSION` extracted twice in `release.yml`~~ |
| ~~P8‑16~~ | ~~Nitpick~~ | ~~GNOME ext~~ | ~~`critMeter?.label` optional chaining redundant~~ |
| ~~P8‑17~~ | ~~Nitpick~~ | ~~GNOME ext~~ | ~~`pacingPct(critMeter, …)` computed twice~~ |
| ~~P8‑18~~ | ~~Nitpick~~ | ~~Python server~~ | ~~`generate-icon.py --tier` arg access without length guard~~ |
| ~~P8‑19~~ | ~~Nitpick~~ | ~~GNOME ext~~ | ~~`formatReset()` missing `typeof` type guard~~ |

---

## Critical

### P8‑1 — Menu `open-state-changed` signal never disconnected

**File:** `gnome-extension/extension.js:169`

```javascript
this.menu.connect('open-state-changed', (_menu, open) => {
    if (open) {
        this._stopFlash();
        this._flashSuppressed = true;
    }
});
```

`this.menu.connect()` returns a signal ID that is never stored. `destroy()` (lines 438–455) disconnects `_settingsId` from `this._settings`, removes timers, and calls `super.destroy()` — but never disconnects the menu signal. `super.destroy()` tears down `this` (the panel button actor), not `this.menu`. The `PopupMenu` object outlives the actor in some code paths, leaving a handler connected to a destroyed object.

**Fix:**
```javascript
// in _init():
this._menuOpenId = this.menu.connect('open-state-changed', (_menu, open) => { … });

// in destroy():
if (this._menuOpenId) {
    this.menu.disconnect(this._menuOpenId);
    this._menuOpenId = null;
}
```

---

### P8‑2 — Alarm handler not async (MV3 service worker lifecycle)

**File:** `chrome-extension/background.js:360–362`

```javascript
chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === 'fetch-usage') fetchUsage();   // Promise discarded
});
```

MV3 service workers are suspended once the synchronous event handler returns. `fetchUsage()` returns a Promise that the runtime has no handle on, so the SW can be terminated before any `await` inside `fetchUsage()` resumes. Every periodic scrape is at risk of being cut off mid-flight.

**Fix:**
```javascript
chrome.alarms.onAlarm.addListener(async alarm => {
    if (alarm.name === 'fetch-usage') await fetchUsage();
});
```

---

### P8‑3 — Click handler not async (MV3 service worker lifecycle)

**File:** `chrome-extension/background.js:364`

```javascript
chrome.action.onClicked.addListener(() => fetchUsage());
```

Same issue as P8‑2. The listener is synchronous; the returned Promise is discarded.

**Fix:**
```javascript
chrome.action.onClicked.addListener(async () => { await fetchUsage(); });
```

---

## High

### P8‑4 — Scroll returns `EVENT_STOP` unconditionally

**File:** `gnome-extension/extension.js:118–131`

```javascript
this.connect('scroll-event', (_actor, event) => {
    const dir = event.get_scroll_direction();
    if ((dir === Clutter.ScrollDirection.UP ||
         dir === Clutter.ScrollDirection.DOWN) && this._data) {
        // ... metric switching ...
    }
    return Clutter.EVENT_STOP;   // ← always, even when nothing was done
});
```

When `this._data` is null (server not yet reached) or the scroll direction is left/right, the condition is false and the scroll is silently consumed. Any parent widgets or GNOME Shell's own panel scroll handling never sees the event.

**Fix:** Return `Clutter.EVENT_PROPAGATE` when the condition isn't met:
```javascript
    if ((dir === Clutter.ScrollDirection.UP ||
         dir === Clutter.ScrollDirection.DOWN) && this._data) {
        // ... metric switching ...
        return Clutter.EVENT_STOP;
    }
    return Clutter.EVENT_PROPAGATE;
```

---

### P8‑5 — Scroll wrap breaks when `panel-metric` not in eligible list

**File:** `gnome-extension/extension.js:124–128`

```javascript
const cur  = this._settings.get_string('panel-metric');
const idx  = eligible.findIndex(m => m.label === cur);
const delta = dir === Clutter.ScrollDirection.UP ? -1 : 1;
const next = eligible[(idx + delta + eligible.length) % eligible.length];
```

If `cur` isn't found (fresh install with default value, meter removed mid-session, label rename), `idx = −1`. With `delta = −1`:
`(−1 − 1 + N) % N = (N−2) % N` — skips to the second-to-last meter instead of the last. The behaviour is deterministic but wrong.

**Fix:**
```javascript
let idx = eligible.findIndex(m => m.label === cur);
if (idx === -1) idx = 0;
```

---

### P8‑6 — Icon-path race: tick overwrites `generate-icon.py`'s `Icon=` update

**File:** `server/tooltip.py:92–124`, `server/usage_server.py:~220`

The 60 s tick calls `update_desktop(meters, icon_path=None)`. With `icon_path=None`, `update_desktop` preserves the existing `Icon=` line by reading the `.desktop` file, processing it, and doing an atomic `tmp.replace(DESKTOP)`. `generate-icon.py` follows the same pattern but passes a fresh timestamped path.

Race:
1. Tick **reads** DESKTOP → sees `Icon=/cache/icon-T1-none.png`
2. `generate-icon.py` writes DESKTOP → `Icon=/cache/icon-T2-none.png`, deletes `T1` icon
3. Tick **writes** DESKTOP → restores `Icon=/cache/icon-T1-none.png` (now deleted)

GNOME Shell then tries to load a deleted file; the launcher shows no icon until the next generate-icon invocation overwrites it again (up to 15 min if no POST arrives).

**Fix options:**
- Have the tick skip `update_desktop` entirely when `icon_path is None` and only the `Name=` line changed — read-modify-write only the `Name=` field using a targeted `sed`-style replace rather than a full file rewrite.
- Or: add a per-file advisory lock (e.g. `fcntl.flock`) shared between the tick and `generate-icon.py`.

The targeted-replace approach is simplest:
```python
def _update_name_only(name):
    if not DESKTOP.exists():
        return
    text = DESKTOP.read_text()
    new_text = re.sub(r'^Name=.*$', f'Name={name}', text, flags=re.MULTILINE)
    if new_text == text:
        return
    tmp = DESKTOP.with_suffix(f'.desktop.tmp.{os.getpid()}.{time.time_ns()}')
    tmp.write_text(new_text)
    tmp.replace(DESKTOP)
```

---

## Medium

### P8‑7 — `bar()` overflows bar width when pct > 100

**File:** `gnome-extension/extension.js:47–50`

```javascript
function bar(pct, width = 10) {
    const filled = Math.round((pct / 100) * width);
    return '█'.repeat(Math.max(0, filled)) + '░'.repeat(Math.max(0, width - filled));
}
```

`pct = 110, width = 10` → `filled = 11` → bar is 11 chars wide, not 10. `Math.max(0, 10−11) = 0` empty chars, so the total is 11 blocks. The popup row becomes one character wider than all other rows, breaking column alignment.

The server caps pct at reasonable values in validation, but an overrun in pacing math (`pacingPct()` can return values well above 100 when `fraction` is small) feeds back into `bar()` via `pctColor` and popup rendering.

**Fix:**
```javascript
function bar(pct, width = 10) {
    const filled = Math.max(0, Math.min(width, Math.round((pct / 100) * width)));
    return '█'.repeat(filled) + '░'.repeat(width - filled);
}
```

---

### P8‑8 — Offline-buffered data never ages out

**File:** `chrome-extension/background.js:237–254`

```javascript
const r = await fetch(LOCAL_SERVER, { method: 'POST', body: JSON.stringify(buffered) });
if (r.ok) {
    await chrome.storage.local.remove('claude_usage');
} else if (r.status >= 400 && r.status < 500) {
    await chrome.storage.local.remove('claude_usage');   // malformed — discard
}
// No else: 5xx or network error → data remains in storage forever
```

If the server is persistently returning 5xx or unreachable, the buffered payload accumulates across scrapes (each `fetchUsage` sets `claude_usage` again on line 216). There is no expiry; the storage can hold arbitrarily old data. On a first-boot after a long outage, the server receives a flush of weeks-old scrape data.

**Fix:** Add a timestamp to the buffered payload and discard it if older than e.g. 24 h:
```javascript
await chrome.storage.local.set({ claude_usage: { ...data, _buffered_at: Date.now() } });
// … in the flush path:
if (Date.now() - (buffered._buffered_at || 0) > 86_400_000) {
    await chrome.storage.local.remove('claude_usage');
    return;
}
```

---

### P8‑9 — `parseResetMinutes` hour/minute range not validated

**File:** `chrome-extension/background.js:55–72`

```javascript
let h = parseInt(hStr), mn = parseInt(mnStr);
if (ap === 'PM' && h !== 12) h += 12;
else if (ap === 'AM' && h === 12) h = 0;
```

If the DOM produces malformed text like `"Resets Tue 25:99 PM"`, `parseInt` succeeds: `h = 37`, `mn = 99`. The subsequent `Date`/minutes arithmetic returns a nonsensical offset that propagates into the reset countdown display.

**Fix:** Add range guards before the AM/PM adjustment:
```javascript
let h = parseInt(hStr), mn = parseInt(mnStr);
if (h < 1 || h > 12 || mn < 0 || mn > 59) return null;
if (ap === 'PM' && h !== 12) h += 12;
else if (ap === 'AM' && h === 12) h = 0;
```

---

### P8‑10 — `_anthropic_status.indicator` missing whitelist

**File:** `server/usage_server.py` (validation section)

The POST handler validates `_anthropic_status` structure and string length but accepts any string for `indicator`. In `generate-icon.py`, `derive_tier()` treats any non-None, non-`'none'` indicator as `'broken'`. A POST from a misbehaving client sending `indicator: "some_typo"` would permanently display the broken-tier icon until the next real scrape clears it.

**Fix:** Add to `_validate()`:
```python
VALID_INDICATORS = (None, 'none', 'minor', 'major', 'critical', 'maintenance')
if astat.get('indicator') not in VALID_INDICATORS:
    return f"invalid indicator: {astat['indicator']!r}"
```

---

### P8‑11 — JSON / unicode / memory errors all return 400

**File:** `server/usage_server.py:~140–145`

`json.loads(body)` can raise `json.JSONDecodeError` (malformed JSON — client error), `UnicodeDecodeError` (invalid UTF-8 in request body — client error), or `MemoryError` / `OverflowError` (very large payload — server-side resource pressure). All three reach the generic `except Exception` handler and return 400 with `"Error: {e}"`. A memory pressure event is silently classified as a client error and swallowed at severity `print`.

**Fix:**
```python
try:
    data = json.loads(body)
except (json.JSONDecodeError, UnicodeDecodeError) as e:
    self._respond(400, f"bad request: {e}")
    return
except Exception as e:
    print(f"error parsing body: {e}", file=sys.stderr, flush=True)
    self._respond(500, "internal error")
    return
```

---

## Low

### P8‑12 — `innerText` triggers layout recalculation

**File:** `chrome-extension/background.js:89`

```javascript
const body = document.body.innerText;
```

`innerText` forces a synchronous layout pass (it needs to know which text is rendered and visible). `textContent` returns the raw DOM text without triggering layout, is faster, and returns equivalent data for this scraper since the usage page doesn't hide text via CSS visibility tricks.

**Fix:** `const body = document.body.textContent;`

---

### P8‑13 — 3 s scrape delay unexplained

**File:** `chrome-extension/background.js:84`

```javascript
await new Promise(r => setTimeout(r, 3000));
```

No comment explains why 3 seconds. A future maintainer touching the scraper timing has no signal for whether this is a React hydration wait, a server render delay, or a conservative guess.

**Fix:** Add a comment:
```javascript
// Wait for React to hydrate the usage meters after navigation completes.
await new Promise(r => setTimeout(r, 3000));
```

---

### P8‑14 — Silent degradation when `generate-icon.py` not found

**File:** `server/usage_server.py:~16–22`

`GENERATE_ICON` is set to `None` if neither candidate path exists. The POST handler checks `if GENERATE_ICON:` before spawning, silently skipping icon updates. There is no log at startup or at POST time to tell an admin why the dock icon is frozen.

**Fix:** Log once at startup:
```python
if GENERATE_ICON is None:
    print("warning: generate-icon.py not found; dock icon updates disabled", file=sys.stderr, flush=True)
```

---

### P8‑15 — `VERSION` extracted twice in `release.yml`

**File:** `.github/workflows/release.yml`

The same `grep '^Version:' packaging/control | awk '{print $2}'` command appears in two separate steps. A mismatch between the two isn't possible today (same file, same run), but it's noise.

**Fix:** Extract once into a step output and reference `${{ steps.version.outputs.version }}`.

---

## Nitpick

### P8‑16 — `critMeter?.label` optional chaining redundant

**File:** `gnome-extension/extension.js:292`

```javascript
const critMeter = d.meters.find(m => pacingPct(m, periodLens) >= tCrit);
Main.notify('Claude Usage',
    `⚠ ${critMeter?.label ?? 'A meter'} is at ${Math.round(pacingPct(critMeter, periodLens))}% pacing`);
```

This block is guarded by `if (anyCrit)` where `anyCrit = d.meters.some(m => pacingPct(m, periodLens) >= tCrit)` on the same array. JS is single-threaded; `find()` is guaranteed to return a non-undefined value. The `?.` and `?? 'A meter'` are dead code. Remove for clarity.

---

### P8‑17 — `pacingPct(critMeter, …)` computed twice

**File:** `gnome-extension/extension.js:291–293`

`pacingPct(critMeter, periodLens)` is called in the `find()` predicate (once per meter) and again in the `Math.round()` call. Store the result from find:

```javascript
let critPacing = 0;
const critMeter = d.meters.find(m => {
    const p = pacingPct(m, periodLens);
    if (p >= tCrit) { critPacing = p; return true; }
    return false;
});
if (critMeter)
    Main.notify('Claude Usage', `⚠ ${critMeter.label} is at ${Math.round(critPacing)}% pacing`);
```

---

### P8‑18 — `generate-icon.py --tier` arg access without length guard

**File:** `server/generate-icon.py:~250–255`

```python
if len(sys.argv) >= 2 and sys.argv[1] == '--tier':
    tier_override = sys.argv[2]   # IndexError if invoked as: generate-icon.py --tier
```

If called with `--tier` and no value, `sys.argv[2]` raises `IndexError`, caught by the outer handler and logged generically. Add:
```python
if len(sys.argv) >= 3 and sys.argv[1] == '--tier':
    tier_override = sys.argv[2]
```

---

### P8‑19 — `formatReset()` missing `typeof` type guard

**File:** `gnome-extension/extension.js:15`

```javascript
function formatReset(reset) {
    if (!reset) return '';
```

`!reset` catches `null`, `undefined`, and `''`, but not `0` or a non-string object. If the server or a future code path passes a number or object, `.match()` will throw a TypeError. Add `typeof reset !== 'string'` to the guard:
```javascript
if (!reset || typeof reset !== 'string') return '';
```

---

## Items NOT Raised (already closed)

See [docs/wont-fix.md](../wont-fix.md) for: BUG‑4, BUG‑5, BUG‑6, CQ6‑5 (moot), CQ6‑6, CQ6‑7, CQ8 (fixed).
