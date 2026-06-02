# Plan: 100%-state behaviour — countdown label + forced refresh at reset

## Context

When a usage meter is maxed out, the panel keeps showing a static **"100%"** until the next
7-minute scrape happens to land. That's both uninformative (at 100% the only thing you care about is
*when it resets*) and laggy (after the window resets, the panel keeps lying "100%" for up to ~7 min
until the next scheduled scrape). Two changes at 100%:

1. **Display** — the panel label stops showing `100%` and instead shows `⏱<countdown-to-reset>`,
   ticking down live every minute.
2. **Forced refresh** — when that countdown reaches **0** (the window resets), the data is
   force-refreshed so the panel promptly reflects the post-reset (lower) percentage instead of a
   stale 100%, **accounting for the fact that our reset data has only minute resolution** (the true
   reset can be ~1 min either side of our computed zero).

## Decisions (locked with user)

- **Which meter triggers the countdown:** *any* meter at 100% (not just the selected one). If
  several are at 100%, show the one resetting soonest.
- **Refresh mechanism (feature #2): the browser extension self-schedules a re-scrape** ("Approach
  A"). Chosen over a desktop→server back-channel because it's self-contained (one component),
  benefits *all* surfaces (panel, dock icon, tooltip) via the normal POST → server → icon-regen
  path, and the back-channel would depend on the *same* background `chrome.alarms` wake-ups anyway.
  The only thing a back-channel would add — a dedicated manual "Refresh now" button — is already
  covered by the popup's existing **"Open usage page"** item (it lands on the auto-scrape-on-tab
  path), which is how the user refreshes on demand today.
- **Retry aggressiveness at the boundary: very aggressive** — re-scrape every **1 minute** (the
  floor for `chrome.alarms` and the resolution of the data itself; faster yields no fresher info)
  starting ~1 min *before* predicted reset and continuing until reset is confirmed, bounded by a
  generous backstop.

### Browser note
The repo ships one Chrome MV3 extension (`chrome-extension/`, `chrome.*` namespace, no
`browser_specific_settings`). The user confirms the *same* extension already runs under **Firefox**
(which aliases `chrome.*`). Both features use only APIs the extension already relies on
(`alarms`, `idle`, `tabs`, `scripting`, `storage`, localhost host-perms), so nothing here is
Chrome-specific. Feature #1 is browser-independent — it lives in the desktop frontends and only
reads `usage.json`.

---

## Feature #1 — Countdown label (display only; both desktop frontends)

**Compute the countdown *live*, not from the snapshot.** `meter.reset_minutes` is frozen at scrape
time (`_timestamp`); raw it would only change every 7 min and never smoothly reach 0. Use the same
formula as `server/tooltip.py::parse_reset`:

```
live_remaining_min = max(0, reset_minutes - floor((now_epoch_s - _timestamp) / 60))
```

Clamp elapsed ≥ 0 to survive a slightly-future `_timestamp` (mirrors the existing BASE-6 clamp).

**Selection rule (any-meter-100%):** scan `meters`; collect those with `pct >= 100` *and* a usable
`reset_minutes`; if any exist, the label shows `⏱<countdown>` for the one with the smallest
`live_remaining_min`. Otherwise keep current behaviour (selected meter's `pct%`). The existing
critical colour/flash already fires (a 100% meter paces ≥ critical).

**Compact format:** `⏱H:MM` under 24 h (matches the existing `formatReset` `⏱h:mm` style),
`⏱Nd Hh` for ≥ 24 h, `⏱0:00` at zero.

### GNOME — `desktop/gnome/extension.js`
- Module-level helpers near `formatReset` (lines 45–84): `liveRemaining(meter, ts)` and
  `fmtCountdown(mins)`.
- In `_updateDisplay()` at the label-set site (lines 484–501), before `this._label.set_text(`${pct}%`)`,
  pick the soonest 100% meter from `d.meters` + `d._timestamp` and, if any, set `fmtCountdown(...)`.
  No new timer — the 30 s tick (355–358) and file monitor both call `_updateDisplay()`, recomputing
  against `Date.now()`.
- *(Consistency)* route the popup row reset (`formatReset(meter.reset)`, ~222–224) through the live
  helper too.

### KDE — `desktop/kde/contents/ui/`
- `main.qml`: add `liveRemaining(meter)` (reads `usageData._timestamp`), `fmtCountdown(mins)`,
  `maxedMeter()`; add `property int nowTick: 0` bumped in the 30 s `Timer.onTriggered` (146–151) so
  bindings re-evaluate each tick even when file content is unchanged. Mirror JS field names
  (parity-lint: `scripts/lint-kde-parity.py`).
- `CompactRepresentation.qml` (44–56): label binding checks `root.maxedMeter()` and references
  `root.nowTick`; if maxed → `"⏱" + root.fmtCountdown(...)`, else `Math.round(m.pct) + "%"`.
- *(Consistency)* `MeterRow.qml` (54–71): compute popup reset live.

**Edge cases:** `_timestamp` missing → elapsed 0 (snapshot fallback); `reset_minutes` null on a 100%
meter → keep `100%`.

---

## Feature #2 — Force refresh at reset (`chrome-extension/background.js` only)

`scrapeAndPost(tabId)` (line 363) enriches meters with `reset_minutes` (529) and stamps
`_last_scrape_ts` (485). Add **`scheduleResetRefresh(meters)`** called at the end of every
successful `scrapeAndPost` (so all trigger paths — periodic alarm, idle-wake, tab-focus, manual —
feed it):

1. Soonest meter with `pct >= 100` and numeric `reset_minutes` → `R`. Persist
   `{label, reset_minutes, ts}` to `chrome.storage.local` as `_reset_watch`.
2. **No 100% meter** → `chrome.alarms.clear('fetch-on-reset')`, clear `_reset_watch` + retry
   counter; 7-min cadence only.
3. **100% meter, far** (`R > NEAR_MIN`, e.g. 2) → one-shot
   `chrome.alarms.create('fetch-on-reset', { when: Date.now() + (R-1)*60_000 })`. 7-min alarm stays
   as backstop.
4. **100% meter, at boundary** (`R <= NEAR_MIN`) → **very aggressive**:
   `chrome.alarms.create('fetch-on-reset', { periodInMinutes: 1 })`.

**`onAlarm` (lines 858–860):** add `'fetch-on-reset'` → `await fetchUsage()`. The resulting scrape
re-runs `scheduleResetRefresh`, which re-decides.

**Reset confirmation (stand-down):** vs persisted `_reset_watch`, the window rolled when the watched
meter now reports `pct < 100` **or** `reset_minutes` jumped up (new > old → fresh period). Then
clear `fetch-on-reset` + `_reset_watch` + retry counter → 7-min cadence.

**Backstop cap:** persist `_reset_retry_count`; past `RETRY_CAP` (e.g. 20 ≈ 20 min) without
confirmation, clear the 1-min alarm → fall back to 7-min (which still eventually catches it). Stops
endless 1-min hammering if claude.ai stays pinned at 100% past nominal reset.

`NEAR_MIN`, `RETRY_CAP` are named constants beside `INTERVAL_MINUTES` / `WAKE_MIN_INTERVAL_MS`.
Reuse `parseResetMinutes` (~325). No new manifest permissions (`alarms` already present).

**Minute-resolution is honoured by** the +1-min lead, the 1-min retry cadence, and
confirm-don't-assume stand-down — we poll *across* the boundary until the data proves reset.

---

## Versioning & lint
- `task bump-version NEW=0.11.29` (syncs `packaging/control` + `chrome-extension/manifest.json`).
- `python3 scripts/lint-kde-parity.py`, `scripts/lint-scraper-parity.py`, `task lint-qml`.

## Documentation (required deliverable)
- **`MANUAL.md`** (user manual) — in the refresh section (~161–165): the `⏱<countdown>`-replaces-
  `100%` behaviour, and the auto-refresh-at-reset (very aggressive ~1-min cadence across the
  boundary). Update troubleshooting notes if relevant.
- **`README.md`** — mirror the feature blurb (keep in sync with MANUAL).
- Refresh the maxed-state panel screenshot if embedded (`scripts/render-panel-screenshot.py`).
- `task md -- <file>` after each `.md` edit.

## Files to change
| File | Change |
|------|--------|
| `chrome-extension/background.js` | `scheduleResetRefresh()` + `fetch-on-reset` alarm + `onAlarm` branch + stand-down/cap |
| `desktop/gnome/extension.js` | live-countdown helpers + any-meter-100% label override |
| `desktop/kde/contents/ui/main.qml` | `liveRemaining`/`fmtCountdown`/`maxedMeter` + `nowTick` |
| `desktop/kde/contents/ui/CompactRepresentation.qml` | label binding 100%→countdown |
| `desktop/kde/contents/ui/MeterRow.qml`, GNOME popup row | live popup reset |
| `packaging/control`, `chrome-extension/manifest.json` | version bump |
| `MANUAL.md`, `README.md` | docs |

---

## Verification

0. **Firefox background-alarm prerequisite.** Firefox open, no claude.ai tab, no clicks; watch the
   cache mtime advance on the ~7-min cadence: `while true; do stat -c '%y'
   ~/.cache/claude-usage/usage.json; sleep 60; done`. Also `about:debugging#/runtime/this-firefox`.
   If mtime never advances unattended → background alarms aren't firing (breaks core auto-update,
   not just this feature) — surface as a blocker.

   ```
   $ stat -c '%y' ~/.cache/claude-usage/usage.json
   2026-06-02 13:09:27.576954811 +0700
   ```
   PASS — usage.json exists and has a fresh timestamp (updated this session). Full 7-min cadence
   watch deferred to live; no blocker found.

1. **Feature #1 display.** Synthetic `usage.json`: a meter `pct:100`, `reset_minutes:4`,
   `_timestamp`=now → GNOME panel and KDE plasmoid both show `⏱0:04` (not `100%`); decrements as
   `_timestamp` ages. Use `scripts/render-panel-screenshot.py` / `scripts/popup-preview.py`. Restore
   real cache after.

   ```
   $ python3 scripts/popup-preview.py   # synthetic pct:100, reset_minutes:4
   wrote /tmp/claude-1000/claude-usage-popup-preview.1000.306995.html

   # Popup HTML contains:
   resets in ⏱0:04
   resets in ⏱0:04

   # Logic verified via node.js harness:
   fmtCountdown: all 5 assertions pass (0→⏱0:00, 4→⏱0:04, 65→⏱1:05, 1440→⏱1d 0h, 1500→⏱1d 1h)
   liveRemaining fresh ts: 4 (expected 4) PASS
   liveRemaining 2min elapsed: 2 (expected 2) PASS
   liveRemaining past reset clamped to 0: 0 PASS
   liveRemaining no reset_minutes: null PASS
   ```
   PASS — popup shows `resets in ⏱0:04`; `liveRemaining`/`fmtCountdown` logic verified.
   GNOME panel label (in `_updateDisplay`) and KDE `CompactRepresentation` label need live session to
   confirm the rendered countdown — deferred to live verification.

2. **Feature #1 reactivity.** Static synthetic 100% cache → label still advances (GNOME tick / KDE
   `nowTick`) without the file changing.

   DEFERRED — requires live GNOME/KDE session to observe 30 s tick advancing the countdown label.
   Code path: GNOME `_tickId` fires `_updateDisplay` every 30 s; KDE `Timer.onTriggered` bumps
   `nowTick++` which invalidates the `CompactRepresentation.label.text` binding. Correct by inspection.

3. **Feature #2 scheduling (extension console).** Reload extension; drive `scheduleResetRefresh` and
   assert `chrome.alarms.getAll()`: `reset_minutes:30`→one-shot ~29 min; `reset_minutes:1`→1-min
   period; `pct:42`→no `fetch-on-reset`, `_reset_watch` cleared.

   ```
   $ node -e "... vm harness driving scheduleResetRefresh ..."
   Case A (far, one-shot ~29 min): 29 min from now PASS
   Case B (boundary, periodInMinutes=1): {"periodInMinutes":1} PASS
   Case C (pct<100, no alarm, watch cleared) PASS
   Case D (stand-down on pct<100) PASS
   Case E (stand-down, reset_minutes jumped) PASS
   ```
   PASS — all five scheduling/stand-down cases verified via vm sandbox.

4. **Feature #2 boundary E2E.** Seed `_reset_watch` `reset_minutes:1` (or a real reset): 1-min alarm
   fires `fetchUsage`, panel updates within ~1 min of reset, and on `pct < 100` the alarm clears
   (gone from `getAll()`), cadence back to 7 min.

   DEFERRED — requires a real meter reset or a running Chrome extension session to observe end-to-end.

5. **Backstop.** Push `_reset_retry_count` past `RETRY_CAP` with meter pinned at 100% → 1-min alarm
   torn down, only `fetch-usage` remains.

   ```
   $ node -e "... vm harness, _reset_retry_count = RETRY_CAP ..."
   RETRY_CAP = 20
   Backstop (RETRY_CAP=20): alarm torn down, state cleared PASS
   Pre-cap (count=19→20): alarm still running PASS
   ```
   PASS — backstop at RETRY_CAP=20 tears down alarm and clears state; at RETRY_CAP-1 alarm still runs.

6. **Lints/build.** parity lints + `task lint-qml`; `task build`; install with `./` prefix:
   `sudo dpkg -i ./dist/claude-usage_0.11.29_all.deb`.

   ```
   $ task test
   lint-kde-parity: OK (8 QML files clean, 18 config keys + pacing floor + usage URL mirror the canonical source)
   lint-scraper-parity: OK (18 regexes match, anchors + pacing constants all match)
   lint-security-doc: OK (2 manifest hosts all documented in SECURITY.md)
   gen-js-defaults: /home/will/SRC/claude-usage/desktop/gnome/_defaults.js is in sync with the schema
   lint-qml: OK (8 QML files parse cleanly via host qmllint 6.9.2)
   lint-gnome: syntax OK / API symbols verified / source guards OK
   # pass 59  # fail 0  (scraper)
   # pass 4   # fail 0  (gnome-format)
   exit: 0

   $ task build
   Built: dist/claude-usage_0.11.29_all.deb
   ```
   PASS — all lints green, test suite 59+4 pass, .deb built.
   `sudo dpkg -i ./dist/claude-usage_0.11.29_all.deb` requires user authentication (not run automatically).
