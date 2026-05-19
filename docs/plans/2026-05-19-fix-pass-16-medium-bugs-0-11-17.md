# Fix pass-16 Medium bugs → 0.11.17

## Context

Pass-16 code review ([`docs/investigations/2026-05-19-code-review-pass16.md`](../../SRC/claude-usage/docs/investigations/2026-05-19-code-review-pass16.md)) identified three Medium-severity bugs and one Info finding that lives in the same code. All three Mediums affect users today:

- **TH‑1** — `claude-usage-status` and `MANUAL.md` document the stale threshold as 10 min, but the extension flips to STALE at 15 min. Pass-13 A‑2 updated the extension's threshold but missed the three downstream consumers (the comment in extension.js itself, the diagnostic tool, and the user manual). The diagnostic is actively misleading.
- **V‑2** — `body = {**prev, **body}` shallow merge in usage-server.py has no top-level allowlist; any key the Chrome extension ever wrote persists in the cache indefinitely. Demonstrated live: maintainer's cache still carries `_debug` (removed in commit 347276a three days ago).
- **PL‑1** — `current_labels` eviction at usage-server.py:332-335 is unguarded against partial meter sets. A single POST with one fake meter wipes `_period_lengths` for every other label. Pacing-based color silently degrades to raw-pct coloring until re-accumulation (up to ~7 days for the weekly bucket).
- **V‑3** (bundled per user direction) — `_validate` accepts empty-string `_period_lengths` keys and `meters[i].label` values. Empty-string labels contribute to PL‑1's eviction wipe.

Target release: **0.11.17**. Single commit bundling all four fixes (matches the pass-15 pattern: `fix(pass15): U-1 + TS-1 + T-8; bump 0.11.12`).

## Approach

### Fix 1: TH‑1 — three text edits

| File | Line | Change |
|---|---|---|
| `gnome-extension/extension.js` | 392 | comment `//   stale  — age > 10 min` → `//   stale  — age > 15 min` |
| `scripts/claude-usage-status.py` | 45 | `elif ts_min > 10:` → `elif ts_min > 15:` (message text already says "extension flips to STALE at this point" — still accurate) |
| `MANUAL.md` | 51 | `No fresh data in 10 min (~1.5 missed fetches)` → `No fresh data in 15 min (~2 missed fetches)` |

The `> 20` broken-tier reference in `claude-usage-status.py:42` is correct — no change.

### Fix 2: V‑2 + PL‑1 in `server/usage-server.py`

**Approach:** Minimal-change, no refactor. Add a top-level whitelist constant, filter `prev` and `body` before the existing shallow merge, and gate the eviction on an `is_full_scrape` heuristic. Keeps the diff small and reviewable; matches the existing `_anthropic_status` known-keys filter pattern at line 285-288 (codebase already endorses this approach).

**Whitelist (verified against background.js end-to-end + Explore agent):**

```python
# Top-level keys we recognise. Anything else gets stripped before merge —
# closes V-2's monotonic-cache-growth class (e.g. _debug from a previous
# Chrome ext version stayed in cache for days after the ext stopped sending it).
# Includes both chrome-emitted keys and server-written keys (_schema,
# _ext_version_mismatch) that should survive across the next POST's merge.
_VALID_TOP_KEYS = {
    'meters', 'plan',
    '_timestamp', 'timestamp',                     # 'timestamp' is legacy ms; converted to _timestamp at write
    '_scrape_fail_count',
    '_anthropic_status',
    '_ext_version', '_ext_version_mismatch',
    '_period_lengths',
    '_schema',
    '_buffered_at',                                # written by Chrome ext during offline-buffer flush
}
```

**Filter step (added just before existing line 305 `prev_pl = prev.get(...)`):**

```python
# V-2: strip unknown top-level keys from both sides so the {**prev, **body}
# merge can't propagate garbage indefinitely. Symmetric to _anthropic_status's
# known-keys filter above.
prev = {k: v for k, v in prev.items() if k in _VALID_TOP_KEYS}
body = {k: v for k, v in body.items() if k in _VALID_TOP_KEYS}
```

**Eviction guard (replaces existing line 332-335):**

```python
# Evict labels no longer in the current meter set — but ONLY on full scrapes,
# so a partial/malicious POST with one fake meter can't wipe the accumulator
# (PL-1). claude.ai always ships ≥ 2 meters on the usage page, so requiring
# ≥ 2 labelled meters + a fresh _timestamp is a reliable "full scrape" signal.
current_labels = {m.get('label') for m in body.get('meters', []) or [] if m.get('label')}
is_full_scrape = (
    body.get('_timestamp') is not None
    and len(body.get('meters', []) or []) >= 2
)
if current_labels and is_full_scrape:
    period_lengths = {k: v for k, v in period_lengths.items() if k in current_labels}
```

### Fix 3: V‑3 in `server/usage-server.py::_validate`

Two-line additions:

```python
# In _bounded_str — line 77 area
def _bounded_str(v, field, allow_empty=True):
    if v is None:
        return None
    if not isinstance(v, str):
        return f"{field} must be a string or null"
    if not allow_empty and not v:
        return f"{field} must be non-empty"
    if len(v) > MAX_STR_LEN:
        return f"{field} exceeds {MAX_STR_LEN} chars"
    return None
```

Then per-callsite for meter labels:

```python
# usage-server.py:108 area — meter label must be non-empty
for k in ('label',):
    err = _bounded_str(m.get(k), f"meters[{i}].{k}", allow_empty=False)
    if err: return err
for k in ('reset', 'spent', 'balance'):
    err = _bounded_str(m.get(k), f"meters[{i}].{k}")
    if err: return err
```

And `_period_lengths` key check at line 161:

```python
if not isinstance(k, str) or not k or len(k) > MAX_STR_LEN:
    return f"'_period_lengths' keys must be non-empty strings ≤ {MAX_STR_LEN} chars"
```

### Fix 4: Regression tests

**Per CLAUDE.md** ("propose a test that would catch it and include it in the same commit as the fix"). Three additions to `server/tests/test_validate.py`:

```python
# V-3 — empty-string rejection
def test_meter_label_must_be_non_empty():
    err = _validate({'meters': [{'pct': 50, 'label': ''}]})
    assert err and 'label' in err

def test_period_lengths_key_must_be_non_empty():
    err = _validate({'_period_lengths': {'': 100}})
    assert err and "'_period_lengths'" in err
```

**For V‑2 and PL‑1**, use a lightweight in-memory `do_POST` harness that mocks `send_response`/`wfile.write`/`end_headers` and exercises the full merge path against a tmpdir cache. Pattern adapted from the existing importlib bootstrap in `test_validate.py` (which already loads `usage-server.py` and stubs `tooltip`).

```python
# New test_merge.py — or extend test_validate.py with a __merge__ section
def _do_post(body, prev_cache=None, tmpdir=None):
    """Drive do_POST through a minimal in-memory harness.
    Returns the parsed cache content after the POST."""
    # Set _MOD.OUTPUT to a tmpdir path
    # Seed it with prev_cache if provided
    # Build a Mock handler with .headers, .rfile, .send_response, .wfile, etc.
    # Call _MOD.Handler.do_POST(mock_handler)
    # Read the resulting OUTPUT file, return parsed JSON
    ...

def test_unknown_top_level_keys_filtered_out():
    """V-2: a body with garbage keys does not propagate them to cache."""
    prev = {'meters': [{'pct': 50, 'label': 'A'}], '_debug': {'old': 'data'}}
    result = _do_post({'_scrape_fail_count': 1}, prev_cache=prev)
    assert '_debug' not in result          # garbage from prev was filtered
    assert '_scrape_fail_count' in result  # body key survived

def test_partial_post_does_not_wipe_period_lengths():
    """PL-1: a single-meter POST should NOT evict legit period_lengths."""
    prev = {
        'meters': [{'pct': 50, 'label': 'A'}, {'pct': 50, 'label': 'B'}],
        '_period_lengths': {'A': 295, 'B': 9680},
    }
    # Partial POST with one fake meter
    result = _do_post(
        {'meters': [{'pct': 0, 'label': 'fake'}]},
        prev_cache=prev,
    )
    assert 'A' in result['_period_lengths']
    assert 'B' in result['_period_lengths']

def test_full_scrape_does_evict_renamed_labels():
    """Eviction still fires on legit full scrapes (≥ 2 meters + _timestamp).
    Anthropic renaming a meter should still drop the old label."""
    prev = {
        'meters': [{'pct': 50, 'label': 'OldName'}],
        '_period_lengths': {'OldName': 100, 'AnotherOld': 200},
    }
    result = _do_post(
        {
            'meters': [
                {'pct': 50, 'label': 'NewName', 'reset_minutes': 100},
                {'pct': 50, 'label': 'OtherNew', 'reset_minutes': 200},
            ],
            '_timestamp': int(time.time()),
        },
        prev_cache=prev,
    )
    assert 'OldName' not in result['_period_lengths']
    assert 'AnotherOld' not in result['_period_lengths']
    assert 'NewName' in result['_period_lengths']
```

### Fix 5: Version bump (per project memory `project_version_locations.md`)

| File | Change |
|---|---|
| `packaging/control` | `Version: 0.11.16` → `Version: 0.11.17` |
| `chrome-extension/manifest.json` | `"version": "0.11.16"` → `"version": "0.11.17"` |

(The `gnome-extension/metadata.json` integer version bump is automated inside the `task release` flow, so no manual edit there.)

### Fix 6: TODO.md

Move the new entry to Done in reverse chronological order with the one-line summary (per CLAUDE.md "TODO done section" rule):

```
- [x] 2026-05-19 — Pass-16 M findings → 0.11.17 (TH-1 stale-threshold drift, V-2 top-level filter, PL-1 eviction guard, V-3 empty-string labels). [Plan](docs/plans/2026-05-19-fix-pass-16-medium-findings-0-11-17.md). Commit: `<sha>`.
```

(Also write a project-local plan file at `docs/plans/2026-05-19-fix-pass-16-medium-findings-0-11-17.md` mirroring this plan, per CLAUDE.md "Plan-first" rule.)

## Files to change

```
gnome-extension/extension.js                                              (TH-1)
scripts/claude-usage-status.py                                            (TH-1)
MANUAL.md                                                                 (TH-1)
server/usage-server.py                                                    (V-2, PL-1, V-3)
server/tests/test_validate.py                                             (V-3 cases + merge harness)
packaging/control                                                         (version bump)
chrome-extension/manifest.json                                            (version bump)
TODO.md                                                                   (Done entry)
docs/plans/2026-05-19-fix-pass-16-medium-findings-0-11-17.md              (new — project-local plan copy)
docs/investigations/2026-05-19-code-review-pass16.md                      (strike through closed findings)
```

## Existing utilities to reuse

- `_bounded_str` (server/usage-server.py:77) — already validates type and max-length; extend with `allow_empty` parameter for V-3.
- `_VALID_ANTHROPIC_KEYS` (server/usage-server.py:74) — pattern to mirror for `_VALID_TOP_KEYS`.
- importlib bootstrap in `test_validate.py` (lines 14-25) — already loads hyphenated `usage-server.py`; reuse the same pattern for the `do_POST` harness.

## Verification

1. **Unit tests pass:** `task test-validate` — new test cases pass alongside existing 44.
2. **Lint passes:** `task lint-scraper-parity` — should still pass (no scraper.js touched).
3. **Live V‑2 probe (post-fix):**
   ```bash
   curl -s -X POST http://127.0.0.1:7331/update \
       -H 'Content-Type: application/json' \
       -d '{"evil_key": "x"}'
   # Then:
   python3 -c "import json; print('evil_key' in json.load(open('/home/will/.cache/claude-usage/usage.json')))"
   # Expect: False
   ```
4. **Live PL‑1 probe (post-fix):**
   ```bash
   # Seed period_lengths via a normal scrape, then:
   curl -s -X POST http://127.0.0.1:7331/update \
       -H 'Content-Type: application/json' \
       -d '{"meters": [{"pct": 50, "label": "fake", "reset_minutes": 100}]}'
   python3 -c "import json; d=json.load(open('/home/will/.cache/claude-usage/usage.json')); print(d['_period_lengths'])"
   # Expect: original keys still present (fake-meter ignored for eviction purposes)
   ```
5. **TH‑1 diagnostic check:** Wait until a cache is 12 min old (or manually advance `_timestamp`), run `claude-usage-status`. Should NOT print "extension flips to STALE at this point" — should print the normal "present (12m ago, …)" line. At 16+ min, the stale message should fire (matching the panel actually flipping).
6. **MANUAL.md diff:** `task md -- MANUAL.md` — render and visually confirm the threshold text updated.
7. **`.deb` build + smoke test:** `task test-deb-fast` (or `test-deb` for the full path) — verify the new validator + merge logic survive packaging and a live POST cycle.
8. **Pass-16 review document:** strike through closed findings in section 1's table (TH-1, V-2, PL-1, V-3) per the convention from prior passes.

## Release flow

After verification passes:

```bash
git add <files>
git commit -m "fix(pass16): TH-1 stale-threshold + V-2 top-level filter + PL-1 eviction guard + V-3 empty labels; bump 0.11.17"
task release   # runs the preflight + tag-push + CI publish
```

The `task release` flow handles the gnome-extension integer-version bump, version-match guard (packaging/control ↔ chrome-extension/manifest.json), tag, and CI trigger.

## Out of scope (deferred)

- **WP‑1** (Low-Medium pacing false-positive on long buckets) — separate release; design discussion about period-scaled floor.
- **R‑1** (Low race in `_autoScrapeIfEligible`) — separate release; two-line patch.
- **D‑1, D‑2, N‑1, I‑1** — opportunistic polish, separate releases.
- **TF‑1** — deferred per existing TODO.md.
- **Cross-language threshold lint** — the named-constant fix in this plan handles same-file drift in extension.js, but the diagnostic tool (Python) and MANUAL.md (Markdown) can drift again. A `scripts/lint-thresholds.py` would catch this; not built here (premature for three callsites).
