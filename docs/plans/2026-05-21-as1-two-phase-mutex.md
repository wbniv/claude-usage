# AS-1 — two-phase mutex for `_autoScrapeIfEligible`

**Origin**: [pass-26 code review](../investigations/2026-05-20-code-review-pass26.md) AS-1.
**Status**: implementation.

## Problem

`background.js:676` — `_autoScrapeIfEligible` seizes `_fetching = true` synchronously *before* the `chrome.storage.local.get` that drives the eligibility check (debounce window, own-scrape-tab guard). When eligibility fails (the common case during SPA navigation churn) the mutex is released ~10–50 ms later — but any alarm-fired `fetchUsage()` arriving in that window sees `_fetching === true` and bails silently. Next alarm tick: 7 min. Cost when triggered: the GNOME panel sits at BROKEN tier for up to one 7-min cycle.

## The design tension

Pass-16 R-1 moved `_fetching = true` to *before* the storage.get specifically to prevent two near-simultaneous events both passing `if (_fetching) return` and both proceeding to scrape concurrently. R-1's constraint is real: a naïve fix to AS-1 (move the check before the mutex) reverts R-1.

## Approach — two-phase mutex

Split the single `_fetching` flag into two:

- **`_evaluating`** — held only during the eligibility-check phase (URL filter + storage.get + the post-storage predicates). Blocks concurrent `_autoScrapeIfEligible` invocations from racing through the storage.get, which was R-1's original concern. Crucially, `fetchUsage` does **not** check this flag.
- **`_fetching`** — unchanged in meaning: held only during the actual `scrapeAndPost` call. Both `_autoScrapeIfEligible` and `fetchUsage` check it.

Result: alarm-fired `fetchUsage` is no longer starved by an in-progress eligibility check that is about to bail.

```js
let _evaluating = false;
let _fetching = false;

async function _autoScrapeIfEligible(tabId, url) {
  if (url.split(/[?#]/, 1)[0] !== USAGE_URL) return;
  if (_evaluating || _fetching) return;
  _evaluating = true;
  try {
    const { _scrape_tabs = [], _last_scrape_ts = 0 } =
        await chrome.storage.local.get(['_scrape_tabs', '_last_scrape_ts']);
    if (_scrape_tabs.includes(tabId)) return;
    if (Date.now() - _last_scrape_ts < AUTO_DEBOUNCE_MS) return;
    if (_fetching) return;               // alarm beat us in
    _fetching = true;
  } finally {
    _evaluating = false;
  }
  try { await scrapeAndPost(tabId); }
  catch (e) { console.warn('Claude Usage auto-scrape failed:', e.message); }
  finally { _fetching = false; }
}
```

### Correctness trace

| Scenario | Behaviour |
|---|---|
| Two SPA-nav events arrive ~simultaneously | A acquires `_evaluating`; B sees `_evaluating=true` and returns. R-1 invariant preserved. |
| Alarm fires during A's eligibility check | `fetchUsage` checks only `_fetching` (false) → proceeds → sets `_fetching=true` → scrapes. AS-1 starvation eliminated. |
| A finishes eligibility, finds `_fetching=true` (from concurrent alarm) | A returns; alarm's scrape runs to completion. No double-scrape. |
| Alarm currently scraping, event arrives | Event sees `_fetching=true` → returns early at the entry guard. |
| Event currently in eligibility, alarm arrives | Alarm proceeds; event eventually sees `_fetching=true` post-storage and returns. |

### Why not option 1 (in-memory `_lastScrapeTs` cache)?

Considered and rejected — see the conversation transcript. Option 1 (cache `_last_scrape_ts` in a module-level `let`, eliminate the storage.get from the hot path) has a cold-start prime window where the in-memory value is stale, and only fixes AS-1 for the debounce path (the `_scrape_tabs` check remains storage-backed and inside the mutex). Two-phase mutex fixes both paths and keeps storage as single source of truth.

## Changes

1. `chrome-extension/background.js`
   - Add `let _evaluating = false;` next to `let _fetching = false;` (top-level, above setActionStatus per AR-2's TDZ guard).
   - Rewrite `_autoScrapeIfEligible` to the two-phase structure above.
   - Add an AS-1 reference comment block explaining the two-flag contract and naming the three constraints.

2. `TODO.md` — move AS-1 from Deferred → Done.

No changes to scraper.js, no new tests, no Taskfile edit.

## Regression test — explicit decision NOT to add

A behavioural test would require either exposing `_evaluating`/`_fetching` via a debug hook (background.js is loaded as a classic script — `let` declarations are not accessible from the vm-sandbox host) or rewriting the function in a testable shape. Both costs exceed the fix.

A source-shape lint (assert `_fetching = true` appears AFTER `chrome.storage.local.get(` in the `_autoScrapeIfEligible` body) is feasible but brittle to formatting and would be the only such introspection lint in the repo. Skipped.

Mitigation: the design contract is documented inline in the function header. The two-phase structure is visually unmissable in code review.

## Verification

1. Existing background load-time test:
   ```
   node --test chrome-extension/test/background-load.test.js
   ```
   ```
   ✔ loads without throwing — TDZ + top-level call safety (AR-2 regression guard) (55.848905ms)
   ✔ background.js — load-time invariants (56.695484ms)
   ℹ tests 1; pass 1; fail 0
   ```
   PASS.

2. Existing scraper tests:
   ```
   node --test chrome-extension/test/scraper.test.js
   ```
   ```
   ℹ fail 0; cancelled 0; skipped 0; todo 0
   ```
   PASS.

3. All lints:
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

4. Manual trace of the function vs. the correctness table above. Reviewed by walking each of the five scenarios against the post-edit source; all transitions match the table. PASS.

## Risk

Low. The change touches one async function. The two-phase structure is mechanical, the constraints are local, and the existing R-1 and AS-1 references in the surrounding comments document both invariants. Worst case: a subtle ordering bug — caught by the existing R-1 (concurrent-scrape) and AS-1 (alarm-starvation) failure modes, both of which produce observable diagnostics (the GNOME panel goes BROKEN, or duplicate POSTs in journal).
