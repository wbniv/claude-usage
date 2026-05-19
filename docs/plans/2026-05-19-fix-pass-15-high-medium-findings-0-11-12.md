# Fix Pass-15 High + Medium Findings → 0.11.12

## Context

Pass-15 code review ([docs/investigations/2026-05-19-code-review-pass15.md](../../SRC/claude-usage/docs/investigations/2026-05-19-code-review-pass15.md)) surfaced **1 High + 2 Medium** findings against the just-shipped 0.11.11. This plan implements all three and bumps to 0.11.12.

**Why these three together:** U‑1 is the single most leverage-bearing fix in the review — without it, the maintainer's `/hello` was reporting `0.11.8` server code at review-time despite a 0.11.11 .deb on disk (i.e. *every* prior fix may not actually be deploying to live machines after `apt install`). TS‑1 silently disables stale-data detection with a single curl line. T‑8 raises Python tracebacks where the JS twins quietly return `null`. Shipping them together as 0.11.12 closes the deploy-pipeline gap *and* the validator-edge cases in one batch.

**What does not ship in 0.11.12:** the four Lows (HM‑2, SC‑2, I‑2) and three Infos from pass-15. Defer to a future polish batch — pass-15's recommended action order keeps them ranked.

---

## Files modified

### 1. `packaging/claude-usage-setup` — U‑1

**Lines 28-30** currently:

```bash
systemctl --user daemon-reload
systemctl --user reset-failed claude-usage-fetch.service 2>/dev/null || true
systemctl --user enable --now claude-usage-fetch.service
```

`enable --now` is documented to *start* the unit on first enable but is a **no-op** against an already-running service. Result: on .deb upgrade, the running 0.11.x server keeps running old code; the new code on disk is only loaded on the next manual restart or reboot.

**Fix** — split `enable --now` into explicit `enable` + `restart`, so both fresh-install and in-place-upgrade hit the running path:

```bash
systemctl --user daemon-reload
systemctl --user reset-failed claude-usage-fetch.service 2>/dev/null || true
systemctl --user enable claude-usage-fetch.service
# `restart` works whether the service is running (re-execs new code) or stopped
# (equivalent to `start`). `enable --now` would be a no-op against a running
# unit, leaving the upgraded user on stale code — the very V-2-style drift
# pass-14 thought it had closed.
systemctl --user restart claude-usage-fetch.service
```

### 2. `install.sh` — U‑1 (source-install parity)

**Line 140** has the same `enable --now` pattern; apply the same `enable` + `restart` split. Comment block at 136-139 about reset-failed stays.

### 3. `server/usage-server.py` — TS‑1

**Lines 166-170** currently bound `_timestamp` only against type:

```python
ts = body.get('_timestamp') or body.get('timestamp')
if ts is not None and (isinstance(ts, bool) or not isinstance(ts, (int, float))):
    return "'_timestamp' must be a number"
```

The unbounded path lets `_timestamp: 99999999999` (year 5138) into the cache, where `extension.js:380` computes a *negative* age, every stale/broken-tier threshold evaluates false, and the indicator pins to NORMAL forever.

**Fix** — bound plausibility (±1 year past, +1 day future). The asymmetric window keeps backfill scenarios working while clamping browser-clock skew:

```python
ts = body.get('_timestamp') or body.get('timestamp')
if ts is not None:
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return "'_timestamp' must be a number"
    # Translate legacy `timestamp` (epoch-ms) to seconds for the bound check.
    # `_timestamp` (current schema) is already seconds. The do_POST assignment
    # at line 296 handles the same translation downstream.
    ts_s = ts / 1000 if (body.get('timestamp') and not body.get('_timestamp')) else ts
    now = time.time()
    # ±1 year past, +1 day future — anything wider is clock skew, not a
    # legitimate write to persist. Closes the silent-stale-data-disable
    # attack TS-1 (pass-15 review §3): a year-5138 timestamp makes age
    # negative, which bypasses every stale/broken threshold in extension.js.
    if not (now - 365 * 86400 < ts_s < now + 86400):
        return "'_timestamp' implausibly far from server time"
```

Note: `time` is already imported at line 4.

### 4. `server/tooltip.py` — T‑8

**Lines 42-50** currently:

```python
m = re.match(r'[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)', reset)
if m:
    day, h, mn, ap = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    if day not in WD_MAP:
        return None
    if ap == 'PM' and h != 12: h += 12
```

The three JS twins (`chrome-extension/scraper.js:22`, `background.js:148`, `gnome-extension/extension.js:44-49`) all guard `1 <= h <= 12` and `0 <= mn <= 59`. Python side lacks the check; a malformed reset string falls through to `datetime.replace(hour=25, minute=99, …)` → `ValueError`.

**Fix** — add the same range check (3-line insert, matches JS guard exactly):

```python
m = re.match(r'[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)', reset)
if m:
    day, h, mn, ap = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    if day not in WD_MAP:
        return None
    # Parity with JS twins (scraper.js, background.js, extension.js) which all
    # return null on out-of-range. Without this, `datetime.replace(hour=25,
    # minute=99)` raises ValueError, dumping a Python traceback to the journal
    # from the _tooltip_tick / generate-icon.py outer try/except.
    if not (1 <= h <= 12 and 0 <= mn <= 59):
        return None
    if ap == 'PM' and h != 12: h += 12
```

### 5. `server/tests/test_validate.py` — TS‑1 coverage

Add new test cases to the `_timestamp` section (currently lines 185-201). The existing tests cover type/bool rejection; add bound coverage:

```python
def test_timestamp_plausibility_bound():
    """TS-1: a wildly-skewed timestamp would pin extension.js's age calc
    negative, silently disabling stale-data detection. Validator now bounds
    to ±1 year past, +1 day future."""
    import time
    now = int(time.time())
    # In-bounds
    assert _validate({'_timestamp': now}) is None
    assert _validate({'_timestamp': now - 86400}) is None       # 1 day ago
    assert _validate({'_timestamp': now - 30 * 86400}) is None  # 30 days ago
    # Future-bound: +1 day OK, +1 week not
    assert _validate({'_timestamp': now + 86400 - 1}) is None
    err = _validate({'_timestamp': now + 7 * 86400})
    assert err and '_timestamp' in err
    # Year-5138 attack vector from pass-15 live evidence
    err = _validate({'_timestamp': 99999999999})
    assert err and '_timestamp' in err
    # Pre-2024 ancient timestamp
    err = _validate({'_timestamp': 1000000000})  # 2001
    assert err and '_timestamp' in err
    # Legacy `timestamp` (epoch-ms) form is also bounded
    err = _validate({'timestamp': 99999999999000})
    assert err and '_timestamp' in err
```

### 6. Version bumps — 0.11.11 → 0.11.12

- `packaging/control` line 2: `Version: 0.11.11` → `Version: 0.11.12`
- `chrome-extension/manifest.json` line 4: `"version": "0.11.11"` → `"version": "0.11.12"`
- `server/usage-server.py`: derives via V‑2 from manifest — no edit needed
- `gnome-extension/metadata.json`: not bumped here; `task release` auto-increments on tag push

---

## Out of scope (deferred to next batch)

Pass-15 Lows + Infos — none material for 0.11.12:
- **HM‑2** (Content-Length ValueError) — journal noise only
- **SC‑2** (textContent vs innerText) — hypothetical, bounded by 30 s deadline
- **I‑2** (Wayland enable-success message) — cosmetic
- **SC‑3, PR‑1, TF‑1, L‑3** — info-only

The "optional follow-up" from pass-15 §2 (have `claude-usage-status` warn when `/hello`'s version differs from on-disk manifest) is *also deferred* — it would have caught U‑1 sooner, but the U‑1 fix itself closes the underlying drift and the diagnostic-warning improvement can land standalone in a later polish batch.

---

## Verification

1. **Parse checks:**
   ```
   python3 -m py_compile server/usage-server.py server/tooltip.py
   bash -n install.sh packaging/claude-usage-setup
   ```

2. **Unit tests pass:**
   ```
   task test
   ```
   New `test_timestamp_plausibility_bound` must pass; existing `test_timestamp_accepts_int_and_float` adjusted if needed (current cases at 1700000000 = 2023, may now fall outside the past-bound; either use `time.time()`-relative values or widen past-bound to e.g. 2 years).

   **NOTE during implementation:** the existing `test_timestamp_accepts_int_and_float` uses literal `1700000000` (Nov 2023) which is < 1 year ago at *write time* of pass-14 but > 1 year ago at runtime today (2026-05-19). The new bound rejects it. Update to use `time.time()` so the test stays correct over wall-clock time.

3. **TS‑1 live check** after restart with `task install` or after .deb upgrade:
   ```
   PORT=$(cat ~/.cache/claude-usage/port)
   curl -s -w "\nHTTP=%{http_code}\n" -X POST "http://127.0.0.1:$PORT/update" \
     -H 'Content-Type: application/json' \
     -d '{"_timestamp": 99999999999, "_ext_version": "0.11.12"}'
   # expect: HTTP=422 with body "'_timestamp' implausibly far from server time"
   ```

4. **T‑8 live check** (Python REPL or one-liner):
   ```
   python3 -c "
   import sys; sys.path.insert(0, 'server')
   from tooltip import parse_reset
   assert parse_reset('Resets Tue 25:99 AM') is None  # would raise pre-fix
   assert parse_reset('Resets Tue 2:30 PM') is not None  # happy path unchanged
   print('T-8 OK')"
   ```

5. **U‑1 live check** — the full upgrade-doesn't-restart scenario:
   ```
   # On a machine with 0.11.11 service running:
   curl -s http://127.0.0.1:$(cat ~/.cache/claude-usage/port)/hello
   # expect (pre-fix repro): {"app": "claude-usage", "version": "0.11.11"}

   # Apply this batch's changes, build .deb, install:
   task build
   sudo apt-get install -y --reinstall ./dist/claude-usage_0.11.12_all.deb

   # Without re-running claude-usage-setup manually:
   curl -s http://127.0.0.1:$(cat ~/.cache/claude-usage/port)/hello
   # expect: {"app": "claude-usage", "version": "0.11.12"}
   # If still 0.11.11 → U-1 fix didn't take, postinst's restart path is broken
   ```

6. **U‑1 negative test** — fresh install path still works:
   ```
   # In a fresh user (cu-smoke) via packaging/test-deb-live.sh — already
   # exercises `enable --now` equivalent path. Verify the new enable+restart
   # sequence still binds + writes port file + accepts POSTs.
   sudo bash packaging/test-deb-live.sh cu-smoke
   # expect: existing "OK: live smoke test passed" output unchanged
   ```

7. **Version sync sanity:**
   ```
   grep '"version"' chrome-extension/manifest.json   # 0.11.12
   grep '^Version:' packaging/control                # 0.11.12
   # usage-server.py derives via V-2 — no literal to grep
   ```

---

## Commit shape

Two commits suggested:

1. **`fix(pass15): U-1 deploy gap + TS-1 timestamp bound + T-8 parser parity; bump 0.11.12`** — code + test + version-bump changes (5 files).
2. **`docs: pass-15 code review`** — the pass-15 review file itself (currently uncommitted at `docs/investigations/2026-05-19-code-review-pass15.md`).

Single bundled commit also fine — each finding's intent is captured in the inline comments.

---

## Critical files at a glance

| File | Lines | Finding | Change |
|------|-------|---------|--------|
| `packaging/claude-usage-setup` | 28-30 | U‑1 | `enable --now` → `enable` + `restart` |
| `install.sh` | 140 | U‑1 | same pattern |
| `server/usage-server.py` | 166-170 | TS‑1 | bound `_timestamp` to ±1 year past, +1 day future |
| `server/tooltip.py` | 42-50 | T‑8 | add `1 ≤ h ≤ 12 && 0 ≤ mn ≤ 59` guard |
| `server/tests/test_validate.py` | ~190 | TS‑1 | new `test_timestamp_plausibility_bound` + fix existing `test_timestamp_accepts_int_and_float` to use `time.time()` |
| `packaging/control` | 2 | release | bump 0.11.11 → 0.11.12 |
| `chrome-extension/manifest.json` | 4 | release | bump 0.11.11 → 0.11.12 |

Total diff estimate: ~45 lines across 7 files. Bounded; each change is independent (failure of one doesn't cascade).
