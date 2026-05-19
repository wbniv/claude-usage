# Code Review — Pass 16 (post-0.11.16, full-codebase sweep)

**Date:** 2026-05-19
**Reviewer:** Claude (Opus 4.7, max effort, 1M context, "ultrathink")
**HEAD:** `e21a1ba` (0.11.16)
**Scope:** Full codebase. Pass-15 closed 9 of 10 findings across 0.11.12–0.11.13; the pacing fix shipped as 0.11.14–0.11.16. This pass re-reads with fresh eyes, biased toward (a) anything pass-15 didn't drill into, (b) live runtime evidence on the maintainer's machine, and (c) drift propagated from the pass-13 `age > 10 → 15` change.
**Prior work:** [pass-15](2026-05-19-code-review-pass15.md), [pass-14](2026-05-18-code-review-pass14.md), [docs/wont-fix.md](../wont-fix.md), [pacing-fix plan](../plans/2026-05-19-pacing-early-period-fix-0-11-14.md)

---

## 1. Executive Summary

Three findings that affect users today (M/M/M), four worth flagging (L), three info-level.

| Sev | # | ID | Title | New? |
|-----|---|----|-------|------|
| **Medium** | 1 | ~~**TH‑1**~~ | ~~Stale-tier threshold drifted code↔docs↔diagnostic — extension.js code says `> 15`, but extension.js comment, claude-usage-status, and MANUAL all say `10`. Pass-13 A‑2 updated the code only. **Diagnostic tool lies to the user.**~~ | ✓ |
| **Medium** | 2 | ~~**V‑2**~~ | ~~Top-level unknown keys persist forever via `{**prev, **body}` merge. Demonstrated live: maintainer's cache still carries `_debug` removed in commit 347276a (3 days ago). Cache grows monotonically with garbage.~~ | ✓ |
| **Medium** | 3 | ~~**PL‑1**~~ | ~~Single POST wipes `_period_lengths` accumulator. Confirmed live — one `curl` to /update with a fake-meter payload erased the legit "Current session" + "All models" period entries. Pacing-based color silently disabled until re-accumulation.~~ | ✓ |
| Low | 4 | ~~**R‑1**~~ | ~~`_autoScrapeIfEligible` has check-then-await-then-set on `_fetching`. Two near-simultaneous events (e.g. `tabs.onUpdated` + `tabs.onActivated` after a navigation) both pass the guard and double-scrape.~~ | ✓ |
| Low | 5 | ~~**WP‑1**~~ | ~~15-min floor in pacing is tuned for 5h session bucket (15/300 = 5% elapsed, meaningful denominator). For 7-day weekly bucket (15/10080 = 0.15% elapsed), pacing fires `red` at any `pct > 0.14%` from minute 16 — the same false-positive class the 0.11.14 fix closed for sessions still exists for weeklies.~~ | ✓ |
| Low | 6 | ~~**D‑1**~~ | ~~`tooltip.update_desktop()`'s Name=-only path (60s tick) read-modify-writes the .desktop file. The comment claims "we never clobber an Icon= written by a concurrent generate-icon.py", but the window between read and replace can revert Icon= to its pre-generate value.~~ | ✓ |
| Low | 7 | ~~**D‑2**~~ | ~~No startup icon refresh. `usage-server.py` `__main__` block doesn't spawn `generate-icon.py`. Between server boot and first POST (up to 7 min via Chrome alarm; longer if Chrome isn't running) the dock icon is whatever was last written.~~ | ✓ |
| Info | 8 | ~~**N‑1**~~ | ~~Critical-pacing toast can read "All models is at 605% pacing" — math correct but the user has no frame for what "605% pacing" means.~~ | ✓ |
| Info | 9 | ~~**V‑3**~~ | ~~`_validate` accepts `_period_lengths: {"": 100}` and `meters: [{label: "", ...}]`. The empty-label case feeds the current_labels eviction set (PL‑1) and contributes to the wipe. Pre-existing pattern.~~ | ✓ |
| Info | 10 | ~~**I‑1**~~ | ~~`install.sh` `cp -r` doesn't remove stale files from previous installs. A renamed/removed source file persists in `$SERVER_DIR`. The .deb path is fine (dpkg owns file lists); only matters for `--from-source` users iterating across versions.~~ | ✓ |

**Bottom line:** No critical or high-severity finding. **TH‑1** is the most important — `claude-usage-status` actively misleads users about when the panel will flip to STALE, and MANUAL.md documents thresholds that don't match the code. Pass-13 A‑2 updated extension.js's one threshold but missed three downstream consumers (the comment in the same file, the diagnostic tool, the user manual).

**V‑2** and **PL‑1** are paired findings: both are gaps in the cache-merge layer (line 314 of usage-server.py: `body = {**prev, **body}`). Top-level fields are not whitelisted, and `_period_lengths` is structurally fragile to any POST with a stripped meter set. Both have direct evidence on the maintainer's running cache as of 13:30 UTC today.

---

## 2. TH‑1 — Stale-tier threshold drift (Medium, user-facing diagnostic correctness)

**Files:** `gnome-extension/extension.js:392, 410`; `scripts/claude-usage-status.py:42, 45`; `MANUAL.md:51`

### What's wrong

Pass-13 A‑2 raised the stale threshold from 10 → 15 minutes in extension.js to absorb MV3 alarm jitter. But **three other places** still claim the threshold is 10:

```
gnome-extension/extension.js:392        //   stale  — age > 10 min      ← STALE COMMENT
gnome-extension/extension.js:410        } else if (age !== null && age > 15) {   ← REAL CODE
scripts/claude-usage-status.py:42       if ts_min > 20:                 ← matches broken-tier
scripts/claude-usage-status.py:45       elif ts_min > 10:               ← STALE; should be 15
MANUAL.md:51                            "No fresh data in 10 min"       ← STALE
```

### Why it matters

`claude-usage-status` is the **diagnostic tool the manual points users to** when something is wrong. Its job is to tell the user when state has crossed a threshold. With the drift:

- At `ts_min = 12`, the diagnostic prints `⚠ 12m old — extension flips to STALE at this point` — but the extension is still in NORMAL. User runs the tool because they think the panel should have flipped, the tool confirms their (wrong) expectation, and they file a "panel didn't go grey at 10 min" bug.
- MANUAL.md's "When something is wrong" table promises stale at 10 min. Users plan their workflow around documented thresholds; this is a contract.

### Confirmed live

```
$ grep -c '> 15' gnome-extension/extension.js
1
$ grep -c '> 10' gnome-extension/extension.js scripts/claude-usage-status.py
gnome-extension/extension.js:1
scripts/claude-usage-status.py:1
$ grep '10 min' MANUAL.md
| **Stale** | No fresh data in 10 min (~1.5 missed fetches) | …
```

### Fix

One line in each of three files:

1. `gnome-extension/extension.js:392` — comment: `//   stale  — age > 15 min`
2. `scripts/claude-usage-status.py:42-46` — bump the `ts_min > 10` branch to `> 15` (and adjust the message text)
3. `MANUAL.md:51` — `No fresh data in 10 min` → `No fresh data in 15 min`. The `(~1.5 missed fetches)` aside still works (15 / 7 ≈ 2.1, round to "~2 missed").

### Regression guard

The CLAUDE.md rule "When the user reports a bug, propose a test that would catch it" applies. A `scripts/lint-thresholds.py` that grep-checks `> 15` matches between extension.js and the docstring/diagnostic would catch future drift. Lower-friction alternative: define `STALE_MIN = 15` and `BROKEN_MIN = 20` as named constants at the top of extension.js, then reference them from the comment template; the diagnostic stays a separate concern but at least the in-file drift becomes self-evident.

### Severity rationale

Medium because:
- User-facing tool actively lies. Diagnostic correctness is the diagnostic's whole job.
- MANUAL.md documents wrong behavior. Hard to find via grep unless you know to look.
- Self-discovered by anyone who actually runs `claude-usage-status` between 10–15 min after last scrape.
- One-commit fix; no design questions.

Not High because the user-visible impact is "the diagnostic is wrong" not "the panel is wrong". The panel works correctly per the new threshold.

---

## 3. V‑2 — Top-level unknown keys persist forever (Medium, hidden monotonic growth)

**File:** `server/usage-server.py:314`

```python
body = {**prev, **body}
```

### What's wrong

The merge step is a shallow spread that **keeps every prev key body doesn't override**. There is no top-level allowlist. The Chrome extension is "trusted" to send only known keys, but:

1. There's no enforcement.
2. When the Chrome extension *changes its emitted keys* (adds + later removes), the removed keys persist in cache forever.

### Confirmed live

Today, **right now**, on the maintainer's machine:

```
$ python3 -m json.tool < ~/.cache/claude-usage/usage.json
{
    "_scrape_fail_count": 0,
    "_anthropic_status": {…},
    "_ext_version": "0.11.13",
    "_timestamp": 1779198349,
    "_period_lengths": {…},
    "_schema": 1,
    "_debug": {
        "addlIdx": 55,
        "addlLines": [
            "Last updated: just now", "Additional features", "Daily included routine runs",
            "You haven't run any routines yet", "0 / 15", "Usage credits",
            "Turn on usage credits to keep using Claude if you hit a limit. Learn more",
            "$4.11 spent", "Resets Jun 1"
        ],
        "extraDebug": {…}
    },
    "meters": [ … ]
}
```

`_debug` was added in commit `0bc5ed0` and **removed** in commit `347276a` ("fix(pass2): … background.js: remove _debug field and its console.log from all payloads") on 2026-05-16 — three days ago. Every POST since then has merged `{**prev_with_debug, **body_without_debug}` → `_debug` survives.

### Why it matters

- **Cache grows monotonically.** The example above is benign (one nested dict, ~9 strings). But any field the Chrome extension ever wrote stays. Over years of releases the cache could carry rotated-out keys.
- **Forward-compat trap.** If 0.11.X adds a `_foo` field with a typo and 0.11.Y fixes the typo, the typo'd version of `_foo` persists alongside the fixed one. Both get serialized on every write.
- **Local-attack vector.** Another Chrome extension or local process can POST any key. The validator doesn't reject unknown keys; merge keeps them. There's no rate limit on /update. CORS protects against drive-by web pages, but the bar to be "another local Chrome extension" is low (any extension with `host_permissions` for `127.0.0.1` ranges).

### Fix

Mirror the pattern already used for `_anthropic_status` (line 285-288):

```python
_VALID_TOP_KEYS = {
    'meters', 'plan', '_timestamp', 'timestamp', '_scrape_fail_count',
    '_anthropic_status', '_ext_version', '_period_lengths', '_schema',
    '_buffered_at', '_ext_version_mismatch',
}

# Strip unknown top-level keys before merge.
body = {k: v for k, v in body.items() if k in _VALID_TOP_KEYS}
prev = {k: v for k, v in prev.items() if k in _VALID_TOP_KEYS}
body = {**prev, **body}
```

Including `prev` in the filter is important — it cleans up old garbage on first write after the fix lands. (Otherwise pre-existing `_debug` and similar would still survive.)

Optional but tidy: reject unknown top-level keys in `_validate` (returns 422 with `unknown top-level key: <name>`). Keeps the chrome extension honest; gives a CI signal if a new field is introduced server-side without the allowlist being updated.

### Regression guard

Existing `test_validate.py` doesn't cover the merge step (only the validator). Add an integration test that POSTs a body with an unknown key, then asserts the unknown key is absent from the written cache. Could be a small fixture in `test_validate.py` that imports the full module and exercises `do_POST` against an in-memory tmp dir.

### Severity rationale

Medium because:
- Live demonstration of unbounded growth.
- The fix is one block of code.
- It's the symmetric counterpart to a fix already accepted for `_anthropic_status` — the codebase already endorses this pattern, just hasn't extended it to the top level.

Not High because the growth rate is "one POST per discarded key per release" — small in absolute terms, and a `rm ~/.cache/claude-usage/usage.json` self-heals.

---

## 4. PL‑1 — Single POST wipes `_period_lengths` (Medium, silent feature disable)

**File:** `server/usage-server.py:332-335`

```python
current_labels = {m.get('label') for m in body.get('meters', []) or [] if m.get('label')}
if current_labels:
    period_lengths = {k: v for k, v in period_lengths.items() if k in current_labels}
```

### What's wrong

The eviction filter is **unguarded against partial meter sets**. A POST whose `meters` array contains only one labelled meter (real-world malicious payload, or a buggy Chrome extension shipping a stripped scrape) sets `current_labels = {"that_one_label"}`, and the filter discards every other label's accumulated period.

### Confirmed live

Just now, against the maintainer's running server:

```
$ curl -s -X POST http://127.0.0.1:7331/update \
    -H 'Content-Type: application/json' \
    -d '{"meters": [{"pct": 50, "label": "fake-meter", "reset_minutes": 100}]}'
ok

$ python3 -c "import json; print(json.load(open('/home/will/.cache/claude-usage/usage.json'))['_period_lengths'])"
{'fake-meter': 100}
```

The legit `Current session: 295` and `All models: 9680` were wiped by a single POST. (Restored immediately afterward with another POST; the maintainer's next Chrome ext scrape will repopulate naturally.)

### Why it matters

`pacingPct` / `pacing_pct` both gate on `period_lens.get(label)` being truthy:

```js
const period = periodLens?.[meter.label];
if (rm == null || !period) return pct;          // ← falls back to raw pct
```

So when `_period_lengths` is wiped, pacing-based coloring **silently degrades to raw-pct coloring** for every meter except the one in the malicious POST. The user sees no error, no notification — just (in practice) every meter green/amber based on raw pct, even if pacing would have flagged critical. The label color reverts to "raw" thresholds that the user may or may not have tuned to.

Re-accumulation: each subsequent scrape sees the meter's `reset_minutes`, runs `period_lengths[label] = max(period_lengths.get(label, 0), rm)`. The first scrape after wipe records the *current* `reset_minutes` (which is *less than* the true period). So the first re-accumulated period is wrong — it's "time remaining" not "period length". The `max(…)` keeps the largest value seen; subsequent scrapes raise it monotonically toward the real period. **Full pacing accuracy returns only after observing a meter's reset (or a near-reset).** For a weekly bucket that takes ~7 days.

The 0.11.14 plan documents this trajectory under "out of scope" but doesn't mention the wipe vector.

### Fix

The eviction's intent is "drop stale labels Anthropic has renamed/removed". But that intent is structurally indistinguishable from "this POST has fewer meters than the last one" without additional signal. Two options:

**Option A (minimal):** Only evict on POSTs that look like a *full* scrape (i.e., the POST has a recognisable signature, e.g., `_timestamp` set AND `meters.length >= some_threshold`). Partial / status-only POSTs preserve the existing accumulator.

```python
# Only evict when this POST clearly carries the full meter set.
is_full_scrape = (
    body.get('_timestamp') is not None
    and len(body.get('meters', []) or []) >= 2  # claude.ai always shows ≥ 2
)
if current_labels and is_full_scrape:
    period_lengths = {k: v for k, v in period_lengths.items() if k in current_labels}
```

**Option B (stricter):** Add an `is_full_scrape` boolean to the Chrome extension's POST and gate eviction on it. Cleaner contract, but it ties a server change to a Chrome ext change.

Recommend A — it works against today's Chrome ext as a no-op and closes the wipe class.

### Regression guard

Add to `test_validate.py` (or a new `test_merge.py` that exercises do_POST against an in-memory tmp dir):

```python
def test_partial_post_does_not_wipe_period_lengths(...):
    # Seed cache with multi-meter period_lengths
    # POST a partial body with one fake meter
    # Assert prev period_lengths survive
```

### Severity rationale

Medium because:
- Demonstrated live with a one-line curl.
- The user-visible symptom is "pacing colors don't work for ~7 days until weekly resets", which is subtle and easy to miss.
- Fix is small and localized.

Not High because the attack surface is limited (CORS + localhost) and the recovery is automatic over time.

---

## 5. R‑1 — Race in `_autoScrapeIfEligible` (Low, idempotent at server)

**File:** `chrome-extension/background.js:470-486`

```js
async function _autoScrapeIfEligible(tabId, url) {
  if (url.split(/[?#]/, 1)[0] !== USAGE_URL) return;
  if (_fetching) return;                                        // ← check (sync)
  const { _scrape_tabs = [], _last_scrape_ts = 0 } =
      await chrome.storage.local.get(['_scrape_tabs', '_last_scrape_ts']);   // ← await
  if (_scrape_tabs.includes(tabId)) return;
  if (Date.now() - _last_scrape_ts < AUTO_DEBOUNCE_MS) return;
  _fetching = true;                                             // ← set (after await)
  try { await scrapeAndPost(tabId); }
  …
  finally { _fetching = false; }
}
```

### What's wrong

The `_fetching` flag is read before any `await` and written *after* `await chrome.storage.local.get(...)`. Two near-simultaneous events (e.g., `tabs.onUpdated` for `status: complete` and `tabs.onActivated` for tab focus — both can fire for the same `tab.id` on the same navigation) both:

1. Pass `if (_fetching) return` (flag still `false`).
2. Issue the `await storage.get(...)` — both suspend, both eventually resume.
3. Pass `_scrape_tabs.includes(tabId)` and the debounce check (both see the same `_last_scrape_ts = 0` if nothing has scraped yet).
4. Set `_fetching = true` (one redundantly).
5. Both call `scrapeAndPost(tabId)`.

`fetchUsage()` (line 350-466) doesn't have this issue: its check and set are both synchronous and adjacent, so the flag works as a mutex for *that* entry point.

### Why it matters

Double-scrape:
- Runs `chrome.scripting.executeScript` twice on the same tab (Chrome serializes per-tab → second waits for first; ~1 extra page-read cost).
- POSTs twice to the server. Server's writes are last-wins (atomic via tmp.replace), so cache integrity is preserved.
- Bumps `_last_scrape_ts` to the latest time → next legitimate scrape is debounced.
- No race in `chrome.storage.local.set({ _last_scrape_ts: Date.now() })`: those are queued separately, last write wins.

So functionally OK, but wasted work and one Chrome alarm cycle of debounce-shift.

### Fix

Re-check after the await:

```js
async function _autoScrapeIfEligible(tabId, url) {
  if (url.split(/[?#]/, 1)[0] !== USAGE_URL) return;
  if (_fetching) return;
  const { _scrape_tabs = [], _last_scrape_ts = 0 } =
      await chrome.storage.local.get(['_scrape_tabs', '_last_scrape_ts']);
  if (_fetching) return;                                        // ← re-check
  if (_scrape_tabs.includes(tabId)) return;
  if (Date.now() - _last_scrape_ts < AUTO_DEBOUNCE_MS) return;
  _fetching = true;
  …
}
```

Or, cleaner, lift `_fetching` set above the await:

```js
if (_fetching) return;
_fetching = true;
try {
  const { _scrape_tabs = [], _last_scrape_ts = 0 } =
      await chrome.storage.local.get(['_scrape_tabs', '_last_scrape_ts']);
  // … same checks; if we abort here, finally still clears _fetching
  …
} finally { _fetching = false; }
```

The second form widens the critical section but is simpler — and is what `fetchUsage()` already does.

### Severity rationale

Low. Idempotent at the server level, and the second-scrape "leaks" into the debounce window so it doesn't compound. Worth fixing because the fix is two lines and the pattern is a textbook async-mutex bug that another reviewer would flag in any future pass.

---

## 6. WP‑1 — Weekly-bucket false-positive on pacing (Low–Medium, design tradeoff)

**Files:** `gnome-extension/extension.js:86-100`; `server/generate-icon.py:82-106`

### What's wrong

The 0.11.14 plan acknowledged the tradeoff explicitly:

> The weekly bucket loses ~82 min of suppression — but at minute 16 of a week, raw pct will be small enough that pacing rarely crosses 90 unless usage is genuinely extreme.

Math: at minute 16 of a 7-day weekly (10080 min), pacing = `pct × 630`. Threshold-critical default is 90, so pacing crosses critical at:

| Time into week | `pct` to trip critical (default thresh=90) |
|---|---|
| 16 min | 0.14% |
| 30 min | 0.27% |
| 60 min | 0.54% |
| 5 hours | 1.34% |
| 1 day | 6.4% |

The first row is striking: a single non-trivial query in the first 16 minutes of a fresh week already paces > critical. The fifth row: using 1.34% of weekly in 5 hours = 6.4% per day = within normal Pro usage. So pacing reports critical on **completely normal Pro-tier weekly usage** for the first ~24 hours of every week.

### Confirmed analytically

The plan's claim "raw pct will be small enough that pacing rarely crosses 90 unless usage is genuinely extreme" is incorrect when carried out arithmetically. The 15-min floor is well-calibrated for the 5h session bucket (15/300 = 5% elapsed denominator) but vastly under-calibrated for the 7d weekly (15/10080 = 0.15% denominator).

### Why it matters

The fix that motivated 0.11.14 (the 19:40 incident) was exactly this false-positive class: usage that "feels normal" should not pace as red. The fix closed the session-bucket case. The weekly-bucket case is structurally the same problem.

In practice the impact is bounded — the *raw pct* on the weekly bucket stays small, so the *displayed* number in the popup looks fine. But the panel label color (`pacing >= tCrit ? panelCrit : ...`) goes red, and the **dock icon flips to broken-tier red** if pacing eventually crosses other thresholds. Notifications fire (rate-limited but still confusing).

### Fix

One of:

**A.** Period-scaled floor: `if (elapsed < max(15, period * 0.05)) return pct;`. Keeps the 15-min floor as a lower bound (protects short buckets) and adds a 5%-of-period upper bound (protects long buckets). For the 7d weekly: 5% of 10080 ≈ 504 min = 8.4h. So no pacing in the first 8h of a week, which matches "user has barely started; can't extrapolate".

**B.** Per-bucket floor configured via metadata. Anthropic's labels are stable (~3-5 known names); shipping per-label floors is feasible. More code than A.

**C.** Cap pacing display at 200%. Doesn't fix the false-positive, just makes the toast less weird. Cosmetic.

Recommend A — minimal change, semantically defensible, single-source-of-truth.

### Regression guard

`test_pacing.py` already covers the 16-min weekly case as accepting `> 1000` pacing. The fix would flip that test's expectation. Adding parametrized cases over (period, elapsed_min, pct, expected_paced_or_not) makes the change visible.

### Severity rationale

Low-Medium. The plan documented this as "acceptable" but the math wasn't carried through. Worth revisiting in the next minor release; not a blocker.

---

## 7. D‑1 — `update_desktop()` comment is wrong about Icon= safety (Low)

**File:** `server/tooltip.py:108-127`

```python
def update_desktop(meters, icon_path=None, scrape_ts=None):
    """…
    icon_path=None (60 s tick): targeted Name=-only substitution via re.sub
    so we never clobber an Icon= written by a concurrent generate-icon.py.
    …"""
    if not DESKTOP.exists():
        return
    name = format_tooltip(meters, anchor_ts=scrape_ts).replace('\n', r'\n')
    tmp = DESKTOP.with_suffix(f'.desktop.tmp.{os.getpid()}.{time.time_ns()}')
    if icon_path is None:
        text = DESKTOP.read_text()                                # ← read
        new_text = re.sub(r'^Name=.*$', f'Name={name}', text, flags=re.MULTILINE)
        if new_text == text:
            return
        tmp.write_text(new_text)
    else:
        …
    tmp.replace(DESKTOP)                                          # ← replace
```

### What's wrong

The unique-tmp scheme (`.tmp.PID.NS`) prevents two writers from truncating each other's *tmp file*. But the read-modify-write of DESKTOP itself is not atomic:

1. 60s-tick reads DESKTOP (state v1: `Name=old, Icon=icon-1`).
2. generate-icon.py runs, writes its own tmp (with `Name=newer, Icon=icon-2`), `tmp.replace(DESKTOP)` → DESKTOP is now state v2.
3. 60s-tick (which has v1 in memory) computes `new_text` by `re.sub`-ing v1, then writes its tmp (`Name=updated, Icon=icon-1`), `tmp.replace(DESKTOP)`.

End state: DESKTOP has `Name=updated, Icon=icon-1`. The new icon path written by generate-icon.py was reverted to the old one. The comment's claim "we never clobber an Icon=" is structurally false.

### Why it matters

Self-heals: on the next POST cycle (~7 min), generate-icon.py runs again, writes fresh Name+Icon, no concurrent 60s-tick → DESKTOP is correct. Dock launcher shows a stale icon for up to 7 min after a race fires.

How often? Window is ~ms between the 60s-tick's `read_text()` and `tmp.replace()`. generate-icon.py runs on every POST scrape (Chrome's 7-min alarm) AND on tier transitions (GNOME ext 30s tick). In any given hour:
- 60s-ticks: 60
- POST-driven generate-icon.py: ~8 (7-min Chrome alarm)
- Tier-transition generate-icon.py: rare (usually 0)

Coincidence probability is low but not zero. Reported visible symptom would be "dock icon stayed stale for a few minutes after a tier transition".

### Fix

Either:
- Use fcntl flock around the read-modify-write.
- Always do a full read-parse-write (don't use the Name=-only shortcut). Costs a few microseconds per tick.
- Spawn an atomic `Name=`-only mutation via a helper that re-reads Icon= just before writing.

The third is the most surgical:

```python
if icon_path is None:
    text = DESKTOP.read_text()
    new_text = re.sub(r'^Name=.*$', f'Name={name}', text, flags=re.MULTILINE)
    if new_text == text:
        return
    # Re-read Icon= just before write so a concurrent generate-icon.py's
    # write isn't reverted by our cached copy of the file.
    fresh = DESKTOP.read_text()
    fresh_icon = re.search(r'^Icon=.*$', fresh, flags=re.MULTILINE)
    if fresh_icon:
        new_text = re.sub(r'^Icon=.*$', fresh_icon.group(0), new_text, flags=re.MULTILINE)
    tmp.write_text(new_text)
```

Still racy at the system-call boundary, but the window collapses from ~ms to ~µs. With flock it'd be airtight.

### Severity rationale

Low. Self-heals within 7 min, no data loss, no security impact. Worth flagging because (a) the comment claims a property that isn't actually guaranteed and (b) future code that depends on the comment's claim would break in subtle ways.

---

## 8. D‑2 — No startup icon refresh (Low)

**File:** `server/usage-server.py:476-485`

```python
if __name__ == '__main__':
    _sweep_orphan_tmps()
    server, port = _bind()
    _write_port_file(port)
    print(f"Claude Usage server listening on 127.0.0.1:{port}", flush=True)
    threading.Thread(target=_tooltip_tick, daemon=True).start()
    try:
        server.serve_forever()
    …
```

### What's wrong

After server boot, the dock icon is whatever was last written to `~/.cache/claude-usage/icon-*.png`. The icon refreshes only when:
1. The server processes a POST (chrome alarm fires, ~7 min cadence) → spawns generate-icon.py.
2. The GNOME extension's 30s tick fires on a tier transition.

If Chrome isn't running (Chrome alarm doesn't fire) and the GNOME extension is disabled / not yet enabled (no 30s tick), the dock icon stays at whatever was rendered at last shutdown — indefinitely.

The maintainer's TF‑1 (deferred) sits adjacent: the `.desktop` Icon= line holds a per-nanosecond absolute path that can vanish under `rm -rf ~/.cache/claude-usage`. If TF‑1 self-heals "within 60 s", it's via the tooltip_tick — but tooltip_tick (line 396-410) only writes the Name=, never the Icon= path. So the .desktop's stale Icon= is *not* repaired by the 60s tick.

Pair this with D‑2: server reboot → tooltip_tick repairs Name= but Icon= reverts to whatever's on disk → if the icon file was deleted, the launcher shows a broken-icon glyph.

### Fix

Spawn one generate-icon.py at server startup if a cache exists:

```python
if __name__ == '__main__':
    _sweep_orphan_tmps()
    server, port = _bind()
    _write_port_file(port)
    print(f"Claude Usage server listening on 127.0.0.1:{port}", flush=True)
    # Refresh the dock icon on startup so a power cycle / service restart
    # repairs Icon= immediately rather than waiting for the next Chrome alarm.
    if GENERATE_ICON and OUTPUT.exists():
        subprocess.Popen([sys.executable, str(GENERATE_ICON)], stdout=subprocess.DEVNULL)
    threading.Thread(target=_tooltip_tick, daemon=True).start()
    …
```

Costs one fork+exec at startup. Same script the POST handler invokes — no new code path.

### Severity rationale

Low. Common case (Chrome running) self-heals within 7 min. Only matters in "service restarted without Chrome active" — uncommon. Worth doing because the cost is one line and it'd close TF‑1's "60 s self-heal" gap explicitly (instead of relying on the next happenstance generate-icon.py).

---

## 9. N‑1 — Critical-pacing notification text (Info)

**File:** `gnome-extension/extension.js:377-380`

```js
Main.notify('Claude Usage',
    `⚠ ${critMeter.label} is at ${Math.round(critPacing)}% pacing`);
```

`critPacing` is uncapped; for a weekly bucket at minute 30 with 1% used it'd be `pct × 336 = 336`. The toast reads:

> Claude Usage
> ⚠ All models is at 336% pacing

The user has no frame for "336% pacing". "100% means on pace; >100 means over pace" is documented in the source comment but not surfaced.

### Fix

Format the pacing differently or include the contextual hint:

```js
const display = critPacing > 200 ? '>200' : Math.round(critPacing);
Main.notify('Claude Usage',
    `⚠ ${critMeter.label} on pace for ${display}% by reset`);
```

"on pace for 336% by reset" frames it as a forecast rather than a current state.

### Severity rationale

Info. Cosmetic; doesn't affect correctness.

---

## 10. V‑3 — Validator accepts empty-string keys/labels (Info)

**File:** `server/usage-server.py:160-162`

```python
for k, v in pl.items():
    if not isinstance(k, str) or len(k) > MAX_STR_LEN:
        return f"'_period_lengths' keys must be strings ≤ {MAX_STR_LEN} chars"
```

Same for `meters[i].label` via `_bounded_str` (which checks max length but not min).

Empty strings pass. The empty-string label then feeds the `current_labels` set in PL‑1's eviction filter (line 332-335). A meter with `label: ""` could pollute period_lengths and contribute to the wipe.

### Fix

```python
if not isinstance(k, str) or not k or len(k) > MAX_STR_LEN:
```

(Same for meter labels via a length-min in `_bounded_str` or an inline check.)

### Severity rationale

Info. Requires a writer that emits empty-string keys, which neither the current Chrome ext nor any historical version has done. Worth tightening alongside the V‑2 / PL‑1 fixes.

---

## 11. I‑1 — `install.sh` leaks stale files on re-install (Info)

**File:** `install.sh:107-125`

```bash
cp "$REPO_DIR/server/usage-server.py" "$SERVER_DIR/"
cp "$REPO_DIR/server/generate-icon.py" "$SERVER_DIR/"
cp "$REPO_DIR/server/tooltip.py" "$SERVER_DIR/"
…
cp -r "$REPO_DIR/chrome-extension/." "$SERVER_DIR/chrome-extension/"
rm -rf "$SERVER_DIR/chrome-extension/test"
```

### What's wrong

`cp` doesn't remove files in the destination that are absent from the source. If `server/oldfile.py` existed in v1 and was renamed/removed in v2, the old file persists in `$SERVER_DIR` after running install.sh against v2. Same for chrome-extension/. Unlike dpkg-managed installs, install.sh has no file manifest.

### Why it matters

Mostly housekeeping. The old file is dormant — nothing imports it. But it can confuse `grep`-driven debugging ("I edited this file but my change didn't take"). And it could in theory cause a stale module to be importable as a fallback if any path is misconfigured.

### Fix

Either `rsync --delete` (overkill, adds a dep), or maintain a static known-files list and clean up unknowns:

```bash
# Drop any pre-existing entries we don't own in this version
find "$SERVER_DIR" -maxdepth 1 -type f ! -name 'usage-server.py' \
    ! -name 'generate-icon.py' ! -name 'tooltip.py' ! -name 'claude-usage-status' \
    -delete
```

Lower-friction: nuke and recreate.

```bash
rm -rf "$SERVER_DIR"
mkdir -p "$SERVER_DIR"
cp …
```

Slightly noisy (user keeps no state under there) but safe — the cache and gsettings live elsewhere.

### Severity rationale

Info. Source installs are a minority path; dpkg handles the .deb case correctly.

---

## 12. What Was Re-Verified (and Found Holding)

- **V‑2-style cache-trust pattern.** Re-checked the merge logic for `_anthropic_status` (line 285-288) — the known-keys filter works correctly and is structurally what V‑2 wants at the top level.
- **TS‑1's ±1-year bound.** Probed with `inf`, `nan`, and negative numbers — all rejected. The fix is robust.
- **Race in `do_POST`.** Confirmed `HTTPServer` is single-threaded (not `ThreadingHTTPServer`), so concurrent POSTs don't fight over the tmp file. No race there.
- **Pacing JS↔Python parity.** Compared `pacingPct` (extension.js:86-100) and `pacing_pct` (generate-icon.py:82-106) line-by-line. Both implement the same 15-min floor; both fall back to raw pct on missing data; both have identical early-returns. Hand-synced, as TODO.md notes — drift risk remains, but state is currently parity.
- **Test coverage for 0.11.14 pacing fix.** All 13 boundary cases pass. The XDG_DATA_HOME stub (test_pacing.py:31-35) correctly bypasses generate-icon.py's BASE_ICON discovery.
- **Live-smoke test.** test-deb-live.sh exercises both current-shape and old-shape POSTs, verifies cache write and `_schema:1` stamp. Coverage matches the validator's backcompat clause.
- **U‑1's fix.** `claude-usage-setup` and `install.sh` both now use `enable` + `restart` (lines 28-30 / 139-145). The maintainer's running 0.11.13 reflects the manifest-derived VERSION rather than 0.11.8. **U‑1 is closed.**

---

## 13. Recommended Order of Fixes

1. **TH‑1** (one-commit, three-file edit; closes a user-facing correctness issue today).
2. **V‑2** + **PL‑1** + **V‑3** as one batch — they're three angles on the same `body = {**prev, **body}` merge, and the fixes for all three live within 20 lines of usage-server.py.
3. **R‑1** — two-line patch to `_autoScrapeIfEligible`; closes a textbook async-race.
4. **D‑2** — one line at server startup; pairs naturally with the pending TF‑1.
5. **D‑1** — small surface, low impact, fixable opportunistically.
6. **WP‑1** — design-discussion finding; ship one period-scaled floor change in a separate release.
7. **N‑1**, **I‑1** — opportunistic polish.

If targeting one release: 1+2+3+4 close everything Medium and the most surface-area Low for ~50 LoC.

---

## Appendix A — Files reviewed

| File | LoC | Notes |
|---|---|---|
| `chrome-extension/background.js` | 542 | R‑1 finding; otherwise solid |
| `chrome-extension/scraper.js` | 116 | Mirror of background.js inline scrape; lint-covered |
| `chrome-extension/manifest.json` | 38 | Host permissions match server PORT_RANGE |
| `chrome-extension/test/scraper.test.js` | 331 | Good coverage of doScrape; misses parseResetMinutes edge cases like leap-year crossings |
| `gnome-extension/extension.js` | 596 | TH‑1 comment drift; pacingPct logic clean |
| `gnome-extension/prefs.js` | 168 | setTimeout usage works on GJS ≥ 1.74; project supports GNOME 45+, all clear |
| `gnome-extension/schemas/*.gschema.xml` | 90 | Default values match `DEFAULTS` in generate-icon.py |
| `server/usage-server.py` | 485 | V‑2 / PL‑1 / V‑3 findings; otherwise tight |
| `server/generate-icon.py` | 286 | pacing_pct matches extension.js by hand |
| `server/tooltip.py` | 139 | D‑1 finding (comment vs reality) |
| `server/tests/*` | 442 | Strong validator + pacing coverage; missing merge integration tests |
| `scripts/claude-usage-status.py` | 127 | TH‑1 finding (10 vs 15) |
| `scripts/lint-scraper-parity.py` | 105 | Works as intended; doesn't extend to pacing parity (deferred TODO) |
| `install.sh` | 172 | I‑1 finding |
| `packaging/*` | ~400 | All clear; postinst's `enable + restart` closes U‑1 |
| `.github/workflows/release.yml` | 151 | Node 24 migration good; weekly cache-bust correct |
| `Taskfile.yml` | 143 | All tasks resolve cleanly |

## Appendix B — Findings cross-reference

| ID | File:Line | Test added? | Live evidence |
|---|---|---|---|
| TH‑1 | extension.js:392,410 + status:42-46 + MANUAL:51 | None proposed (lint suggested) | Grep across three files |
| V‑2 | usage-server.py:314 | Should add merge-test | `_debug` in live cache |
| PL‑1 | usage-server.py:332-335 | Should add merge-test | `curl` wiped period_lengths |
| R‑1 | background.js:472-486 | Hard to unit-test JS races | Pattern review |
| WP‑1 | extension.js:98 / generate-icon.py:104 | test_pacing.py:102 would flip | Arithmetic check |
| D‑1 | tooltip.py:108-127 | Hard to unit-test races | Logic review |
| D‑2 | usage-server.py:476-485 | Smoke test could check | Code review |
| N‑1 | extension.js:377-380 | Visual only | n/a |
| V‑3 | usage-server.py:160-162 | One-line addition to test_validate | Probed |
| I‑1 | install.sh:107-125 | None | Logic review |
