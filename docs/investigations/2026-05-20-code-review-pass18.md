# Code Review — Pass 18 (post-pass-17 fix landings)

**Date:** 2026-05-20
**Reviewer:** Claude Opus 4.7 (max effort), four parallel agents — server Python, GNOME extension JS, Chrome extension JS, infra/build/docs
**HEAD:** `0146a4d`
**Scope:** The 11 commits since pass-17's review doc (`2283398..HEAD`) — i.e., the pass-17 fix landings themselves. Goal: find bugs the fixes introduced, not re-litigate the original findings. Trust the pass-17 resolution log for "what's already audited".
**Prior work:** [pass-17](2026-05-20-code-review-pass17.md), [server/schema_defaults.py](../../server/schema_defaults.py) (the SOT)

---

## 1. Executive Summary

One **Critical** (regression I introduced in MS-1), five **High** (real gaps in the pass-17 fixes), eleven Medium, nine Low, one Info.

| Sev | # | ID | Title | New this pass? |
|-----|---|----|-------|----------------|
| **Critical** | 1 | **TS‑2** | Icon orphan-sweep `pid_position=2` reads the literal `'tmp'`, never the PID. `int('tmp')` raises → except clause swallows → falls through to `unlink()`. **Sweep deletes live in-flight tmps from concurrent `generate-icon.py` invocations.** | ✓ (introduced by MS‑1) |
| **High** | 2 | **DT‑1** | `derive_tier` crashes with `TypeError` if cached `_scrape_fail_count` is a non-empty string. Validator rejects on POST, but a previously-corrupt cache survives until manually deleted. | ✓ |
| **High** | 3 | **PT‑1** | `prefs.js` L-4 `writeTimer` and L-5 `holder.regenTimer` fire after the prefs window closes. `adj.get_value()` reads a disposed `SpinRow` widget. | ✓ (introduced by L‑4/L‑5) |
| **High** | 4 | **OT‑1** | `setActionStatus` called at only 1 of 4 `postUpdate` sites in `background.js`. The other three leave the toolbar tooltip stale on partial-update, offline-buffer flush, and catastrophic-failure paths. | ✓ (gap in O‑1) |
| **High** | 5 | **L2‑2** | `_parse_failure` signal has no consumer. Producer + validator + storage all landed; nothing reads. The L-2 fix shipped half. | ✓ (gap in L‑2) |
| **High** | 6 | **VD‑1** | `test-deb-verify.sh` uses `py_compile` on `generate-icon.py`, which doesn't execute imports — so a future commit dropping the schema-XML copy from `build-deb.sh` would ship a broken .deb that py_compiles cleanly. | ✓ |
| Medium | 7 | **MD‑1** | M-1 commit docstring overclaims atomicity ("the dock can't end up with split-vintage icons across sizes" — false on SIGKILL between renames in phase 2). Cosmetic but misleading. | ✓ |
| Medium | 8 | **MD‑2** | `schema_defaults._load()` crashes import on missing XML with no helpful diagnostic. Every consumer dies with an unhelpful traceback. | ✓ |
| Medium | 9 | **SD‑1** | SECURITY.md claims a specific outbound-URL set; no CI guard. Future `host_permissions` addition lands without doc sync. | ✓ |
| Medium | 10 | **PF‑1** | `_parse_failure` predicate `/\d+\s*%/.test(text)` fires false positives on marketing copy, footer text, banners, logged-out states. | ✓ |
| Medium | 11 | **MV‑1** | `chrome-extension/manifest.json` version unchanged at 0.11.19 despite adding `idle` permission. CWS prompt fires on the wrong version. | ✓ |
| Medium | 12 | **AT‑1** | `chrome.action.setTitle` title interpolation is unbounded. Long error messages produce huge tooltips. | ✓ |
| Medium | 13 | **AT‑2** | MV3 service-worker state resets on SW restart; `chrome.action.setTitle` writes revert to `default_title`. The O-1 hover value evaporates between cycles. | ✓ |
| Medium | 14 | **PR‑2/3** | `prefs.js:schemaRange` crashes if called on a key without `<range>` or with a typo'd key name. Today only numeric+ranged keys are passed; future call sites need a precondition guard. | ✓ |
| Medium | 15 | **RL‑1** | Pass-17 commit `6533877`'s message + resolution log claim it closes `DR-1..5`. Only DR-2 and DR-4 landed there; DR-1/DR-3/DR-5 landed elsewhere. Doc accuracy. | ✓ |
| Medium | 16 | **LC‑2** | `destroy()` directly does `source_remove(_flashId)` instead of calling `_stopFlash()`. Bypasses L-6's `_destroyed` guard for the cleanup `opacity = 255`. Cosmetic (actor disposed soon) but inconsistent. | ✓ |
| Low | 17 | **LL‑1** | L-9 comment documents `_clearingMetric = false` ordering but not the symmetric `_clearMetricIdleId = null` invariant. Future re-order risk. | ✓ |
| Low | 18 | **JS‑1** | `safeColor` fallbacks (`#2a9a2a` etc.) hard-coded in `extension.js` — drift surface vs the Python SOT module. Closes if a CI lint cross-checks. | ✓ |
| Low | 19 | **CE‑1** | `load_contents_async` cancelled-error logs as generic `"failed to read cache"`. Every file-monitor coalesced read spams `journalctl`. | ✓ |
| Low | 20 | **UT‑1** | Statuspage description `.slice(0, 117)` cuts by UTF-16 code unit; a split surrogate pair produces invalid UTF-16. Theoretical; English Statuspage ASCII today. | ✓ |
| Low | 21 | **ID‑1** | `install.sh`'s `rsync --delete` wipes user-edited files under `$SERVER_DIR/chrome-extension/`. Undocumented. | ✓ |
| Low | 22 | **UG‑1** | Uninstall glob matches by name not content. Unlikely to bite (we own the IconName) but worth a note. | ✓ |
| Low | 23 | **RP‑1** | `render-panel-screenshot.py` `PCT_VALUE = threshold_warning + 4` can overflow `>100%` if threshold ever climbs above 96. | ✓ |
| Low | 24 | **BA‑1** | `_buffered_at` bound check uses `time.time() * 1000` (float). Cosmetic; sibling fields use int. | ✓ |
| Low | 25 | **RS‑1** | `rsync` is now a build/install prereq; not flagged in README or asserted at script start. | ✓ |
| Info | 26 | **CV‑1** | CM-1 reset-on-non-dict path has no regression test. | ✓ |

**Bottom line:** **TS‑2 is genuinely critical and I caused it** — the MS-1 sweep extension landed with the wrong field index. The PID-alive check is fully bypassed, and the sweep runs at server startup concurrently with a fresh `generate-icon.py` invocation. Fix is one character (`2 → 3`) plus a regression test.

The five Highs are all "the fix shipped but not all the way": OT-1 (3 missing call sites), L2-2 (signal with no reader), PT-1 (timer not cleaned up), DT-1 (type guard incomplete), VD-1 (test framework doesn't catch what was claimed). Each is a 5-15 line follow-up.

**Theme:** pass-17 landed a lot of changes fast; the fixes themselves need their own regression coverage. The new tests added (test_schema_defaults, test_tooltip, test_icon — 30 new) help, but they cover the helpers that DIDN'T need fixing more than the fix paths themselves (e.g., CV-1: no test asserts CM-1's behaviour).

No structural pattern here — these are mostly point bugs in individual fixes, not a new drift cluster.

---

## 2. Critical: TS‑2 — orphan-sweep PID guard bypassed

**Files:** `server/usage-server.py:567-573`

The new MS-1 sweep extension passes `pid_position=2` for icon-tmp files. The filename `.claude-usage.tmp.<PID>.<NS>.<SIZE>.png` splits by `.` into:

```
['', 'claude-usage', 'tmp', '<PID>', '<NS>', '<SIZE>', 'png']
   0        1          2       3        4       5       6
```

Position 2 is the literal `'tmp'`. `int('tmp')` raises `ValueError`, which the `except (ValueError, IndexError): pass` catches — then execution falls through to `orphan.unlink()`. **Every icon-tmp gets deleted regardless of PID liveness.**

Concrete failure: at server startup, `_sweep_orphan_tmps()` runs. If a `generate-icon.py` spawned by the previous server's last POST is mid-write (the PIL resize step takes hundreds of ms), the sweep deletes its tmp file before the rename phase can promote it. The rename then fails with `FileNotFoundError`; that size keeps its old icon vintage indefinitely.

**Fix:** change `pid_position=2` to `pid_position=3`. Add a regression test that creates a `.claude-usage.tmp.<own-pid>.<ns>.64.png` file under a tempdir, runs `_sweep_orphan_tmps`, and asserts the file still exists.

---

## 3. High — quick descriptions + fix sketches

### 3.1 DT‑1 — `derive_tier` crashes on non-int `_scrape_fail_count`
**File:** `server/generate-icon.py:248-250`

`(data.get('_scrape_fail_count') or 0) >= 2` raises if the value is a non-empty string (`"5"`). Validator rejects on POST, but a pre-existing corrupt cache survives.

**Fix:** explicit isinstance guard:
```python
sfc = data.get('_scrape_fail_count')
if isinstance(sfc, int) and not isinstance(sfc, bool) and sfc >= 2:
    return 'broken'
```

### 3.2 PT‑1 — prefs window-close timer leak
**File:** `gnome-extension/prefs.js:81-95`

L-4's `writeTimer` (per-`addSpinRow` closure) and L-5's `holder.regenTimer` both keep running after the prefs window closes. The `writeTimer` callback reads `adj.get_value()` from a disposed `SpinRow`.

**Fix:** thread the window into `fillPreferencesWindow`'s `holder`, register a `close-request` handler:
```js
const holder = {regenTimer: null, writeTimers: []};
window.connect('close-request', () => {
    if (holder.regenTimer) clearTimeout(holder.regenTimer);
    for (const t of holder.writeTimers) clearTimeout(t);
});
```
Track `writeTimer` in `holder.writeTimers` instead of a closure-local.

### 3.3 OT‑1 — `setActionStatus` only at 1 of 4 `postUpdate` sites
**File:** `chrome-extension/background.js`, sites at lines 346, 369, 415, 503

Only line 369 (the main `fetchUsage` success/failure) calls `setActionStatus`. The empty-meters partial POST (346), the offline-buffer flush (415), and the catastrophic-failure POST (503) leave the tooltip stale.

**Fix:** add appropriate `setActionStatus(...)` calls at each remaining site. Probably a new kind `'partial'` for the empty-meters case and `'recovered'` for buffer flush.

### 3.4 L2‑2 — `_parse_failure` signal has no consumer
**Files:** `chrome-extension/scraper.js:121-128`, `background.js:303-310`, `server/usage-server.py:238-242`. Consumer: `scripts/claude-usage-status.py` should read but doesn't.

The L-2 commit shipped the producer + validator + cache-storage. Nothing reads the value. The signal lands in the cache and dies.

**Fix:** Surface in `claude-usage-status.py`:
```python
pf = d.get('_parse_failure')
if pf == 'locale_or_layout':
    print('  Parse:      ⚠ scraper produced no meters; page may be in a non-English locale')
```
And in extension.js — when the cache has `_parse_failure`, force broken-tier with a useful tooltip.

### 3.5 VD‑1 — `py_compile` doesn't catch import failures
**Files:** `packaging/test-deb-verify.sh:11-19`, `server/generate-icon.py:65`

`python3 -m py_compile` parses the file but doesn't execute imports. A future `build-deb.sh` edit dropping the `schemas/*.xml` copy ships a .deb where `from schema_defaults import DEFAULTS` would crash at import — and the per-distro container test passes.

**Fix:** add to `test-deb-verify.sh`:
```bash
test -f /usr/share/claude-usage/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
python3 -c "import sys; sys.path.insert(0, '/usr/share/claude-usage'); import schema_defaults; assert schema_defaults.DEFAULTS"
```

---

## 4. Medium / Low / Info — short descriptions

| ID | Where | Note | Fix sketch |
|----|-------|------|-----------|
| **MD‑1** | `generate-icon.py:286-290` (docstring) | M-1 claims "can't end up with split-vintage" — false on SIGKILL mid-rename | Reword: "the inconsistency window shrinks from … to …" |
| **MD‑2** | `schema_defaults.py:90` | `_load()` import-time crash with bare traceback | Wrap with try/except → print useful hint to stderr |
| **SD‑1** | `SECURITY.md:78-82` vs `manifest.json:host_permissions` | No CI guard between SECURITY's outbound-URL claim and manifest | Add `scripts/lint-security-doc.py` that asserts the lists match |
| **PF‑1** | `scraper.js:121-128` + `background.js:303-310` | `_parse_failure` predicate too wide; false positives on `%` in marketing copy | Anchor on `\d+\s*%\s*used` (the actual meter format) |
| **MV‑1** | `chrome-extension/manifest.json:4` | Version 0.11.19 — unchanged despite adding `idle` permission | `task bump NEW=0.11.20` before next CWS publish |
| **AT‑1** | `background.js:67-83` `setActionStatus` | `errorMsg` interpolated unbounded into title | Cap `errorMsg` at 80 chars |
| **AT‑2** | `background.js:67-83` + manifest | MV3 SW restart reverts `setTitle` to `default_title` | Persist last-status to `chrome.storage.local`; restore on SW wake |
| **PR‑2/3** | `prefs.js:63-69` `schemaRange` | No guard for non-range or typo'd keys | Add precondition check + clear error |
| **RL‑1** | `2026-05-20-code-review-pass17.md:486-510` resolution log | Doc claims `6533877` closed DR-1..5; actually DR-2/DR-4 only | Amend resolution log + commit body |
| **LC‑2** | `extension.js:585-591` `destroy()` | Inlines `source_remove(_flashId)` instead of calling `_stopFlash()` | Replace with `this._stopFlash()` (already L-6-guarded) |
| **LL‑1** | `extension.js:550-565` `_getPrimary` idle | L-9 comment misses `_clearMetricIdleId = null` ordering invariant | Extend the comment |
| **JS‑1** | `extension.js:356-363` `safeColor` fallbacks | Hardcoded hex literals are drift surface vs Python SOT | Add CI lint that grep-checks |
| **CE‑1** | `extension.js:303-324` cancelled-read | Cancellation throws → caught + logged as generic "failed to read cache" | Special-case `Gio.IOErrorEnum.CANCELLED` → return silently |
| **UT‑1** | `background.js:148-149` | UTF-16 code-unit slice — surrogate split risk on non-ASCII | Use code-point-aware truncation if non-English Statuspage ever ships |
| **ID‑1** | `install.sh:144` | `rsync --delete` clobbers user-edited files under `$SERVER_DIR/chrome-extension/` | Document in install.sh comment |
| **UG‑1** | `install.sh:49` uninstall glob | Matches by name; we own the icon name so practically safe | Add comment about the namespace assumption |
| **RP‑1** | `render-panel-screenshot.py:35` | `threshold_warning + 4` overflows `>100` if threshold climbs above 96 | `min(99, ...)` or use midpoint of warn/crit |
| **BA‑1** | `usage-server.py:250-252` | `time.time() * 1000` is float; sibling fields use int | `int(time.time() * 1000)` for consistency |
| **RS‑1** | `install.sh`, `build-deb.sh` | `rsync` used but not declared as prereq | Add `command -v rsync >/dev/null \|\| { ...; exit 1; }` |
| **CV‑1** | `tests/test_validate.py` | No regression test for CM-1's "reset prev on non-dict" path | Add `test_cache_reset_on_non_dict_prev` |

---

## 5. Items dismissed

- **DG‑3** — `setActionStatus`'s defensive `if (chrome.action)` guard is dead code. Acceptable style; skip.
- **DR‑1 read-side clamp** — pass-17 closed this; agent confirmed acceptable as-is.
- **EVENT_PROPAGATE** — pass-17's S-1 fix; no actual downstream consumer today.
- **CM-1 truncated-but-valid-dict edge case** — atomic rename has been in place since pass-15; theoretical only.
- **Test isolation `XDG_DATA_HOME`** — single-process pytest today; not actually a race.
- **Lifecycle audit** — agent confirmed every long-lived async source is tracked + cleaned in `destroy()`.
- **All SECURITY.md claims verified** — bound to 127.0.0.1 ✓, mode 0600 ✓, validator bounds ✓, outbound URLs accurate today ✓.

---

## 6. Recommended fix order

**Immediate:** TS-2 (1 char + test). Critical-blast-radius bug landed in pass-17.

**Within this pass:** all 5 Highs (DT-1, PT-1, OT-1, L2-2, VD-1). All have 5-15 line fixes.

**Mediums (mechanical):** MD-1, MD-2, PF-1, MV-1, PR-2/3, RL-1, LC-2, AT-1. These are 1-10 lines each.

**Mediums (more work):** SD-1 (new lint script), AT-2 (chrome.storage persistence + restore).

**Lows:** batch the doc-only and 1-line ones (LL-1, JS-1's lint, CE-1, UG-1, ID-1, RP-1, BA-1, RS-1). UT-1 is theoretical — defer.

**Info:** CV-1 test addition.

---

## 9. Resolution log

23 of 26 findings closed in 6 commits since the review (`a1c012e..cd81ca5`). Three deferred as TODO entries — all are design decisions, not mechanical fixes.

| ID | Title | Resolution |
|----|-------|-----------|
| **TS‑2**  | orphan-sweep PID guard bypassed | `a1c012e` + 5-test regression suite (`test_orphan_sweep.py`) |
| **DT‑1**  | derive_tier on non-int sfc | `3d6f2a2` + 4 test cases in `test_icon.py` |
| **PT‑1**  | prefs window-close timer leak | `3d6f2a2` (per-row Set tracked on holder, drained on close-request) |
| **OT‑1**  | setActionStatus at only 1 of 4 sites | `abdc37b` — now at all 4 with kinds: partial / recovered / scrape-failed |
| **L2‑2**  | _parse_failure has no consumer | `ff8ba90` — wired into claude-usage-status |
| **VD‑1**  | py_compile doesn't catch import | `ff8ba90` — test-deb-verify.sh now imports schema_defaults |
| **MD‑1**  | M-1 docstring overclaim | `2d1185a` — reworded to "shrinks from … to … — not zero" |
| **MD‑2**  | schema_defaults bare import error | `2d1185a` — wrap with stderr hint |
| **SD‑1**  | SECURITY.md outbound-URL has no CI guard | `cd81ca5` — new `scripts/lint-security-doc.py`, wired into `task test` |
| **PF‑1**  | _parse_failure predicate too wide | `2d1185a` — tightened to `\d+\s*%\s*used` |
| **MV‑1**  | version unchanged after permission change | `2d1185a` — `task bump NEW=0.11.20` |
| **AT‑1**  | setActionStatus title unbounded | `abdc37b` — cap errorMsg at 80 chars |
| **AT‑2**  | setActionStatus doesn't survive SW restart | `abdc37b` — persist+restore via chrome.storage.local |
| **PR‑2/3** | schemaRange lacks defensive guards | `2d1185a` — clear errors on no-range / unknown key |
| **RL‑1**  | pass-17 resolution log overclaim | `2d1185a` — pass-17 doc amended |
| **LC‑2**  | destroy() inlines partial _stopFlash | `3d6f2a2` — replace with `this._stopFlash()` |
| **LL‑1**  | L-9 missing _clearMetricIdleId ordering note | `cd81ca5` — comment extended |
| **CE‑1**  | cancelled load logs as generic error | `cd81ca5` — special-case Gio.IOErrorEnum.CANCELLED |
| **ID‑1**  | rsync --delete clobbers user edits | `cd81ca5` — install.sh comment |
| **UG‑1**  | uninstall glob matches by name | `cd81ca5` — install.sh comment about namespace |
| **RP‑1**  | render-panel can overflow >100 | `cd81ca5` — `min(99, threshold_warning + 4)` |
| **BA‑1**  | _buffered_at float arithmetic | `cd81ca5` — int() the anchor |
| **RS‑1**  | rsync prereq not asserted | `cd81ca5` — install.sh fails loudly at start if missing |
| **CV‑1**  | CM-1 reset path unguarded by test | `cd81ca5` — new `test_cache_reset_on_non_dict_prev` |
| **JS‑1**  | safeColor JS-side drift surface | **deferred** → [TODO](../../TODO.md) — needs design decision (JS lint or generate `_defaults.js` from schema) |
| **TT‑1**  | format_tooltip stderr spam | **deferred** → [TODO](../../TODO.md) — design call on log throttling |
| **UT‑1**  | UTF-16 surrogate-split | **deferred** → [TODO](../../TODO.md) — theoretical; English Statuspage today |

Test suite: 87 → 94. Lints: 2 → 3 (added `lint-security-doc`).

**Lessons for next pass:** the test stub setup (XDG_DATA_HOME tempdir + cairo/PIL stubs) is duplicated across `test_pacing.py`, `test_schema_defaults.py`, `test_icon.py`. A shared `conftest.py` would deduplicate ~30 lines × 3 files. Not a finding — just an opportunity. The new `test_orphan_sweep.py` skipped the stub block by using a `tmp_path` + `monkeypatch` fixture pattern; that's cleaner and probably worth migrating the others to.
