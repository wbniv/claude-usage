# Code Review — Pass 27 (post-pass-26 fix verification)

**Date:** 2026-05-20
**Reviewer:** Claude Opus 4.7, two parallel general-purpose agents
**HEAD:** `367afe7`
**Scope:** Diff-narrow review of the 5 fix commits that landed during pass-26 Phase 2 (`34263dd`..`367afe7`). Verifies correctness of all 23 closed findings; surfaces any regressions.
**Prior work:** [pass-26](2026-05-20-code-review-pass26.md)

---

## 1. Executive Summary

**1 finding:** 0 High, 0 Medium, 1 Low, 0 Info. The 23 fixes from pass-26 are all correct. One regression-guard gap: the NM-1 fix (`meters: null` rejection) landed without a test, violating the project's regression-guard rule.

| Sev | # | ID | Surface | Title |
|-----|---|----|---------|-------|
| ~~**Low**~~ | ~~1~~ | ~~**RT‑1**~~ | ~~tests~~ | ~~NM-1's `meters: null` rejection has no regression test in `test_validate.py`~~ |

**Carry-forward backlog** (deferred from pass-26 — unchanged, user has not acted):

| ID | Summary |
|----|---------|
| AS‑1 | `_autoScrapeIfEligible` holds mutex during async eligibility check |
| RD‑1 | `idle.onStateChanged` 'active' fires on every screen unlock with no debounce |
| SV‑1 | `metadata.json:shell-version` 45-49 only; GNOME 50 (Ubuntu 26.04) silently fails |
| PL‑3 | Scraper parity lint misses section-anchor strings and DOM selectors |
| TR‑1 | `docs/transcripts/` tracked + special-cased in `task release` dirty check |
| IN‑1 | `tabs` permission broader than `host_permissions` + `activeTab` would need |

---

## 2. Findings

### Tests (1 finding)

**RT‑1 (Low)** — `server/tests/test_validate.py` — no coverage added when NM-1 was fixed at `usage-server.py:116-117`. The fix (`if 'meters' in body and meters is None: return "…must not be null…"`) is correct, but `test_validate.py` has no test exercising `_validate({'meters': None})`. Per the project's regression-guard rule (CLAUDE.md: "propose a test that would catch it and include it in the same commit as the fix"), this gap should be closed. The test would assert `_validate({'meters': None})` returns a non-None error string containing `'meters'`.

**Fix:** Add `test_meters_null_rejected()` to `server/tests/test_validate.py`.

---

## 3. Items dismissed

- **GI‑1 color change** — `generate-icon.py` now reads `cfg['weekly_color_red']` (default `#ff5933`) instead of hardcoded `#e03030`. The delta in hue is minor; both are a "red-ish broken tier" color. Not a bug; schema-driven is strictly better. Confirmed intentional.
- All 23 pass-26 fixes verified correct by both review agents. No regressions found.

---

## 4. Recommended fix order

1. `RT-1` — add `test_meters_null_rejected()` (trivial, one assertion)

---

## 5. Resolution log

| ID | Title | Resolution |
|----|-------|------------|
| RT‑1 | NM-1 missing regression test | Fixed — `test_meters_null_rejected()` added to `server/tests/test_validate.py` |
