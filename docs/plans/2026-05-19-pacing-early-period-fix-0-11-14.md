# 2026-05-19 — Pacing early-period false-critical fix → 0.11.14

## Symptom

Within ~5–10 min of a session reset, a single Opus turn (3 % `Current session` usage at minute 6 of a 295 min period) flipped the GNOME panel label red. The popup and cache showed a healthy scrape; nothing was actually wrong.

Captured live at 19:40 with cache `{pct: 3, reset_minutes: 289}` on a `Current session` period of 295 min — pacing computed to 150 %, exceeded the default `threshold-critical` of 90, and `extension.js:349` forces *any* critical meter to drive the whole label red.

## Root cause

`pacingPct(meter, periodLens)` in `gnome-extension/extension.js:84` and the parallel `pacing_pct(meter, period_lens)` in `server/generate-icon.py:82` both gate the divide-by-fraction with:

```
if (fraction <= 0.01) return pct;
```

That floor is **period-relative**. For a 5 h session, 1 % elapsed = 2.95 min — pacing becomes "valid" by minute 3, and a single 3 % action paces to 150 %. The floor was tuned for the weekly bucket (where 1 % = ~97 min, plenty for one action to be statistical noise). On the much shorter session bucket it produces minutes-long windows where any usage looks like a runaway.

## Fix (option B from the chat)

Replace the period-relative floor with a **time-based floor**: pacing is suppressed until at least **15 min** have elapsed in the period.

```js
function pacingPct(meter, periodLens) {
    const pct = meter.pct;
    if (typeof pct !== 'number' || pct === 0) return pct ?? 0;
    const rm = meter.reset_minutes;
    const period = periodLens?.[meter.label];
    if (rm == null || !period) return pct;
    const elapsed = period - rm;
    // Time-based suppression: pacing requires ≥ 15 min elapsed. The previous
    // 1 %-of-period floor was too aggressive on the 5 h session bucket — a
    // single action 4 min in paced to ~150 % and tripped critical. 15 min is
    // long enough that one action is no longer dominant, short enough to still
    // catch real fast-burn on the weekly bucket.
    if (elapsed < 15) return pct;
    return pct / (elapsed / period);
}
```

Effect across the three known bucket sizes:

| Bucket | Period | Old floor (1 %) | New floor (15 min) |
|---|---|---|---|
| Current session | 295 min | suppress < 3 min | suppress < 15 min |
| All models (weekly) | 9 680 min | suppress < 97 min | suppress < 15 min |
| Daily included routine runs | 1 440 min | suppress < 14.4 min | suppress < 15 min |

The session bucket gains 12 more minutes of suppression (the bug class disappears). The weekly bucket *loses* ~82 min of suppression — but at minute 16 of a week, raw pct will be small enough that pacing rarely crosses 90 unless usage is genuinely extreme, so the loss is acceptable.

## Files changed

1. `gnome-extension/extension.js` — `pacingPct` body (≈ 5-line change).
2. `server/generate-icon.py` — `pacing_pct` body (same logic, kept in sync by hand; the SC-3 lint covers scraper parity, not pacing parity — a future tightening is noted in the deferred TODO).
3. `server/tests/test_pacing.py` — **new** pytest covering the regression scenario plus the boundary cases (elapsed = 14 / 15 / 16 min, zero pct, missing reset_minutes, missing period).
4. `packaging/control` — `Version: 0.11.13` → `0.11.14`.
5. `chrome-extension/manifest.json` — `"version": "0.11.13"` → `"0.11.14"` (release-task parity guard demands matching versions even though the Chrome extension is unchanged).
6. `TODO.md` — move this item to Done after verification.

## Why not also touch JS via a parity lint

The existing `scripts/lint-scraper-parity.py` (SC-3) only compares scraper regex tables. Generalising it to function bodies in two languages is a bigger lift than the fix. The Python test catches semantic regressions (15 → 14, off-by-one, sign flip); JS parity is maintained by hand for now. A note in the deferred TODO covers the structural follow-up.

## Verification

1. Run `task test` — all pre-existing tests + new `test_pacing.py` cases pass.
2. Run `python3 -c "from server.generate_icon import pacing_pct; print(pacing_pct({'label':'Current session','pct':3,'reset_minutes':289}, {'Current session':295}))"` — expect `3` (suppressed, not 147.5).
3. Visual check in the running panel: 6 min into a `Current session` with one Opus turn (~3 %), label should be Anthropic-orange not red.
4. Rebuild + reload the GNOME extension via Wayland-safe path (render a popup-preview PNG with live data + GSettings rather than asking for a logout — per the project's standing rule for extension.js changes).
5. `claude-usage-status` continues to report `✓ v0.11.14` after a fresh `.deb` install.

## Out of scope

- Refactoring pacing to a single source of truth (one of: shared Python lib that JS imports, or generated JS from Python). Worth doing eventually but disproportionate for a 5-line bug fix.
- Generalising `lint-scraper-parity.py` to cover pacing parity. Same reasoning.
- Adjusting the 15-min default in GSettings — keeping the constant inline. If telemetry later shows the weekly bucket suffers, a `pacing-min-elapsed-minutes` schema key can be added.
