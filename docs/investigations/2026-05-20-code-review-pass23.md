# Code Review — Pass 23 (post-pacing-viz landing + Phase-0 drain)

**Date:** 2026-05-20
**Reviewer:** Claude Opus 4.7 (max effort), three parallel agents
**HEAD:** `77b518c`
**Scope:** 7 commits since pass-21's HEAD (`9757826..HEAD`). The pacing-viz port to extension.js + generate-icon.py is the largest landing; JS-1 (gschema SOT for JS), UT-1 (code-point trunc), TT-1 (one-shot warning), small fix-followups round out the set.
**Prior work:** [pass-21](2026-05-20-code-review-pass21.md), [pass-22 no-needed](2026-05-20-no-pass22-needed.md), [pass-20](2026-05-20-code-review-pass20.md)

---

## 1. Executive Summary

No Critical/High/Medium. **8 Lows** (mostly maintenance + drift between sibling implementations), 3 Info-tier confirmations. The pacing-viz port itself is functionally correct in every code path the agents traced.

| Sev | # | ID | Title | New this pass? |
|-----|---|----|-------|----------------|
| Low | 1 | ~~**CAP‑1**~~ | ~~`chrome-extension/background.js:97` `cap()` has the **same UTF-16 surrogate-pair split bug UT-1 just fixed** in the sibling `trunc()`. Used on error messages (4xx body, scrape exceptions); identical-class fix.~~ | ✓ (missed by UT-1) |
| Low | 2 | **PS‑1** | Parity lint covers `pacingPct↔pacing_pct` and `elapsedFraction↔elapsed_fraction` but NOT `pacingSegments↔pacing_segments` or `colorFor↔color_for` — the two functions with the most semantic surface in the viz port. Drift is invisible to CI. | ✓ |
| Low | 3 | ~~**EF‑1**~~ | ~~JS `elapsedFraction` is missing the `if (!meter) return null` guard the Python twin has. Parity lint only diffs numeric literals; structural divergence is undetected. Not currently exploitable (sole caller passes a non-null meter).~~ | ✓ |
| Low | 4 | ~~**DR‑1**~~ | ~~`extension.js:14` comment points at `lint-js-defaults-parity.py` — a file that doesn't exist. Actual lint is `gen-js-defaults.py --check` invoked via `task lint-js-defaults`. Doc drift.~~ | ✓ |
| Low | 5 | **GD‑1** | `scripts/gen-js-defaults.py:36-63` duplicates `_parse_default` + `_kebab_to_snake` from `server/schema_defaults.py`. The JS-1 SOT story has two parsers now; a future schema-type addition needs the same edit in both places. | ✓ |
| Low | 6 | **GD‑2** | `gen-js-defaults.py` lacks the helpful-error wrapper `schema_defaults.py` grew over MD-2/MD-3/MD-4. Malformed XML produces a bare `ParseError` traceback rather than the "reinstall the .deb" hint its Python sibling emits. | ✓ |
| Low | 7 | ~~**DR‑2**~~ | ~~`_doc_render.py:135-146` has a dead branch — the `is_count_only` check splits into two identical bodies. Either collapse or wire the split to actually do something different for count rows.~~ | ✓ |
| Low | 8 | ~~**DR‑3**~~ | ~~`docs/investigations/2026-05-20-no-pass22-needed.md:20-22` lists JS-1/TT-1/UT-1 as carry-forward, but all three have landed since. Doc is historically accurate at write-time; reads as stale at HEAD.~~ | ✓ |
| Info | 9 | ~~**GI‑1**~~ | ~~`.claude/scheduled_tasks.lock` is untracked + not in `.gitignore`. Per-process state; should be ignored.~~ | ✓ |
| Info | 10 | **TX‑1** | `formatRows`' `text` field on bar rows is now dead weight after the markup port — the consumer only reads it on the no-bar path. Harmless plain-text fallback; could be dropped or kept as defensive. | ✓ |
| Info | 11 | **CT‑1** | Count rows (e.g. "Daily included routine runs 0/15") render with blank bar in both extension.js and the doc renderer. Pass-19's `_doc_render.py:106-112` comment is now stale relative to its own commit (says "[viz] not yet shipped" but it IS shipped, just not for count rows). Intentional or oversight? | ✓ |

**Bottom line:** the pacing-viz port is solid in the happy paths. The findings are sibling-implementation drift (`cap` vs `trunc`, JS vs Python guards) and lint-coverage gaps that won't matter today but will the next time someone edits the viz functions.

---

## 2. Findings (brief, with fix sketches)

| ID | File | Fix sketch |
|----|------|-----------|
| **CAP‑1** | `chrome-extension/background.js:97` | Apply UT-1's pattern: `cap = s => { if (typeof s !== 'string') return s; const cps = [...s]; return cps.length > 80 ? cps.slice(0, 77).join('') + '...' : s; }` |
| **PS‑1** | `scripts/lint-scraper-parity.py:189-192` | Extend `pairs` to include `('pacingSegments', 'pacing_segments')` and `('colorFor', 'color_for')`. The Python copies live in `popup-preview.py`, not `generate-icon.py` — extend `check_pacing_parity` to also load from popup-preview.py |
| **EF‑1** | `gnome-extension/extension.js:115-122` | Add `if (!meter) return null;` as the first line. Matches the Python sibling at `generate-icon.py:218-219`. |
| **DR‑1** | `gnome-extension/extension.js:14` | Replace `lint-js-defaults-parity.py` → `task lint-js-defaults` |
| **GD‑1** | `scripts/gen-js-defaults.py` | `from schema_defaults import _parse_default, _kebab_to_snake` instead of redefining. Adjust `_load` accordingly. |
| **GD‑2** | `scripts/gen-js-defaults.py` (around `_load()`) | Wrap with the same try/except as `schema_defaults.py:99-108` (FileNotFoundError, ParseError, Permission, IsADirectory, ValueError, KeyError) and emit the same hint to stderr. |
| **DR‑2** | `scripts/_doc_render.py:135-146` | Drop the `is_count_only` local + the dead first `if` branch; the second `elif` already handles every count-meter case. |
| **DR‑3** | `docs/investigations/2026-05-20-no-pass22-needed.md` | Add a footer: "Update: between this doc and pass-23, commits `4e9df23`/`624adb4`/`0e1f913`/`013ccea`/`77b518c` closed JS-1, TT-1, UT-1, and the pacing viz. Carry-forward backlog now empty." |
| **GI‑1** | `.gitignore` | Add `.claude/scheduled_tasks.lock` (or `.claude/*.lock`). |
| **TX‑1** | n/a | Acceptable as defensive fallback; no action. |
| **CT‑1** | n/a / `_doc_render.py` comment | Update the stale comment OR make a deliberate decision about count-row bars. |

---

## 3. Carried-forward TODOs (still awaiting human decision)

**Carry-forward backlog: empty** — every deferred item from prior passes (pacing viz, JS-1, TT-1, UT-1) has been resolved this session.

---

## 4. Recommended fix order

One batched commit covers everything: CAP-1 + EF-1 + DR-1 + DR-2 + DR-3 + GI-1 + TX-1/CT-1 note. Two separate commits worth splitting:
- **PS-1** (extend parity lint) — touches lint code, distinct from the user-facing fixes
- **GD-1 + GD-2** (gen-js-defaults consolidation) — touches the JS-1 work

After: pass-24 fires per step 12.

---

## 9. Resolution log

_To be populated after fixes land._
