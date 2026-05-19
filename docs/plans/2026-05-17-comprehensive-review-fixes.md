# Plan: Fix All Bugs from Comprehensive Code Review

## Context

The comprehensive code review (2026-05-18) identified 6 concrete bugs across `gnome-extension/prefs.js`, `gnome-extension/extension.js`, `chrome-extension/scraper.js`, `chrome-extension/background.js`, and `.github/workflows/release.yml`. This plan implements all 6 fixes.

**Critical structural fact:** `chrome-extension/scraper.js` is the canonical source for `parseResetMinutes`, `isHydrated`, and `doScrape` — `test/scraper.test.js` imports from it. `background.js` has inlined copies of these functions inside the `executeScript` `func:` callback (which runs in page context and cannot import). The header comment in scraper.js says: _"Keep both in sync when changing parsing logic."_ Every parsing change must touch **both** files.

---

## Files to Modify

| File | Bugs fixed |
|------|-----------|
| `gnome-extension/prefs.js` | PREFS-1 |
| `gnome-extension/extension.js` | JS-1 |
| `chrome-extension/scraper.js` | JS-1, JS-7 |
| `chrome-extension/background.js` | JS-1 (mirrored), JS-6, JS-7 (mirrored) |
| `.github/workflows/release.yml` | CI-1, CI-2 |

---

## Fix Details

### PREFS-1 — Debounce `regenIcon()` in `gnome-extension/prefs.js`

**Problem:** `addSpinRow` calls `regenIcon()` on every `value-changed` signal when `regen=true`. The two threshold spinrows both use `regen=true`. Cross-validation between spinrows also fires `set_value()` on the adjacent slider, triggering a second `value-changed`. Dragging a threshold 20 steps spawns 20–40 icon-generation subprocesses.

**Change:**

Add a module-level `let _regenTimer = null;` before the `addColorRow` function.

In `addSpinRow` (L49-52), replace:
```js
adj.connect('value-changed', () => {
    settings.set_uint(key, Math.round(adj.get_value()));
    if (regen) regenIcon();
});
```
With:
```js
adj.connect('value-changed', () => {
    settings.set_uint(key, Math.round(adj.get_value()));
    if (regen) {
        clearTimeout(_regenTimer);
        _regenTimer = setTimeout(() => { _regenTimer = null; regenIcon(); }, 300);
    }
});
```

`clearTimeout(null)` is safe (no-op). `_regenTimer` is module-scoped so all spinrows share one timer — if user changes both thresholds rapidly, exactly one regen fires 300 ms after the last change. `setTimeout`/`clearTimeout` are available in GJS.

---

### JS-1 — `wdMap` guard in `gnome-extension/extension.js`

**Problem:** `formatReset()` looks up `wdMap[day]` but has no guard for unknown day abbreviations. If `day` doesn't match a key, `ahead` is `NaN` and date arithmetic fails silently (falls back to non-countdown display). `tooltip.py` already has `if day not in WD_MAP: return None` — this is the JS equivalent.

**Change:** In `formatReset` (L31), after the wdMap definition, insert one line:
```js
const wdMap = {Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6};
if (!(day in wdMap)) return reset;  // unknown abbreviation — show literal
let ahead = (wdMap[day] - now.getDay() + 7) % 7;
```

`return reset` matches the function's existing last-line fallback (`return reset;`) for unrecognized formats.

---

### JS-1 — `wdMap` guard in `chrome-extension/scraper.js` (canonical source)

**Problem:** Same as above — `parseResetMinutes` lacks the guard. If `wdMap[day]` is undefined, `Math.min(NaN, …)` returns NaN; `JSON.stringify` converts it to null before the POST (server sees valid null), so the bug is masked, but the code is inconsistent with tooltip.py.

**Change:** In `parseResetMinutes` (L26), after wdMap definition:
```js
const wdMap = {Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6};
if (!(day in wdMap)) return null;
let ahead = (wdMap[day] - now.getDay() + 7) % 7;
```

No test impact: existing tests use valid day abbreviations only.

---

### JS-1 — `wdMap` guard in `chrome-extension/background.js` (mirrored copy)

**Change:** In `parseResetMinutes` (L63), same one-line addition:
```js
const wdMap = {Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6};
if (!(day in wdMap)) return null;
let ahead = (wdMap[day] - now.getDay() + 7) % 7;
```

---

### JS-6 — Log unrecognized plan tiers in `chrome-extension/background.js`

**Problem:** Plan tier regex `/^(?:Plan:\s*)?(Max(?:\s*\([^)]+\))?|Pro|Free|Team)$/` silently leaves `plan = null` for any unrecognized tier. Impact is cosmetic (status bar shows "Claude"), but the failure is invisible without developer tooling.

**Change:** In `scrapeAndPost`, after the meter-empty guard (after the `if (!data || !data.meters.length)` block that returns early), add a warning before meter enrichment:

```js
// (after the fail-path early return, before meter enrichment loop)
if (!data.plan) {
    console.warn('Claude Usage: plan tier not recognized; status bar will show "Claude"');
}
```

No change to scraper.js (it's a pure parser; logging belongs in the caller).

---

### JS-7 — Tighten balance regex in `chrome-extension/scraper.js` (canonical)

**Problem:** `/^(\$[\d,.]+)$/` accepts `$1,2,3` (misplaced commas) and `$1.2.3` (multiple decimals). Display-only impact but sloppy defensive coding.

**Change:** Line 104, replace regex:
```js
// Before:
const balMatch = lines[i].match(/^(\$[\d,.]+)$/);

// After:
const balMatch = lines[i].match(/^(\$\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)$/);
```

Test compatibility: existing test uses `'$89.50'` (matches `$` + `89` (≤3 digits) + `.50` ✓) and `'$10.50'` ✓. No test breakage.

---

### JS-7 — Tighten balance regex in `chrome-extension/background.js` (mirrored copy)

**Change:** Line 156, same regex replacement:
```js
const balMatch = lines[i].match(/^(\$\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)$/);
```

---

### CI-1 — Add Chrome extension tests to `release.yml`

**Problem:** `task test-scraper` (44 Node.js unit tests) is never run in CI. Scraper regressions can ship.

**Change:** Add a step after "Install go-task" and before the Docker cache step:
```yaml
      - name: Test Chrome extension
        run: task test-scraper
```

Node.js is pre-installed on `ubuntu-latest`. No additional setup needed.

---

### CI-2 — Validate tag name matches package version in `release.yml`

**Problem:** A manually pushed tag (bypassing `task release`) can publish "Claude Usage v1.0.0" with a `.deb` named `claude-usage_0.10.7_all.deb` — a visible user-facing discrepancy.

**Change:** Add a step after checkout (before any build work):
```yaml
      - name: Validate tag matches package version
        run: |
          set -euo pipefail
          pkg_ver=$(grep '^Version:' packaging/control | awk '{print $2}')
          tag_ver="${GITHUB_REF_NAME#v}"
          if [ "$pkg_ver" != "$tag_ver" ]; then
            echo "Tag $GITHUB_REF_NAME does not match packaging/control version $pkg_ver" >&2
            exit 1
          fi
```

---

## Commit Plan

Single commit covering all 6 bugs. Title: `fix: comprehensive review fixes (PREFS-1, JS-1, JS-6, JS-7, CI-1, CI-2)`

Update the review report to mark all Section 4 findings as fixed (strikethrough the finding headers, same pattern as prior pass summary tables).

---

## Verification

1. `cd /home/will/SRC/claude-usage && task test-scraper` — all 44 tests must pass after scraper.js changes
2. Inspect prefs.js manually: only one `_regenTimer` declaration at module scope, `clearTimeout` called before every `setTimeout`
3. Check extension.js and both background.js/scraper.js changes are identical (wdMap guard) and both balance regexes are identical
4. Check release.yml: tag validation step comes before any Docker or build steps; test step comes before build
5. Verify no test file changes needed (all existing tests use valid inputs that pass both old and new regexes)
