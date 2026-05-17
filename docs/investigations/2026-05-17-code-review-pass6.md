# Code Review — Pass 6

**Date:** 2026-05-17
**Scope:** Independent comprehensive re-read of every source file after the pass‑5 fix batch (`296f868`, `3ccd289`, `b46cca0`), the pass‑5 code-quality cleanup (`893ccb7`), and the four feature stacks landed since pass 5: outage detection / icon tiers (`7371760`), auto‑scrape on user-opened usage tabs (`2f8913b`), in-process 60 s tooltip refresh (`3bf6160`, `0fc68c9`), and pacing-based meter colors with period inference (`0aa182f`).
**Prior art:** Pass 1 (`2026-05-16-code-review.md`), Pass 2, Pass 3, Pass 4, Pass 5.

---

## Method

Read every source file end-to-end with no assumptions carried from prior passes. Verified that all pass‑5 bug fixes (P5‑1 through P5‑7) and the closed code-quality items (CQ1, CQ2, CQ3, CQ4, CQ6, CQ7, CQ9) are still in place. Then focused on the four feature stacks listed above, since each one widened the surface area in ways the older passes could not have audited.

Files reviewed (full reads):
`chrome-extension/{background.js,manifest.json}`, `server/{usage-server.py,generate-icon.py,tooltip.py}`, `gnome-extension/{extension.js,prefs.js,metadata.json,schemas/*.gschema.xml}`, `scripts/claude-usage-status.sh`, `install.sh`, `Taskfile.yml`, `packaging/{build-deb.sh,build-chrome-zip.sh,test-deb-verify.sh,test-deb.Dockerfile,postinst,postrm,control,claude-usage-setup}`, `systemd/claude-usage-fetch.service`, `desktop/claude-usage.desktop`, `MANUAL.md`, `PRIVACY.md`.

Findings are anchored to precise `file:line` references and include reproducers or runtime traces where the failure mode isn't immediate from a read.

---

## Pass‑5 Findings — Verified Current Status

| ID | Description | Status |
|----|-------------|--------|
| BUG‑P5‑1 | `pct: true / false` bypasses int range check | ✓ Fixed — explicit `isinstance(pct, bool)` reject at `usage-server.py:56` |
| BUG‑P5‑2 | `_fetching` deadlock when `chrome.storage.local.get` throws | ✓ Fixed — outer `try/finally` wraps the whole body (`background.js:214–298`) |
| BUG‑P5‑3 | Negative `Content-Length` bypasses 256 KB cap | ✓ Fixed — `length <= 0 or length > 256 * 1024` at `usage-server.py:108` |
| BUG‑P5‑4 | Defensive sweep closes user-opened usage tabs | ✓ Fixed — storage‑tracked `_scrape_tabs` (`background.js:243–252, 292–295`) |
| BUG‑P5‑5 | Panel/popup desync at 0% Sonnet | ✓ Fixed — `_isSelectable` layered over `_isEligible` (`extension.js:364–367`) and used in scroll handler + `_getPrimary` |
| BUG‑P5‑6 | Scroll wheel UP/DOWN both advance forward | ✓ Fixed — `delta = dir === UP ? -1 : 1` (`extension.js:126–128`) |
| BUG‑P5‑7 | Plan regex matches "Pro tip:" etc. | ✓ Fixed — anchored regex with optional "Plan: " prefix (`background.js:91`) |
| CQ1 — subprocess zombies | ✓ `signal.signal(SIGCHLD, SIG_IGN)` at `usage-server.py:12` |
| CQ2 — release dirty‑tree guard | ✓ `git diff --quiet HEAD` block in `Taskfile.yml:88–92` |
| CQ3 — `_loadData` silent errors | ✓ `logError(e, 'ClaudeUsage: failed to read cache')` at `extension.js:223` |
| CQ4 — Pillow `LANCZOS` forward-compat | ✓ `getattr(Image, 'Resampling', Image).LANCZOS` (`generate-icon.py:9`) |
| CQ6 — `import time` at module top | ✓ Top-level import (`generate-icon.py:4`) |
| CQ7 — `ring_color` dead defaults removed | ✓ Direct `cfg['threshold_critical']` (`generate-icon.py:75–77`) |
| CQ9 — live `panel-icon-size` | ✓ `this._icon.set_icon_size(...)` in `_updateDisplay` (`extension.js:234`); summary text drops "requires reload" |

All seven pass‑5 bugs and seven of nine code‑quality items are closed. CQ5 (`status.sh` invokes Python 3×) and CQ8 (`Name=` overwrites Activities search) remain deferred — noted by the pass‑5 plan and out of scope for this pass.

---

## New Bugs

### BUG‑P6‑1 — Medium: Stale `_anthropic_status` persists across status‑page outages

**File:** `chrome-extension/background.js:163, 192–194` · `server/usage-server.py:126–136`

```javascript
const anthropic_status = await fetchAnthropicStatus();
...
if (anthropic_status) data._anthropic_status = anthropic_status;
```

The status‑page result is attached to the POST body only when `fetchAnthropicStatus()` returns truthy. When it returns `null` (network glitch, status.claude.com 5xx, AbortController‑style cancel), no `_anthropic_status` field is included.

The server merges full payloads on top of prev:

```python
body = {**prev, **body}
```

`prev._anthropic_status` (if any) is preserved unchanged.

**Failure scenario** — Anthropic resolves an outage while the user's Chrome is closed:

1. T0: Anthropic has a `minor` incident. Cache: `_anthropic_status: { indicator: 'minor', description: 'Elevated 5xx on Claude.ai' }`. Extension shows broken tier with outage reason.
2. T0+30min: User closes Chrome (or loses network briefly).
3. T1: Anthropic resolves the incident. status.claude.com now reports `indicator: 'none'`.
4. T2 (Chrome reopened, but status fetch transiently fails — e.g. their statuspage rate-limited us): scrape succeeds → POST body has fresh `meters` and `_timestamp` but **no** `_anthropic_status`. Server merges → cache keeps stale `indicator: 'minor'`.
5. Extension reads cache: `astat.indicator === 'minor'` is still truthy → tier=broken with outage reason. **Stale outage signal wins over fresh local data.**

The tier‑decision precedence in `extension.js:280–294` is "outage signal first, local fail next, age last." So a stale outage flag outranks an otherwise‑healthy cache.

**Reachability:** Requires a transient status‑fetch failure across the recovery boundary. Not theoretical — Statuspage's free tier rate-limits to ~1 req/sec per IP, and the auto‑scrape path can spam it if the user opens the usage page rapidly.

**Fix options (pick one):**

1. **Explicit clear:** send `_anthropic_status: null` when `fetchAnthropicStatus()` returns null. Server treats null as "no signal" and clears the cached value.

   ```javascript
   const partial = { _scrape_fail_count: fails, _anthropic_status: anthropic_status };  // unconditionally include, even when null
   // and likewise for the success path
   data._anthropic_status = anthropic_status;  // may be null
   ```

   Then `_validate` already accepts `astat is None`, and the merge replaces prev's value with null. Extension's `astat.indicator && ...` short‑circuits on null. Clean.

2. **Freshness gate:** attach a timestamp to `_anthropic_status` and ignore values older than ~15 min in the extension. More resilient but requires both ends to know about the field.

Option 1 is two lines; option 2 is structural. Recommend option 1.

**Regression test:** seed cache with `_anthropic_status: { indicator: 'minor' }`, simulate a successful scrape with `fetchAnthropicStatus` returning null, expect the next cache read to have `_anthropic_status: null` (or missing) and the extension to render tier=normal.

---

### BUG‑P6‑2 — Medium: Concurrent `generate-icon.py` runs delete each other's icons

**File:** `server/generate-icon.py:213–220` · `gnome-extension/extension.js:180–197` · `server/usage-server.py:161–163`

Two code paths spawn `generate-icon.py` in parallel:

1. `usage-server.py` POST handler — spawns on every successful cache write (`subprocess.Popen([sys.executable, str(GENERATE_ICON)], …)`). No `--tier` flag.
2. `extension.js:_spawnIconRegen` — spawned on tier transition (`Gio.Subprocess.new(['python3', script, '--tier', tier], …)`). Includes `--tier` override.

On **recovery from broken/stale → normal** the two paths fire near-simultaneously:
- The Chrome extension posts a fresh scrape → server writes cache, spawns generate-icon (path 1).
- The file monitor in the GNOME extension fires → `_updateDisplay` computes tier=normal → spawns generate‑icon with `--tier normal` (path 2).

Each `generate-icon.py` invocation does:

```python
dest = _next_icon_path()                          # unique, time_ns() filename
generate(all_pct, sonnet_pct, cfg, dest, tier=…)  # write new icon
for old in CACHE_DIR.glob('icon-*.png'):          # cleanup: keep only dest
    if old != dest:
        try: old.unlink()
        except OSError: pass
update_desktop(meters, dest, …)                   # point .desktop at dest
```

Each process treats *its own* `dest` as the canonical icon and deletes everything else under `icon-*.png` — including the *other* process's just‑written icon.

**Interleaving trace** (two concurrent processes T1 and T2, generating icons A and B):

| Step | T1 | T2 | Disk state |
|------|----|----|------------|
| 1 | write A | — | {A} |
| 2 | — | write B | {A, B} |
| 3 | cleanup glob → [A, B], deletes B (B != A) | — | {A} |
| 4 | — | cleanup glob → [A], deletes A (A != B) | {} |
| 5 | update_desktop → Icon=A | — | {} ← Icon points to deleted file |
| 6 | — | update_desktop → Icon=B | {} ← still deleted |

Final state: `.desktop` points to icon B, but B was deleted by T1's cleanup. GNOME falls back to the icon theme entry (`claude-usage` → `/usr/share/icons/hicolor/64x64/apps/claude-usage.png` baseline, or the orphan placeholder on source installs) until the next icon regen.

**Reachability:** Specifically the recovery transition (broken → normal). The pass‑5 review identified the tier system as recently landed (commit `7371760`); the race is a side-effect of that commit interacting with the long‑standing POST‑handler spawn.

**Reproducer (bash):**

```bash
# Pre-condition: cache file exists with usable meters.
( python3 /usr/share/claude-usage/generate-icon.py & \
  python3 /usr/share/claude-usage/generate-icon.py --tier normal & \
  wait )
ls ~/.cache/claude-usage/icon-*.png   # may be empty
grep ^Icon= ~/.local/share/applications/claude-usage.desktop
# Icon path may not exist on disk
```

**Fix options:**

1. **File lock around the whole regen** — wrap the write‑cleanup‑update_desktop block with `fcntl.flock` on a sentinel file. Serializes concurrent invocations; second waits for first to finish.

2. **Cleanup‑by‑mtime, not by name equality** — only delete icons older than `dest`. Concurrent writers race on icon count but never delete each other's *current* output.

   ```python
   dest_mtime = dest.stat().st_mtime
   for old in CACHE_DIR.glob('icon-*.png'):
       try:
           if old.stat().st_mtime < dest_mtime - 1.0:   # 1 s grace window
               old.unlink()
       except OSError:
           pass
   ```

3. **Drop the server-side spawn entirely** — let the extension be the sole orchestrator. The extension already spawns on tier transitions; add a "spawn on every cache update" trigger and remove the POST‑handler spawn. Simpler architecture, but couples icon refresh to extension health (the extension must be enabled for icons to render).

Recommend option 2 as the lowest-churn fix; option 3 if you want to simplify.

---

### BUG‑P6‑3 — Medium: `_period_lengths` not validated, can persist garbage

**File:** `server/usage-server.py:36–87` · `server/usage-server.py:147–154`

The validator at `_validate(body)` checks `meters`, `plan`, `_scrape_fail_count`, `_anthropic_status`, and `_timestamp`. It does **not** check `_period_lengths`. A POST with arbitrary content in that field passes validation and is merged into the cache:

```python
period_lengths = body.get('_period_lengths', {}) or {}
for meter in body.get('meters', []) or []:
    rm = meter.get('reset_minutes')
    label = meter.get('label')
    if rm is None or not label: continue
    period_lengths[label] = max(period_lengths.get(label, 0), rm)
body['_period_lengths'] = period_lengths
```

**Exploitation paths** (all assume a same‑user local attacker, since the server is loopback‑only):

| Payload | Effect |
|---------|--------|
| `{"_period_lengths": "garbage"}` | `"garbage" or {}` evaluates to the string → `period_lengths.get(...)` raises AttributeError → outer except returns 400. Cache not written, but every legit POST in the same merge window gets refused. |
| `{"_period_lengths": {"weekly": "999"}}` | `max("999", 0)` → TypeError comparing str/int → 400. Same denial. |
| `{"_period_lengths": {"weekly": -100}}` | Passes the line‑by‑line max() because both args are ints. Persists negative period to cache. `pacing_pct` then computes `fraction = 1 - rm/-100 = 1 + rm/100` — large positive, pacing≈pct/big = small. Cosmetic: colors stay green even when on pace to blow the period. |
| `{"_period_lengths": {"weekly": 9999999999}}` | Passes. Persists huge period. `fraction = 1 - rm/big ≈ 1`. Pacing ≈ raw pct (no projection bonus). Just defeats the feature for one label. |

None of these escalate beyond cosmetic, but the validator's job is to gate cache content and it has a clear gap on a field that's now load-bearing for the pacing‑based color feature.

**Fix:**

```python
pl = body.get('_period_lengths')
if pl is not None:
    if not isinstance(pl, dict):
        return "'_period_lengths' must be an object"
    for k, v in pl.items():
        err = _bounded_str(k, '_period_lengths key')
        if err: return err
        if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 60 * 24 * 31:
            return f"_period_lengths[{k!r}] must be a non-negative integer ≤ 31 days"
```

`31 days` is a reasonable upper bound — the longest plausible Claude period is the weekly one (~10 080 minutes); 31 days × 1440 = 44 640 leaves headroom for whatever monthly period might appear without letting integers go to the moon.

---

### BUG‑P6‑4 — Medium: `.desktop` tmp filename collision across writers

**File:** `server/tooltip.py:110–112`

```python
tmp = DESKTOP.with_suffix(DESKTOP.suffix + '.tmp')
tmp.write_text('\n'.join(out) + '\n')
tmp.replace(DESKTOP)
```

`tmp` is the fixed filename `~/.local/share/applications/claude-usage.desktop.tmp`. Three independent writers can hit this path:

1. **`usage-server.py:_tooltip_tick`** — in-process call to `tooltip.update_desktop(...)` every 60 s.
2. **`generate-icon.py` spawned by `usage-server.py`** — on every POST (every ~7 min, plus auto-scrape fires).
3. **`generate-icon.py` spawned by `extension.js:_spawnIconRegen`** — on tier transitions.

If two writers `Path.write_text(...)` to the same path concurrently, the second's open truncates the first's in-flight write. The replace-onto-DESKTOP is a single syscall and atomic, but the *content* of the file being renamed is now interleaved between the two writers — possibly truncated to nothing, possibly with one writer's first half + the other's second half.

**Pre-conditions for an actually broken `.desktop` file** are tight:
- Two writers' `open(..., 'w')` calls overlap with each other's `write(...)`.
- `write_text` is implemented as `open() + write() + close()` and the GIL doesn't help across these.

In practice the tooltip tick (single line in/out, microseconds) is unlikely to overlap with generate-icon.py's update_desktop (also fast). But the race window exists, and the cost of fixing it is two extra characters in the tmp filename.

**Fix:**

```python
tmp = DESKTOP.with_suffix(f'.tmp.{os.getpid()}.{time.time_ns()}')
```

Each writer gets a unique tmp name. No collision possible. `Path.replace` is still atomic onto DESKTOP. Add a periodic sweep (or rely on `/tmp`‑style staleness cleanup) if orphan tmp files are a concern — they're tiny.

Same fix applies to `usage-server.py:155–159` for the JSON cache, but that file has a single writer (the HTTP handler), so the same-path race is structurally impossible there.

---

### BUG‑P6‑5 — Low: `_timestamp` validation accepts `True / False`

**File:** `server/usage-server.py:84–86`

```python
ts = body.get('_timestamp') or body.get('timestamp')
if ts is not None and not isinstance(ts, (int, float)):
    return "'_timestamp' must be a number"
```

Same Python `bool ⊂ int` gotcha as the pass‑5 BUG‑P5‑1: `isinstance(True, (int, float))` is `True`. A POST with `{"_timestamp": true}` passes validation. Server stores `True` in the cache.

Downstream:
- `tooltip.parse_reset(anchor_ts=True)` → `time.time() - True` = `time.time() - 1` (one second ago). Live countdown thinks the scrape was a second ago. Cosmetic.
- `extension.js: Math.round((Date.now() / 1000 - d._timestamp) / 60)` → `Math.round((now - true) / 60)`. `now - true` coerces `true` to 1, so age becomes "now minus 1 second" → ~0 min. Cosmetic.

Same threat model as BUG‑P5‑1: only reachable via a malicious local POST; not actually catastrophic. Defense-in-depth gap — the bool check that landed for `pct`, `reset_minutes`, and `_scrape_fail_count` was not extended to `_timestamp`.

**Fix (1 line):**

```python
if ts is not None and (isinstance(ts, bool) or not isinstance(ts, (int, float))):
    return "'_timestamp' must be a number"
```

---

### BUG‑P6‑6 — Low: `reset_minutes` has no upper bound

**File:** `server/usage-server.py:63–66`

```python
rm = m.get('reset_minutes')
if rm is not None and (
    isinstance(rm, bool) or not isinstance(rm, int) or rm < 0
):
    return f"meters[{i}].reset_minutes must be a non-negative integer or null"
```

A POST with `reset_minutes: 999999999` passes. The server then accumulates it into `_period_lengths` via `max(prev, rm)`, durably poisoning the period for that label until either a fresh scrape with the correct value overrides it (which `max()` won't allow if the bad value is larger — bug becomes permanent) or the user manually edits the cache.

Even legitimate parser output is bounded — `parseResetMinutes` in `background.js:42–69` parses "X hr Y min" / "X min" / day‑and‑time. The longest plausible day‑and‑time is 7 days × 1440 = 10 080 minutes. A weekly period is the longest known meter. Cap the field at the same 44 640 (31 days) suggested for `_period_lengths` in BUG‑P6‑3.

**Fix:**

```python
if rm is not None and (
    isinstance(rm, bool) or not isinstance(rm, int) or rm < 0 or rm > 60 * 24 * 31
):
    return f"meters[{i}].reset_minutes must be in [0, 44640] or null"
```

---

### BUG‑P6‑7 — Low: `tab.url.startsWith(USAGE_URL)` over-matches

**File:** `chrome-extension/background.js:306`

```javascript
if (!tab.url || !tab.url.startsWith(USAGE_URL)) return;
```

`USAGE_URL` is `https://claude.ai/settings/usage`. `startsWith` matches:

- `https://claude.ai/settings/usage` ✓ (intended)
- `https://claude.ai/settings/usage?ref=email` ✓ (intended)
- `https://claude.ai/settings/usage#section` ✓ (intended)
- `https://claude.ai/settings/usagedetails` ✓ (**unintended**)
- `https://claude.ai/settings/usage-policy` ✓ (**unintended**)

Not a bug today — Anthropic doesn't host those URLs — but a quiet trap if `/settings/usage-summary` or similar ever ships. The auto-scrape would fire on that page and parse zero meters, incrementing `_scrape_fail_count` toward broken-tier.

**Fix:**

```javascript
const url = new URL(tab.url);
if (url.origin !== 'https://claude.ai' || url.pathname !== '/settings/usage') return;
```

Or equivalently:

```javascript
const stripped = tab.url.split(/[?#]/, 1)[0];
if (stripped !== USAGE_URL) return;
```

---

### BUG‑P6‑8 — Low: `fetchAnthropicStatus` has no timeout

**File:** `chrome-extension/background.js:12–26`

```javascript
async function fetchAnthropicStatus() {
    try {
        const resp = await fetch(STATUS_URL);
        ...
    } catch (_) { return null; }
}
```

No `AbortController`. If `status.claude.com` is slow (e.g. their CDN is degraded — a plausible co-incident with a Claude outage), this fetch can block the whole `scrapeAndPost` flow until Chrome's MV3 service-worker idle timer kills the request (~30 s). During that time, `_fetching` is held true and no other scrape can run.

**Fix:**

```javascript
async function fetchAnthropicStatus() {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 5000);
    try {
        const resp = await fetch(STATUS_URL, { signal: ctl.signal });
        if (!resp.ok) return null;
        const j = await resp.json();
        const claudeAi = (j.components || []).find(c => c.name === 'claude.ai');
        return {
            indicator: j.status?.indicator ?? null,
            description: j.status?.description ?? null,
            claude_ai_component_status: claudeAi?.status ?? null,
        };
    } catch (_) {
        return null;
    } finally {
        clearTimeout(timer);
    }
}
```

5 s is plenty for a 50 KB JSON poll; saves up to 25 s of held-open `_fetching` on a bad day.

---

### BUG‑P6‑9 — Low: Permissive CORS allows any local-origin web page to POST

**File:** `server/usage-server.py:173–176`

```python
def _cors(self):
    self.send_header('Access-Control-Allow-Origin', '*')
    self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
    self.send_header('Access-Control-Allow-Headers', 'Content-Type')
```

`Access-Control-Allow-Origin: *` is the wildcard — any web page in any browser can submit a cross-origin POST to `127.0.0.1:7331` and the browser will deliver it. The validator gates the *shape* of the body, but a malicious page can submit shape-valid garbage (e.g. `meters: [{ pct: 100, label: 'All models' }]` repeated) to push the user's panel to permanent red.

**Threat model:** the attacker must trick the user into visiting their page in *any* browser on the same machine. Same caveat as BUG‑P5‑1/P5‑3: not a remote attacker, but a real attack surface from drive-by web content.

**Fix options:**

1. **Restrict CORS to the extension origin:**

   ```python
   ALLOWED_ORIGINS = {
       'chrome-extension://*',   # ideally the specific extension ID
   }
   ```

   But the unpacked extension ID changes per-install, so a fixed allow-list is brittle. Chrome Web Store publication would lock the ID.

2. **Require a shared secret in the POST body** — generated at server start, written to a 0o600 file the extension reads. Out of scope for an unpacked extension that can't easily mount a per-user file system path.

3. **Drop CORS entirely** — the extension sends `Access-Control-Allow-Origin: *` requests but the browser's same-origin policy on the *request* side may not require CORS for `chrome-extension://` origins making fetches to loopback (some Chrome versions treat extension fetches as same-origin to localhost). Verify and remove the CORS headers if unneeded.

Recommend option 3 — test whether the current Chrome extension actually needs the CORS headers. If not, drop them entirely.

---

## New Code-Quality Findings

### CQ6‑1 — `ImageOps` import inside conditional

**File:** `server/generate-icon.py:167–171`

```python
if tier == 'stale':
    r, g, b, a = img.split()
    from PIL import ImageOps
    grey = ImageOps.grayscale(Image.merge('RGB', (r, g, b)))
    img = Image.merge('RGBA', (grey, grey, grey, a))
```

Same pattern flagged in pass‑5 CQ6 for `import time`; the `from PIL import ImageOps` here is its sibling. Hoist to module top with the other PIL import.

### CQ6‑2 — Two storage reads in the auto-scrape listener could be one

**File:** `chrome-extension/background.js:310–313`

```javascript
const { _scrape_tabs = [] } = await chrome.storage.local.get('_scrape_tabs');
if (_scrape_tabs.includes(tabId)) return;
const { _last_scrape_ts = 0 } = await chrome.storage.local.get('_last_scrape_ts');
if (Date.now() - _last_scrape_ts < AUTO_DEBOUNCE_MS) return;
```

Two await points where one suffices:

```javascript
const { _scrape_tabs = [], _last_scrape_ts = 0 } =
    await chrome.storage.local.get(['_scrape_tabs', '_last_scrape_ts']);
if (_scrape_tabs.includes(tabId)) return;
if (Date.now() - _last_scrape_ts < AUTO_DEBOUNCE_MS) return;
```

Halves the awaits, halves the chance of a service-worker suspension splitting them. Cosmetic.

### CQ6‑3 — `claude-usage-status` uses 30 min stale threshold; extension uses 10 / 20 min

**File:** `scripts/claude-usage-status.sh:50–55`

```bash
if [ "$ts" = "?" ] || [ "$ts" -gt 30 ] 2>/dev/null; then
    echo "  Cache:      ⚠ ${ts}m old — data may be stale (plan: $plan)"
```

The GNOME extension flips to **stale** at 10 min and **broken** at 20 min (`extension.js:289–294`). The diagnostics tool only flags stale at 30 min. A user who sees their panel go grey at minute 11 and runs `claude-usage-status` is told everything's fine — but the panel is already advertising "stale."

**Fix:** align thresholds, and report the cause text the extension would use:

```bash
if [ "$ts" = "?" ]; then
    echo "  Cache:      ✗ unparseable timestamp"
elif [ "$ts" -gt 20 ]; then
    echo "  Cache:      ✗ ${ts}m old — extension flips to BROKEN at this point"
elif [ "$ts" -gt 10 ]; then
    echo "  Cache:      ⚠ ${ts}m old — extension flips to STALE at this point"
else
    echo "  Cache:      ✓ present (${ts}m ago, plan: $plan)"
fi
```

### CQ6‑4 — `claude-usage-status` doesn't surface tier signals from the cache

**File:** `scripts/claude-usage-status.sh:56–67`

The diagnostics tool reports cache age and per‑meter rows but ignores the two cache fields that drive the broken tier:

- `_scrape_fail_count` — the count the GNOME extension uses to flip to broken at `>= 2`.
- `_anthropic_status.indicator` / `.description` — the outage signal.

If a user complains "the icon is red but I don't know why," the tool should be the first place to look. Add:

```python
sfc = d.get('_scrape_fail_count', 0)
astat = d.get('_anthropic_status') or {}
if sfc >= 2:
    print(f"  Scrape:     ⚠ {sfc} consecutive failures")
if astat.get('indicator') not in (None, 'none'):
    print(f"  Anthropic:  ⚠ {astat.get('description') or astat.get('indicator')}")
```

The whole diagnostics tool would be cleaner as a single Python script (closing CQ5 from pass 5 in the process), but even a two-block addition to the existing heredoc here would surface the signal.

### CQ6‑5 — `release` task runs `deps` before preflight checks

**File:** `Taskfile.yml:75–104`

```yaml
release:
    desc: …
    deps: [build, build-chrome-zip, test-deb]
    vars:
      TAG: v{{.VERSION}}
    cmds:
      - |
        set -euo pipefail
        current=$(git rev-parse --abbrev-ref HEAD)
        if [ "$current" != "main" ]; then
          echo "Refusing to release from non-main branch: $current"
          exit 1
        fi
        if ! git diff --quiet HEAD; then
          ...
```

`deps:` runs before the first `cmds:` block. Order of operations on a dirty working tree:

1. `task build` runs (~30 s, builds the .deb).
2. `task build-chrome-zip` runs (~1 s).
3. `task test-deb` runs (~4–7 min — `task test-deb` is the cold-cache variant in `deps:`, not the fast variant).
4. *Then* the preflight detects the dirty tree and refuses.

That's potentially 4–7 minutes of work thrown away because the preflight fires last. Move the preflight to a separate task that's a dep of build / chrome-zip / test-deb:

```yaml
release-preflight:
    cmds: [ "<the existing preflight block>" ]

build:
    deps: [release-preflight]
    ...
```

Or inline the preflight at the *top* of the release `cmds:` and accept that `deps:` will run first regardless — but at minimum, move the check that catches the most common mistake (dirty tree) into a dep so it short-circuits before the build.

### CQ6‑6 — Server-spawned `generate-icon.py` doesn't pass tier

**File:** `server/usage-server.py:161–163`

```python
if GENERATE_ICON:
    subprocess.Popen([sys.executable, str(GENERATE_ICON)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

No `--tier` flag. The spawned script falls back to `derive_tier(data)` which reads the cache the server just wrote — so it sees the freshest `_anthropic_status` and `_scrape_fail_count`, but **cannot** see how stale the cache is (the script doesn't know "now" relative to the cache's `_timestamp`).

That's fine for normal POSTs (cache is by definition fresh). But it means the server-spawn always renders the tier as **normal** (or **broken** if there's an outage / fail-count signal) — never **stale**. The extension's age-based tier transitions are the only thing that produce the stale dock icon.

Not a bug — the extension reliably catches age via its 30 s timer (`extension.js:174`). Just noting the asymmetry: the server is the icon-rendering trigger on the happy path; the extension is the icon-rendering trigger on the unhappy path. Both call sites work; they're not interchangeable.

### CQ6‑7 — Stale entries in `_period_lengths` accumulate indefinitely

**File:** `server/usage-server.py:147–154`

Every unique `meter.label` seen across all scrapes adds a key to `_period_lengths`. If Anthropic renames a meter (e.g. "Sonnet 4.5" → "Sonnet 4.6"), both keys persist. Same for labels that appear once in a UI bug and never again.

**Bounded by the universe of label strings,** which is tiny. A dozen entries over a year is the realistic max. Not a leak — just an observation. A "max 32 entries, oldest-out" eviction would be over-engineered for this.

### CQ6‑8 — `Main.notify` on every stale/broken entry can chatter

**File:** `gnome-extension/extension.js:316`

```javascript
if (tier !== this._lastTier) {
    if (tier === 'stale' || tier === 'broken') {
        Main.notify('Claude Usage', reason || `Status: ${tier}`);
        ...
```

Notifies on entry to stale/broken. Not on recovery. Fine for a single transition. But sequence `normal → stale → broken → normal → stale → broken → normal …` (Chrome flapping on a flaky network, alarm misses then catches up, repeat) produces a notification on every tier upgrade — 6 notifications over an hour is plausible.

The notification text changes each time (reason includes age in minutes), so GNOME's notification dedupe doesn't collapse them.

**Soft fix:** rate-limit — track `_lastNotifyTs` and skip notifications if the last one was within 5 min. The icon color flip is the persistent signal; toasts should be the occasional "hey, this is happening" prod, not a metronome.

### CQ6‑9 — `parse_reset` defaults unknown day to Monday

**File:** `server/tooltip.py:45`

```python
wd = {'Mon':0,'Tue':1,'Wed':2,'Thu':3,'Fri':4,'Sat':5,'Sun':6}.get(day, 0)
```

If `day` is not in the map (claude.ai changes locale, returns `Mon ` with trailing space, returns `Mon.` with period), `wd` is 0 → Monday. The displayed reset day silently shifts.

Same defensive default exists in `extension.js:29–30`:

```javascript
const wdMap = {Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6};
let ahead = (wdMap[day] - now.getDay() + 7) % 7;
```

But JS `undefined - n + 7` is `NaN`, and `NaN % 7` is `NaN`. The subsequent `if (ahead === 0)` is false (NaN !== 0). Then `(now + NaN)` is "Invalid Date". The whole thing returns the raw `reset` string. Different graceful degradation than Python's "assume Monday."

Both could fail-loud instead (return None / fall through to displaying the raw string). The Python case is worse because Monday is a plausible-looking wrong answer; a user wouldn't notice the misparse.

**Fix:**

```python
if day not in WD_MAP:
    return None
wd = WD_MAP[day]
```

### CQ6‑10 — `test-deb-verify.sh` skips `tooltip.py` syntax check + `claude-usage-status` syntax check

**File:** `packaging/test-deb-verify.sh:27–30`

```bash
/usr/bin/claude-usage-status -h >/dev/null
python3 -m py_compile /usr/share/claude-usage/generate-icon.py
python3 -m py_compile /usr/share/claude-usage/usage-server.py
bash -n /usr/bin/claude-usage-setup
```

`tooltip.py` is checked for existence (line 16) but not syntax. `claude-usage-status` is exercised via `-h` (catches argv-stage parser errors) but not `bash -n` (catches preceding script syntax errors).

**Fix:**

```bash
python3 -m py_compile /usr/share/claude-usage/tooltip.py
bash -n /usr/bin/claude-usage-status
```

Two lines. Both quick; gates the cases where someone ships a syntax-broken file because the wrapper script never reaches it.

### CQ6‑11 — `tooltip.py` chmod inconsistency between source and `.deb` installs

**File:** `install.sh:81` vs. `packaging/build-deb.sh:86`

```bash
# install.sh
chmod +x "$SERVER_DIR/usage-server.py" "$SERVER_DIR/generate-icon.py"

# build-deb.sh
find "$PKG/usr/share/claude-usage" -name "*.py" -exec chmod 755 {} \;
```

Source install: tooltip.py stays 644 (not executable). Correct — it's a library.
`.deb` install: tooltip.py gets 755. Inconsistent with source.

Functionally inert (CPython imports modules regardless of executable bit), but the inconsistency would bite if anyone ever tries to `find ... -executable` to enumerate scripts in one install but not the other. Minor.

**Fix:** in `build-deb.sh`, scope the chmod to the two entry-point scripts:

```bash
chmod 755 "$PKG/usr/share/claude-usage/usage-server.py" \
          "$PKG/usr/share/claude-usage/generate-icon.py"
```

### CQ6‑12 — PRIVACY.md doesn't list `_anthropic_status` or `_scrape_fail_count`

**File:** `PRIVACY.md:23`

```
- `~/.cache/claude-usage/usage.json` — usage data + inferred per-meter period lengths (`_period_lengths`: …), updated every 7 minutes
```

`_period_lengths` is itemized; `_anthropic_status` and `_scrape_fail_count` are not. Neither carries personal data (the status fields are about Anthropic's status page, not the user; the fail count is an integer), but for completeness the policy should enumerate everything stored.

**Fix:**

```
- `~/.cache/claude-usage/usage.json` — usage data, inferred per-meter period lengths (`_period_lengths`),
  consecutive scrape-failure counter (`_scrape_fail_count`), and Anthropic public status-page snapshot
  (`_anthropic_status`: indicator + description). Updated every 7 min.
```

### CQ6‑13 — SPA navigation to the usage page isn't picked up by the auto-scrape listener

**File:** `chrome-extension/background.js:304–306`

```javascript
chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== 'complete') return;
  if (!tab.url || !tab.url.startsWith(USAGE_URL)) return;
```

`tabs.onUpdated` fires `info.status === 'complete'` on hard page loads. claude.ai is a React SPA — navigating from `/chat` to `/settings/usage` via the in-app sidebar uses `history.pushState`, which produces `webNavigation.onHistoryStateUpdated` events but no `tabs.onUpdated` with `status: 'complete'`.

So if the user clicks the in-app "Settings → Usage" link, the auto-scrape doesn't fire until the next 7-min alarm tick. The MANUAL.md promise ("Open `claude.ai/settings/usage` in any normal tab … the extension auto-scrapes the page once it finishes loading") is only true for fresh navigations (address bar, bookmark, click-link-that-navigates-away).

**Fix options:**

1. Subscribe to `chrome.webNavigation.onHistoryStateUpdated` — requires adding `"webNavigation"` to `permissions` in manifest.json. ~10 extra lines.
2. Document the limitation in MANUAL.md instead.

Option 2 is cheaper and probably acceptable — the common path to /settings/usage is the popup's "Open Usage Page" item (which calls `Gio.AppInfo.launch_default_for_uri`, opening a new tab), the toolbar icon, or a bookmark. All are hard navigations that hit the `status: 'complete'` path.

### CQ6‑14 — `_anthropic_status` description hardcoded in MANUAL example

**File:** `MANUAL.md:54`

```
> *"Anthropic reports: Elevated 5xx on Claude.ai"*
```

The actual Statuspage `description` field is normally the *page-level* status (`"All Systems Operational"`, `"Minor Service Outage"`, `"Partial Service Outage"`, etc.) — not an incident-specific message. For an active incident, the user sees something like `⚠ Anthropic reports: Minor Service Outage`, not the example text. Cosmetic doc drift; either soften the example to "e.g. *Minor Service Outage*" or pull a real example from a past outage.

---

## Architecture & Process

These were flagged in prior passes; still applicable.

### A1 — No CI gate on tag push

`task test-deb-fast` exists, runs in ~10 s, and is in `deps:` of `release`. But the release happens from the maintainer's laptop. A GitHub Actions workflow on tag push (matrix: 22.04, 24.04; runs `test-deb`) would catch the "I bumped the version locally but forgot to push" / "test-deb passes on my machine, fails in CI's clean image" gap. Same finding as pass 5.

### A2 — `metadata.json` extension version still `1`

The extensions.gnome.org spec demands an integer that increments per release. Self-hosted distribution doesn't check this. Flag the first time EGO submission enters scope.

### A3 — Source + `.deb` install can shadow each other

Documented in pass 5; still applies. A one-line note in MANUAL.md ("Pick one install method — running both creates a systemd-unit precedence conflict") would close it.

### A4 — Version sync is manual

`packaging/control:Version` and `chrome-extension/manifest.json:version` are bumped by hand. Nothing in `task release` cross-checks them. If they drift, the `.deb` ships with one version and the Chrome zip with another.

**Fix:** preflight check in `release`:

```bash
ctl_ver=$(grep '^Version:' packaging/control | awk '{print $2}')
ext_ver=$(python3 -c 'import json; print(json.load(open("chrome-extension/manifest.json"))["version"])')
if [ "$ctl_ver" != "$ext_ver" ]; then
    echo "Version mismatch: control=$ctl_ver, manifest=$ext_ver"
    exit 1
fi
```

### A5 — Old `.deb`s pile up in `dist/`

Thirteen versions sitting in `dist/` (0.9.1 → 0.10.5). Gitignored, so they don't pollute git history, but they're ~70 KB each and `dist/` is referenced by `task build`'s `generates:` and `task release`'s `gh release create`. A `task release` cleanup step that prunes anything older than the latest two would keep the directory tidy. Cosmetic.

---

## Security — Verified Intact

- Loopback-only bind ✓ (`usage-server.py:200`)
- `0o600` cache file ✓ (`usage-server.py:158`)
- Schema validation rejects malformed input ✓ (modulo BUG‑P6‑3, BUG‑P6‑5, BUG‑P6‑6 above)
- No shell command interpolation in any script reviewed
- Atomic write-then-rename for cache and `.desktop` ✓
- 256 KB request cap ✓
- Subprocess zombie reaping ✓ (SIGCHLD SIG_IGN)
- No path traversal in user-controlled inputs
- IPv4 loopback only — no IPv6 binding

The systemd hardening recommendation from pass 5 (NoNewPrivileges, ProtectSystem=strict, etc.) is still unimplemented but not a regression.

---

## Priority Summary

| Priority | Count | Items |
|----------|-------|-------|
| **High**   | 0 | — |
| **Medium** | 4 | BUG‑P6‑1 (stale astat), BUG‑P6‑2 (icon delete race), BUG‑P6‑3 (`_period_lengths` validation), BUG‑P6‑4 (`.desktop` tmp race) |
| **Low**    | 5 | BUG‑P6‑5 (`_timestamp` bool), BUG‑P6‑6 (`reset_minutes` cap), BUG‑P6‑7 (URL match), BUG‑P6‑8 (status fetch timeout), BUG‑P6‑9 (CORS) |
| **Code quality** | 14 | CQ6‑1 …  CQ6‑14 |
| **Architecture** | 5 | No CI, metadata.json version, source+deb conflict, version sync, dist cleanup |

---

## Recommended Fix Order

1. **BUG‑P6‑1** — stale `_anthropic_status` clear: 2 lines in `background.js`, no schema or extension change needed.
2. **BUG‑P6‑3** — `_period_lengths` validation: ~8 lines in `usage-server.py` `_validate`.
3. **BUG‑P6‑5 + BUG‑P6‑6** — defense-in-depth validator gaps: 2 lines.
4. **BUG‑P6‑2** — icon-delete race: mtime-based cleanup (~5 line change in `generate-icon.py`).
5. **BUG‑P6‑4** — `.desktop` tmp race: PID+nanos suffix (~1 line in `tooltip.py`).
6. **BUG‑P6‑7** — URL exact-match: ~3 lines.
7. **BUG‑P6‑8** — `AbortController` on status fetch: ~10 lines.
8. **CQ6‑3 + CQ6‑4** — align `claude-usage-status` thresholds with extension, surface tier signals: ~15 lines in the shell script.
9. **CQ6‑10** — extra `py_compile` + `bash -n` lines in test-deb-verify.
10. Remaining CQ items — bundle into a single cleanup PR.

---

## Overall Assessment

**Grade: A−**

Same letter grade as pass 5, but a different shape:

- **Zero high-severity bugs.** Pass 5 found two (BUG‑P5‑1, BUG‑P5‑2); this pass finds none. The validator-strictness pattern from P5 has been consistently applied to `pct`, `reset_minutes`, and `_scrape_fail_count`, and pass-5's `_fetching` deadlock fix held up. The high-severity surface is genuinely well-covered now.

- **Four medium-severity bugs**, all in code added since pass 5:
  - BUG‑P6‑1 (stale `_anthropic_status`) is a side effect of the outage-tier system introduced in `7371760`.
  - BUG‑P6‑2 (concurrent icon-regen race) is a side effect of the same commit interacting with the long-standing server-side POST spawn.
  - BUG‑P6‑3 (`_period_lengths` validation) is a side effect of the pacing-based color feature in `0aa182f`.
  - BUG‑P6‑4 (`.desktop` tmp race) is a side effect of the 60 s tooltip refresh in `3bf6160` adding a second writer to a file path that previously had one.

The pattern: each new feature widens the I/O surface area, and the validator / concurrency story has to widen with it. The validator now covers six fields end-to-end and is one easy edit away from covering the seventh and eighth.

- **Pass-5 fixes are durable.** All seven bugs and seven of the nine flagged code-quality items are closed and remain closed. The two deferred items (CQ5 status.sh Python invocations, CQ8 Activities-search Name= overwriting) are still parked.

- **Code remains compact and well-structured.** ~2 400 LOC total. The new files (`tooltip.py`) are small and well-scoped. The recently added features all have rationale-rich comments at the call sites that survive code review.

The architecture choices that supported the earlier passes (file-monitor over polling, atomic writes, schema-validated POST, 0o600 cache) all hold up under the new feature load. The race conditions in BUG‑P6‑2 and BUG‑P6‑4 are the cost of two-writer concurrency that wasn't present pre-tier system; they're fixable in <20 lines combined.

### To reach A

Close BUG‑P6‑1 through BUG‑P6‑4 and CQ6‑3 / CQ6‑4. ~50 LOC of changes across 4 files.

### To reach A+

Everything above, plus:

- GitHub Actions on tag push (parked since pass 4).
- Single Python diagnostics script replacing `claude-usage-status.sh` (closes CQ5 from pass 5).
- systemd hardening directives (defense-in-depth; not a bug).
- Version-sync preflight in `release` (A4).

---

## Closure Status

Resolved by `213e19b` (Commit A — bugs + 0.10.6 bump) and the immediately-following Commit B (code quality). See [plans/2026-05-17-pass6-fixes.md](../plans/2026-05-17-pass6-fixes.md) for the fix plan and verification log.

| ID | Status | Commit |
|----|--------|--------|
| BUG-P6-1 (stale astat) | ✓ Fixed | A |
| BUG-P6-2 (icon delete race) | ✓ Fixed | A |
| BUG-P6-3 (`_period_lengths` validation) | ✓ Fixed | A |
| BUG-P6-4 (`.desktop` tmp race) | ✓ Fixed | A |
| BUG-P6-5 (`_timestamp` bool) | ✓ Fixed | A |
| BUG-P6-6 (`reset_minutes` cap) | ✓ Fixed | A |
| BUG-P6-7 (URL exact match) | ✓ Fixed | A |
| BUG-P6-8 (status fetch timeout) | ✓ Fixed | A |
| BUG-P6-9 (Origin-based CORS) | ✓ Fixed | A |
| A4 (version-sync preflight) | ✓ Fixed | A |
| CQ6-1 (ImageOps hoist) | ✓ Fixed | B |
| CQ6-2 (single storage read) | ✓ Fixed | B |
| CQ6-3 (`claude-usage-status` thresholds) | ✓ Fixed | B |
| CQ6-4 (surface tier signals) | ✓ Fixed | B |
| CQ5 (pass-5, three-Python heredocs) | ✓ Fixed | B — closed by CQ6-4 restructure |
| CQ6-8 (notify rate limit) | ✓ Fixed | B |
| CQ6-9 (fail-loud on unknown day) | ✓ Fixed | B |
| CQ6-10 (extra test-deb-verify checks) | ✓ Fixed | B |
| CQ6-11 (chmod scope) | ✓ Fixed | B |
| CQ6-12 (PRIVACY.md fields) | ✓ Fixed | B |
| CQ6-5, CQ6-6, CQ6-7, CQ6-13, CQ6-14 | Deferred — see plan |
| CQ8 (pass 5, Activities-search) | Deferred — needs live GNOME test |
| A1, A2, A3, A5 | Deferred — backlog |
