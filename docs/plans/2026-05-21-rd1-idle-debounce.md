# RD-1 — debounce `chrome.idle.onStateChanged` 'active'

**Origin**: [pass-26 code review](../investigations/2026-05-20-code-review-pass26.md) RD-1.
**Status**: implementation.

## Problem

`chrome-extension/background.js:780-784`. The idle handler is correct in intent (pass-17 CI-2: `chrome.alarms` does not catch up after suspend, so wake-from-suspend must trigger an immediate scrape or the GNOME panel sits at BROKEN tier for up to 7 min). But `chrome.idle.onStateChanged` fires `'active'` on *every* return-to-active transition, not just wake-from-suspend:

- screen unlock after lockscreen
- screensaver dim → mouse-jiggle
- monitor power-save → keypress

Each fire goes straight to `fetchUsage()` with no debounce. SPA-navigation paths funnel through `AUTO_DEBOUNCE_MS = 30_000`; this path doesn't. Cost: one claude.ai page-load + one Statuspage hit per lock/unlock cycle.

## Design call — `WAKE_MIN_INTERVAL_MS`

Chosen value: **`INTERVAL_MINUTES * 60 * 1000`** (7 min, matching the alarm period).

The handler exists *only* to fill in for missed alarm periods. Debouncing at less than the alarm period over-corrects (fires when the next alarm would have fired anyway). Debouncing at more than the alarm period leaves a stale-panel window the alarm could have closed. Equal-to-period is the principled value — it means "fire on wake only if the last successful scrape is older than the alarm would have scheduled."

Trade-offs considered:

| Value | Suppresses lock/unlock noise? | Stale-panel window after wake | Verdict |
|---|---|---|---|
| 30 s (= AUTO_DEBOUNCE_MS) | barely | 0 s | overcorrects almost nothing |
| 5 min | yes (rapid cycles) | up to 12 min (5 + 7) | works, but asymmetric with alarm period |
| **7 min (= INTERVAL_MINUTES)** | **yes** | **up to 7 min** | **principled — debounces at exactly the alarm cadence** |
| 15 min | yes (everything short) | up to 22 min | needlessly long for the lunch-break / pee-break case |

## Changes

1. `chrome-extension/background.js`
   - Add `const WAKE_MIN_INTERVAL_MS = INTERVAL_MINUTES * 60 * 1000;` next to the other top-level interval constants.
   - Rewrite the `chrome.idle.onStateChanged` handler to read `_last_scrape_ts` from storage and bail if within the debounce window.

2. `TODO.md` — move RD-1 from Deferred → Done.

No scraper.js changes, no test changes, no Taskfile edit.

## Implementation

```js
const WAKE_MIN_INTERVAL_MS = INTERVAL_MINUTES * 60 * 1000;
...
if (chrome.idle && chrome.idle.onStateChanged) {
  chrome.idle.onStateChanged.addListener(async state => {
    if (state !== 'active') return;
    // RD-1 (pass-26 deferred → pass-29): debounce against the last
    // successful scrape so lockscreen unlock / screensaver dim cycles
    // don't burn a claude.ai page-load each. Equal to INTERVAL_MINUTES
    // means "only fire if the alarm would have been overdue anyway"
    // — preserves CI-2's wake-from-suspend purpose without spamming.
    try {
      const { _last_scrape_ts = 0 } =
          await chrome.storage.local.get('_last_scrape_ts');
      if (Date.now() - _last_scrape_ts < WAKE_MIN_INTERVAL_MS) return;
    } catch (_) { /* fall through to fire */ }
    fetchUsage();
  });
}
```

Storage read errors fall through to fire — preserves CI-2's "wake from suspend always works even when storage is wedged" invariant.

## Regression test — explicit decision NOT to add

Testing this requires either: (a) exposing the idle listener from a vm-sandboxed background.js for direct invocation (same MV3-classic-script + `let`-scoping problem as AS-1's deferred test), or (b) a source-shape lint asserting the handler awaits storage before calling fetchUsage. Both cost more than the fix.

Mitigation: the design contract is documented inline; the debounce is a single linear control flow visible in the handler.

## Verification

1. Background load-time test still passes:
   ```
   node --test chrome-extension/test/background-load.test.js
   ```
   ```
   ℹ pass 1; fail 0
   ```
   PASS.

2. Scraper tests still pass:
   ```
   node --test chrome-extension/test/scraper.test.js
   ```
   ```
   ℹ pass 50; fail 0
   ```
   PASS.

3. All lints pass:
   ```
   python3 scripts/lint-scraper-parity.py ; echo exit=$?
   ```
   ```
   lint-scraper-parity: OK (18 regexes match between scraper.js and background.js inline)
   lint-anchor-strings: OK (2 anchors + 1 selectors present)
   lint-pacing-parity: OK (3 literals match between pacingPct and pacing_pct)
   lint-pacing-parity: OK (2 literals match between elapsedFraction and elapsed_fraction)
   lint-pacing-parity: OK (9 literals match between pacingSegments and pacing_segments)
   lint-pacing-parity: OK (5 literals match between colorFor and color_for)
   lint-pair-inventory: OK (no unregistered JS↔Python pairs detected)
   exit=0
   ```
   PASS.

## Risk

Minimal. Single async listener body, no shared-state changes, falls open on storage error.
