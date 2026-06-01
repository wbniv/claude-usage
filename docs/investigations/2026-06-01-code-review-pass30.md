# Code Review — Pass 30 (verification of pass-29 fixes)

**Date:** 2026-06-01
**Reviewer:** Claude Opus 4.8, direct read-through + one adversarial verification agent
**HEAD:** `e46a045`
**Scope:** Diff-narrow verification of the 5 fix commits that landed in pass-29 (`2837acb..e46a045`). Confirms correctness + regression-freedom of all 15 fixes and re-sweeps the changed files for anything introduced or missed. Mirrors pass-27's "post-pass-26 fix verification" shape.
**Prior work:** [pass-29](2026-06-01-code-review-pass29.md)

---

## 1. Executive Summary

**0 findings.** All 15 pass-29 fixes verified correct and regression-free; nothing new surfaced in the changed surface. Empirical backing: `task test` green (110 server + 59 scraper + 4 gnome-format + 9 lints incl. lint-qml/lint-kde-parity/lint-gnome), `.deb` rebuilt + `dpkg-deb -c` checked, an rsync file-set diff for PKG-1, and live `gi` probes for SRV-1. **The review loop terminates here** — matching the clean-termination precedent of passes 22/25/28.

| Fix | Surface | Verdict |
|-----|---------|---------|
| ~~SRV‑1~~ | server/scripts | **Verified** — happy path preserved (real GSettings values + colour validation unchanged); both `Gio.Settings.new()` sites now behind a `lookup()` probe; `Gio` imported lazily so no module-load abort |
| ~~STAT‑1~~ | scripts | **Verified** — all 3 sites + meter loop coerced; `:91` correctly reuses the coerced `raw_ts` (the 3rd site the pass-29 read missed); bool excluded |
| ~~ICN‑1~~ | server | **Verified** — `continue` only skips the (already-default, in-range) value's range-check; boundaries 1/500 kept; DIFF-4 non-int test still holds |
| ~~KQ‑1~~ | kde | **Verified (structural)** — `root` resolves (pre-existing `root.*` at CompactRepresentation `:48/:51`); scroll direction matches the removed code; no click-to-expand regression (old MouseArea was `NoButton`). Runtime still `[verify][live]` |
| ~~KQ‑4~~ | kde | **Verified** — `Math.max(thresholdCritical, tWarn+1)`, critical checked first; only `pacingColor` ladders |
| ~~KQ‑6~~ | kde | **Verified** — Kirigami import + `_dimColor` valid; filled-bar/label `meterColor` untouched |
| ~~KQ‑5~~ | kde | **Verified** — `Math.max(0, …)` clamp |
| ~~EXT‑1~~ | gnome | **Verified** — `wantLink` (`:586`) in scope at `:638`; `_src.addNotification` (`:643`) + the `_lastNotifyTs`/`_spawnIconRegen`/`_lastTier` tail run outside the gate |
| ~~EXT‑2~~ | gnome | **Verified** — only residual `status.anthropic.com` is in the comment; page link + API URL both on the canonical host |
| ~~EXT‑3~~ | gnome | **Verified** — scraper does emit count/total + spent/balance, so the enriched `meterKey` is meaningful; template valid |
| ~~EXT‑4~~ | chrome | **Verified** — comment now matches the `30_000` deadline |
| ~~CI‑1/CI‑2~~ | ci | **Verified** — only-changed refs; both YAML parse; pre-existing healthy majors untouched |
| ~~DOC‑1~~ | docs | **Verified** — PRIVACY perms == manifest `permissions` exactly; host rows match patterns |
| ~~PKG‑1~~ | packaging | **Verified** — empirical rsync-vs-cp file-set diff: only `test/format.test.js` dropped; all real files land |

---

## 2. Re-sweep (regressions / misses in changed files)

Nothing to report. Specifically cleared:
- `activeMeterIndex` writers after the MouseArea removal — `resolveActiveMeter`, `cycleMeter`, the RadioButton `onClicked` — all consistent; no orphaned increment logic.
- No second unguarded `Gio.Settings.new()` anywhere in `scripts/`/`server/`.
- `popup-preview.py`'s `raise RuntimeError` lands in the right `except` → DEFAULTS; both failure modes (no `gi`, no schema) converge.
- Bookkeeping consistent: TODO records KQ-1 `[verify][live]`, all 6 deferred items, and the Done summary; the "105→110" server-test count is accurate.

---

## 3. Resolution log

| ID | Resolution |
|----|------------|
| SRV‑1 … PKG‑1 (all 15) | **Verified correct & regression-free** in pass-30; no further action |
| KQ‑1 | Code verified structurally; runtime scroll on Plasma 6 remains `[verify][live]` (TODO) |

---

## 4. Loop status: complete

Pass-30 surfaced **nothing substantive**, so the review loop terminates cleanly (precedent: passes 22/25/28). All remaining open work is user/design-gated and tracked in `TODO.md`:

- **Design calls** from pass-29: KQ-2 (count/Extra meter rendering), KQ-3 (eligibility/Sonnet-0% filter), KQ-7 (latent ARGB/RGBA, inert), KQ-8 (fontCombo highlight), LK-1 (lint range-coverage), BUF-1 (`_buffered_at` hygiene, inert).
- **`[verify][live]`**: KQ-1 scroll-to-cycle on a real Plasma 6 session (`task test-kde-live`).
- **Pre-existing**: the 2026-05-22 install.sh item, the 2026-05-30 GNOME-45 notify [verify][live], and the two 2026-05-31 deferred architecture items.
