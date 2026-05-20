# Code Review — Pass 21 (post-pass-20 fix landings, loop iteration 4)

**Date:** 2026-05-20
**Reviewer:** Claude Opus 4.7 (max effort), two parallel agents
**HEAD:** `9757826`
**Scope:** 4 commits since pass-20's review doc HEAD (`123c579..HEAD`).
**Prior work:** [pass-20](2026-05-20-code-review-pass20.md), [pass-19](2026-05-20-code-review-pass19.md)

---

## 1. Executive Summary

Three Lows, zero High/Critical/Medium. The loop is converging — each iteration is finding less.

| Sev | # | ID | Title | New this pass? |
|-----|---|----|-------|----------------|
| Low | 1 | ~~**BL‑1**~~ | ~~`background-load.test.js`'s `process.off(...)` runs in the `finally` block — BEFORE the microtask drain. The intended diagnostic message `'background.js produced an unhandled rejection at load: …'` is dead code. The test still catches regressions via `node --test`'s built-in unhandled-rejection detection, but with a less specific failure message.~~ | ✓ (introduced by AR‑2's new test) |
| Low | 2 | ~~**DC‑1**~~ | ~~AR-2's declaration block was spliced into the middle of `postUpdate`'s doc comment area — the two visually merge into one comment but describe different things. Cosmetic.~~ | ✓ |
| Low | 3 | ~~**DC‑2**~~ | ~~Pass-20 resolution log arithmetic is off-by-one: `94 server + 50 scraper + 1 background-load = 95 + 50 = 145 (was 94 + 50)`. Actual: `95 + 51 = 146`. Same incorrect counts mirrored into TODO.md.~~ | ✓ |

**Bottom line:** Three minor follow-ups, all from pass-20's new test + doc. No regression in production code. The loop continues per step 12 (any Low-or-above keeps it running).

---

## 2. Findings

### 2.1 BL‑1 — load-test rejection handler removed before it can fire

**File:** `chrome-extension/test/background-load.test.js:95-114`

```js
process.on('unhandledRejection', rejectionHandler);
try { vm.createContext(...); vm.runInContext(...); }
catch (e) { topLevelError = e; }
finally { process.off('unhandledRejection', rejectionHandler); }   // ← too early
...
return new Promise((resolve) => setTimeout(() => {
    assert.equal(unhandledRejection, null, ...);
}, 50));
```

`runInContext` returns synchronously; the `finally` runs before any microtask. A rejection fired later (e.g. the AR-2 TDZ throw becoming a rejected promise) lands AFTER the handler is removed, so `unhandledRejection` stays `null`. The test still catches the regression because `node --test` has its own unhandled-rejection collector and marks the test failed — but the carefully-worded assertion message is unreachable.

**Fix:** move `process.off(...)` into the setTimeout callback so it runs AFTER the drain.

### 2.2 DC‑1 — comment block stitched into postUpdate's doc area

**File:** `chrome-extension/background.js:59-73`

AR-2's declaration block was inserted between `postUpdate`'s doc-comment fragment and the function. Two unrelated comment blocks visually merge.

**Fix:** add a blank line / clearer delimiter, or move the AR-2 declarations to a dedicated section higher up.

### 2.3 DC‑2 — arithmetic error in pass-20 resolution log + TODO.md

**Files:** `docs/investigations/2026-05-20-code-review-pass20.md:108`, `TODO.md:12`

Doc says `= 95 + 50 = 145 (was 94 + 50)`. Actual: `95 + 51 = 146`. The 51 scraper count includes the new background-load test that the same sentence references as "+1 background-load" but doesn't add to the scraper subtotal.

**Fix:** `Test suite: 95 server + 51 scraper = 146 (was 94 + 50 = 144; +1 OS-2, +1 background-load smoke).`

---

## 3. Items reviewed and dismissed

- AR-2 declaration move (verified all reads are below the new declarations)
- background-load.test stub completeness (all module-load APIs covered)
- SS-1 regex (verified against the live SECURITY.md + EOF case)
- OS-2 regression test (verified on the actual filename pattern)
- CV-4 subset check (correctly captures the invariant)
- MD-4 except tuple (catches all known malformed-schema paths)
- Strikethrough markers in pass-20 doc (all 5 IDs)
- Loop status §10 in pass-20 doc (correctly references step 12 + step 2)
- Cross-doc references (pass-19, pass-20 link targets resolve)
- Drift surfaces (none new)

---

## 4. Carried-forward TODOs (still awaiting human decision)

Per the slash-command Phase 1 step 4 addition this turn — list every still-open TODO item filed by an earlier review pass. These persist in every new review until the user marks them `[x]`.

- **JS-1 (pass-18)** — cross-language drift lint for `extension.js`'s `safeColor` fallback hex literals vs `server/schema_defaults.py`. Design call: grep-based CI cross-check, or generate `_defaults.js` from the gschema XML at build time. [Origin: pass-18](2026-05-20-code-review-pass18.md).
- **TT-1 (pass-18)** — `tooltip.format_tooltip` stderr spam (1440/day) if claude.ai renames meter labels. Design call: throttle, one-shot, or remove. [Origin: pass-18](2026-05-20-code-review-pass18.md).
- **UT-1 (pass-18)** — UTF-16 surrogate-split risk in Statuspage description truncation. Theoretical (English-only Statuspage today). Move to code-point-aware truncation if Anthropic localises. [Origin: pass-18](2026-05-20-code-review-pass18.md).
- Plus the **pacing visualization** prototype work (not from a review pass, but in the same `[ ]` queue — see `TODO.md`).

If you act on any of these, mark the corresponding line `[x]` in `TODO.md` and it'll drop out of the next review's carry-forward section.

---

## 5. Recommended fix order

Single batched commit — all three are 1-3 line edits. Per the slash command step 5, apply strikethrough in the same commit.

After: pass-22 fires. If it surfaces only Info-tier observations, the loop terminates per step 12.

---

## 9. Resolution log

All 3 findings closed in 1 batched commit (per §5).

| ID | Title | Resolution |
|----|-------|-----------|
| **BL‑1** | Load test's `process.off` ran before microtask drain | Moved into the `setTimeout` callback so the handler stays attached until after the assertion |
| **DC‑1** | Comment-block stitching after AR-2 spliced into postUpdate's doc | Moved AR-2 declarations into a clearly-delimited "module-scope mutable flags" section ABOVE the postUpdate doc-comment; restored postUpdate's full doc-comment paragraph |
| **DC‑2** | Pass-20 resolution log arithmetic off-by-one | Corrected to `95 server + 51 scraper = 146 (was 94 + 50 = 144)` in both the pass-20 doc and TODO.md |

Test suite still at 95 server + 51 scraper = 146; 3 lints green.

---

## 10. Loop status

3 Lows closed; the loop continues per step 12. Pass-22 fires next.
