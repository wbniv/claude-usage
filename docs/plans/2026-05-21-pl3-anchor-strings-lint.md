# PL-3 — anchor-strings parity lint

**Origin**: [PL-3 investigation](../investigations/2026-05-21-pl3-scraper-string-parity.md) — Recommendation A approved by user (2026-05-21).
**Scope**: extend `scripts/lint-scraper-parity.py` only. No source changes to `scraper.js` or `background.js`.

## Changes

1. `scripts/lint-scraper-parity.py`
   - Add module-level `ANCHOR_STRINGS = ['Plan usage limits', 'Extra usage']`.
   - Add `DOM_SELECTORS_IN_BACKGROUND = ['[role="switch"][aria-label="Extra usage"]']`.
   - Add `check_anchor_strings()` — asserts each anchor is present in BOTH `scraper.js` and the inline scrape region of `background.js`; asserts each selector is present in `background.js`.
   - Wire into `main()` next to `check_scraper_parity()` and `check_pacing_parity()`.

2. `chrome-extension/scraper.js`
   - One-line leading-comment note pointing at the new lint so future readers know the section anchors are pinned.

3. `TODO.md`
   - Move `PL-3` from Deferred → Done with a one-line summary.

No Taskfile edit needed — `task lint-scraper-parity` already runs `main()`.

## Verification

1. Lint passes on current source:
   ```
   python3 scripts/lint-scraper-parity.py
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

2. Regression guard — temporarily typo an anchor in `scraper.js`, confirm the lint fails with a precise diagnostic, then revert:
   ```
   sed -i "s/'Plan usage limits'/'Plan usage limit'/" chrome-extension/scraper.js
   python3 scripts/lint-scraper-parity.py ; echo "exit=$?"
   git checkout -- chrome-extension/scraper.js
   ```
   ```
   lint-anchor-strings: anchor 'Plan usage limits' missing in scraper.js

     A literal-equality anchor changed on one side but not the other.
     Update both, or update ANCHOR_STRINGS in this lint.
   exit=1
   ```
   PASS.

3. Regression guard — temporarily drop the DOM selector, confirm the selector-pin fires:
   ```
   sed -i 's|\[role="switch"\]\[aria-label="Extra usage"\]|[role="switch"]|' chrome-extension/background.js
   python3 scripts/lint-scraper-parity.py ; echo "exit=$?"
   git checkout -- chrome-extension/background.js
   ```
   ```
   lint-anchor-strings: required selector '[role="switch"][aria-label="Extra usage"]' missing in background.js

     A literal-equality anchor changed on one side but not the other.
     Update both, or update ANCHOR_STRINGS in this lint.
   exit=1
   ```
   PASS.

4. Existing test suites still pass:
   ```
   task lint
   ```
   Deferred — captured in the commit's pre-push CI; the parity lint above is the only behaviour change.

## Risk

Minimal — lint-only change. Worst case: false positive blocks CI; revert the lint commit and re-derive.
