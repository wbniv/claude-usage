# Code Review — Pass 14 (post-0.11.10, full-codebase sweep)

**Date:** 2026-05-18
**Reviewer:** Claude (Opus 4.7, max effort, 1M context, "ultrathink")
**Scope:** Full codebase at HEAD (`7c46e36`). Particular attention to (a) the diff since pass-13 (`c717d45..HEAD`), (b) every file the port-discovery review (`ecf24ad`) was scoped to skip, and (c) live runtime evidence from the maintainer's machine.
**Prior work:** [pass-13](2026-05-18-code-review-pass13.md), [port-discovery review](2026-05-18-port-discovery-review.md), [comprehensive review](2026-05-18-code-review-comprehensive.md), [docs/wont-fix.md](../wont-fix.md)

---

## 1. Executive Summary

| Sev | # | ID | Title |
|-----|---|----|-------|
| **High** | 1 | **V‑2** (materialised) | `server/usage-server.py:28 VERSION = '0.11.8'` while every other version source is `0.11.10`. `/hello` and `X-Claude-Usage-Server` advertise 0.11.8 *right now*. Predicted as Info in the port-discovery review; the very next release proved the prediction. |
| Medium | 2 | **AS‑1** | `_anthropic_status.indicator` validator rejects the *entire* POST on unknown values. The first new Statuspage indicator Anthropic adds silently kills scrape data — exactly when status info matters most. |
| Medium | 3 | **TL‑1** | `packaging/test-deb-live.sh` hard-codes `PORT=7331`. With dynamic port discovery (0.11.7+), the smoke test POSTs to a port the service may not have bound. Test passes/fails on whatever happens to be on 7331 — not the real claude-usage server. |
| Medium | 4 | **E‑12** | `scrapeAndPost`'s catch logs `"Claude Usage: local server unavailable"` for *any* failure including 4xx validator rejections. The server is reachable in that case; the log misroutes diagnostic attention. |
| Low | 5 | **T‑6** | Popup countdown threshold (`<12 h`) diverges from dock-tooltip countdown threshold (`<24 h`). Two adjacent UI surfaces flip from `⏱h:mm` to `Tue 17:00` at different points; the dock reads "⏱14:30" while the popup row simultaneously reads "resets Tue 17:00" for the same meter. |
| Low | 6 | **C‑4** | `_anthropic_status.indicator` validation error message returns Python tuple repr: `must be one of (None, 'none', 'minor', ...)`. Cosmetic, but it leaks Python internals and looks unprofessional in an HTTP error body. |
| Low | 7 | **G‑4** | `generate-icon.py` argv parsing silently accepts unrecognised flags (`--tier` without value, `--foo bar`) and runs `main()` as if no args were supplied. No `-h`/`--help`. |
| Low | 8 | **T‑7** | `tooltip.py:124-129` has three branches that all do `out.append(line)` — the elif/else split is structurally dead. |
| Low | 9 | **HM‑1** | `do_POST` Content-Type comparison is case-sensitive: `'application/json' != 'Application/JSON'`. Per RFC 7231 media types are case-insensitive. Chrome always sends lowercase so this is theoretical. |
| Low | 10 | **L‑2** | `_anthropic_status` redaction (line 250-253) is the only validator-side mutation that survives merge into `prev`. Other unknown keys at the top level pass through `{**prev, **body}` and accumulate forever in the cache. Mostly bounded by validator scope. |
| Info | 11 | **CI‑3** | Live-smoke test fixture POSTs `_ext_version: '0.11.1'` (hardcoded). Every CI run logs a "version mismatch" warning on the test server. Not breaking, but the fixture should track the manifest version. |
| Info | 12 | **CI‑4** | GH Actions docker-cache key only hashes `packaging/control` + `Dockerfile`. An apt-cached image from weeks ago can mask upstream-package regressions until the cache key changes. |
| Info | 13 | **CD‑1** | `_anthropic_status` indicator whitelist + `_VALID_INDICATORS` is defined inside `_validate()` so it's reconstructed per call. Trivial perf, but the constant belongs at module scope alongside `_VALID_ANTHROPIC_KEYS`. |

**Bottom line:** the code is now in mature shape — twelve months of incremental review have closed every structural bug, and pass-14's findings are increasingly small. **The most important finding is V‑2 materialising on the very next release** — exactly the failure mode the port-discovery review's Info-rated prediction said would happen. That's the only High; the rest are Medium-and-below polish. AS‑1 (anthropic-indicator forward-compat) is the next-most-likely-to-bite if Statuspage ever evolves its indicator set; everything else is paper cuts.

---

## 2. V‑2 — `VERSION = '0.11.8'` in usage-server.py while everything else ships 0.11.10 (High)

**File:** `server/usage-server.py:28`

```python
# Bump alongside packaging/control + chrome-extension/manifest.json on release.
VERSION = '0.11.8'
```

vs.

```
$ grep -n '"version":' chrome-extension/manifest.json
4:  "version": "0.11.10",
$ grep '^Version:' packaging/control
Version: 0.11.10
```

Two patch versions of drift between the server's self-identification and the rest of the release. The port-discovery review's V‑2 finding (rated **Info**) said:

> `usage-server.py:28` adds a fourth file to the version-bump list… `/hello`'s `version` field is informational only — no consumer validates it — so cosmetic drift if forgotten.

The **very next two releases (0.11.9 → 0.11.10) forgot it**. Live verification:

```
$ curl -s http://127.0.0.1:7331/hello
{"app": "claude-usage", "version": "0.11.8"}

$ curl -sI http://127.0.0.1:7331/hello | grep -i x-claude
X-Claude-Usage-Server: 0.11.8
```

The user's running server is .deb-installed 0.11.10 — *but the server is reporting 0.11.8*. Two release engineering opportunities (0.11.9 and 0.11.10) both missed the bump.

### Impact today
- `/hello`'s version field is informational. No consumer validates it. ✓ no functional break.
- `X-Claude-Usage-Server` header value isn't validated by `isOurs` either (the check is `header !== null`). ✓ no functional break.
- `claude-usage-status` doesn't surface `/hello`'s version. ✓ no user-visible signal.

### Impact tomorrow
The moment any consumer (claude-usage-status, a future Chrome ext gate, a debug tool) starts reading the `/hello` version, the cosmetic drift becomes load-bearing. The fix should land *before* that, not after.

### Fix

Derive `VERSION` from the manifest at module load. The pattern is already in the file (`_read_expected_ext_version`, lines 55-66). Reuse it for the server's own version:

```python
def _read_self_version():
    """Single source of truth: chrome-extension/manifest.json. Both .deb and
    source-install land it at /usr/share/claude-usage/chrome-extension/ or
    ~/.local/share/claude-usage/chrome-extension/ respectively."""
    for p in (
        Path(__file__).resolve().parent / 'chrome-extension' / 'manifest.json',
        Path('/usr/share/claude-usage/chrome-extension/manifest.json'),
        Path.home() / '.local/share/claude-usage/chrome-extension/manifest.json',
    ):
        try:
            if p.exists():
                return json.loads(p.read_text()).get('version', '0.0.0')
        except Exception:
            pass
    return '0.0.0'

VERSION = _read_self_version()
```

This collapses the version files-to-bump from four to two (`packaging/control` + `chrome-extension/manifest.json`), and the release.yml gate already enforces they agree. Pattern reuse — no new code, just renamed call.

**Recommended:** Land this before the next release. The drift will only accelerate.

---

## 3. AS‑1 — `_anthropic_status.indicator` whitelist rejects entire POST on unknown values (Medium)

**File:** `server/usage-server.py:141-144`

```python
ind = astat.get('indicator')
_VALID_INDICATORS = (None, 'none', 'minor', 'major', 'critical', 'maintenance')
if ind not in _VALID_INDICATORS:
    return f"_anthropic_status.indicator must be one of {_VALID_INDICATORS}"
```

The whitelist matches Statuspage's documented top-level indicator values today. But:

1. The validator returns an error string for unknown values, which `do_POST` upgrades to a **422 rejection of the entire payload** (line 240-243). The scrape data is lost, not just the status field.
2. `fetchAnthropicStatus` in the Chrome ext returns *whatever* indicator string the Statuspage API emits. It's passed through unmodified to the POST.
3. If Anthropic ever adds a new top-level indicator (e.g., the API has historically used `investigating`, `identified`, `monitoring` for *incident* states — close enough that confusion is plausible), our validator kills every POST until we ship a fix.

This is a brittle coupling between Anthropic's API evolution and our cache writes, with no graceful degradation.

### Concrete failure mode

The day Anthropic adds a new top-level indicator value:
1. `fetchAnthropicStatus()` returns `{indicator: 'new-value', ...}`.
2. `scrapeAndPost` POSTs the full body, including new-value indicator.
3. Server validator returns 422.
4. Chrome ext logs the failure, falls into the buffered-offline path (line 318-320), then *discards* the buffer at next fetch because the 4xx response is treated as "validator-rejected, malformed" (line 351-358).
5. **No scrape data lands in the cache**. The user sees stale meters + `⚠ N scrape attempts failed`.

The status-only error path (lines 285-292, 422-435) also includes `_anthropic_status` → also rejected → also fails. The system completely stops updating until either Anthropic reverts or we ship a server-side fix.

### Fix

Two non-exclusive options:

1. **Drop unknown indicators rather than reject** — same pattern as the validator-side redaction for unknown `_anthropic_status` keys (line 245-253):
    ```python
    if ind not in _VALID_INDICATORS:
        # Forward-compat: silently strip unknown indicator rather than reject the whole POST
        astat = dict(astat)
        astat['indicator'] = None
        body['_anthropic_status'] = astat
    ```
    This widens the safety margin without changing the validation contract for known values.

2. **Loosen the validator to "bounded string"** — keep the indicator field as a free string, length-bounded like other `_anthropic_status` fields:
    ```python
    err = _bounded_str(astat.get('indicator'), '_anthropic_status.indicator')
    if err:
        return err
    ```
    Drop the whitelist entirely. The GNOME extension's display logic (`extension.js:391`) already does `astat.indicator && astat.indicator !== 'none'` — so any unknown value just shows as a broken tier with the description. Graceful degradation by construction.

**Recommended:** Option 2 (loosen to bounded string). The indicator value is downstream-display-only; the whitelist provides no real safety, only fragility.

---

## 4. TL‑1 — `test-deb-live.sh` hard-codes the port (Medium, CI smoke test)

**File:** `packaging/test-deb-live.sh:16`

```bash
PORT="${CLAUDE_USAGE_PORT:-7331}"
```

This was correct before 0.11.7 (dynamic port discovery), when the server always bound 7331. After 0.11.7, the server falls through to 7332..7340 if something else is squatting on 7331. The CI smoke test doesn't pin `CLAUDE_USAGE_PORT` for the service — it just talks to whatever's on 7331.

### Concrete failure mode on a contended port

On the bare GH Actions runner:
1. The runner's setup pre-installs the .deb. `postinst` auto-runs `claude-usage-setup` for `SUDO_USER` (the runner user).
2. The runner user's claude-usage-fetch.service starts and binds 7331.
3. The script stops the SUDO_USER service (lines 42-51) to free 7331 for cu-smoke.
4. cu-smoke's service starts.

Step 3 is best-effort with `|| true`. If the stop fails (race, permission), 7331 is still bound. cu-smoke's service falls through to 7332. The test then POSTs to 7331 — hitting the SUDO_USER's still-active server, which is in a different working directory and may have a different cache file. The verify step reads `/home/cu-smoke/.cache/claude-usage/usage.json` — empty/missing — and fails.

Even worse, if some completely unrelated process on the runner is on 7331 (very unlikely on GH Actions, but the principle stands), the test would POST to *that* process and report success/failure based on its behaviour, not the actual claude-usage code.

### Fix

After starting cu-smoke's service, read the port file the server just wrote:

```bash
# Give the service a moment to bind the port + write port file
sleep 3

PORT_FILE="/home/$TESTUSER/.cache/claude-usage/port"
if [ -f "$PORT_FILE" ]; then
    PORT=$(cat "$PORT_FILE")
    echo "==> Service bound port $PORT (from $PORT_FILE)"
else
    echo "FAIL: $PORT_FILE missing — service didn't write its port" >&2
    exit 1
fi
```

This makes the test resilient to port collisions and *also* verifies the port-file write path (which the existing test never exercises).

Alternative: pass `Environment=CLAUDE_USAGE_PORT=7331` to the service so binding is deterministic. Either works; the port-file read approach exercises more code.

---

## 5. E‑12 — `scrapeAndPost` log message misroutes diagnostic attention on 4xx (Medium)

**File:** `chrome-extension/background.js:314-321`

```js
try {
    const resp = await postUpdate(data);
    if (!resp.ok) throw new Error(`server ${resp.status}`);
    console.log(`Claude Usage: sent ${data.meters.length} meters to local server`);
} catch (e) {
    console.warn('Claude Usage: local server unavailable, using chrome.storage', e.message);
    await chrome.storage.local.set({ claude_usage: { ...data, _buffered_at: Date.now() } });
}
```

`postUpdate` returns 200/4xx with the signature header for real-server responses. The `!resp.ok` branch throws `server 422` for a validator rejection. The catch then logs "local server unavailable" — **but the server is reachable, the payload is just malformed**. The user looking at the SW console sees "unavailable" and chases the wrong root cause.

A 422 from claude-usage is interesting (means the validator caught something) and worth a distinct log. The current text routes the user to `systemctl status` or port debugging when they should be looking at `journalctl --user-unit=claude-usage-fetch.service` for the validator error.

### Fix

Distinguish the two paths:

```js
} catch (e) {
    if (e.message.startsWith('server 4')) {
        console.warn('Claude Usage: server rejected POST:', e.message,
                     '— check journalctl --user-unit=claude-usage-fetch.service');
    } else {
        console.warn('Claude Usage: local server unavailable, buffering offline:', e.message);
    }
    await chrome.storage.local.set({ claude_usage: { ...data, _buffered_at: Date.now() } });
}
```

The buffer-offline behaviour is the right fallback in both cases (the offline-flush code at lines 346-358 already handles 4xx by discarding stale buffered payloads). The change is purely in the log message routing.

---

## 6. T‑6 — Popup and dock-tooltip countdown thresholds diverge (Low)

**Files:** `gnome-extension/extension.js:60` vs `server/tooltip.py:61`

```js
// extension.js — popup row formatter
if (mins < 12 * 60)
    return `resets in ⏱${...}`;
return `resets ${day} ${...}`;
```

```python
# tooltip.py — dock launcher tooltip
if mins < 24 * 60:
    return (True, f"{mins // 60}:{mins % 60:02d}")
return (False, f"{day} {h:02d}:{mn:02d}")
```

The 0.11.10 commit (`7c46e36`) tightened the popup row's switchover from 24 h to 12 h, so resets more than half a day away show a concrete day+time. `tooltip.py::parse_reset` was *not* updated. Result: for any meter that resets 12-24 hours from now, the dock tooltip says `⏱14:30` while the popup row simultaneously says `resets Tue 17:00`. Two adjacent UI surfaces disagreeing about how to render the same value.

### Fix

Pick one threshold and apply it to both. The commit message argues for 12 h ("resets more than half a day away show a concrete timestamp") — that logic applies equally to the dock tooltip. Change `tooltip.py:61`:

```python
if mins < 12 * 60:
    return (True, f"{mins // 60}:{mins % 60:02d}")
return (False, f"{day} {h:02d}:{mn:02d}")
```

Single source of truth would be better long-term, but the two files are pure functions that don't share a process — a constant + comment is the lightest fix.

---

## 7. C‑4 — Validator error message leaks Python tuple repr (Low, cosmetic)

**File:** `server/usage-server.py:144`

```python
return f"_anthropic_status.indicator must be one of {_VALID_INDICATORS}"
```

Renders as:

```
_anthropic_status.indicator must be one of (None, 'none', 'minor', 'major', 'critical', 'maintenance')
```

In an HTTP API error body, the Python tuple syntax is jarring. The fix:

```python
_VALID_IND_DISPLAY = ', '.join(repr(v) for v in _VALID_INDICATORS)
# ...
return f"_anthropic_status.indicator must be one of: {_VALID_IND_DISPLAY}"
```

Or simpler, hardcode the display string. Moot if AS‑1 is fixed by loosening the validator.

---

## 8. G‑4 — `generate-icon.py` silently accepts unrecognised flags (Low)

**File:** `server/generate-icon.py:241-260`

```python
if __name__ == '__main__':
    try:
        if len(sys.argv) >= 2 and sys.argv[1] == '--baseline':
            if len(sys.argv) < 3:
                print('usage: generate-icon.py --baseline DEST', file=sys.stderr)
                sys.exit(2)
            generate(0, 0, dict(DEFAULTS), Path(sys.argv[2]), draw_rings=False)
            sys.exit(0)
        tier_override = None
        if len(sys.argv) >= 3 and sys.argv[1] == '--tier':
            if sys.argv[2] not in ('normal', 'stale', 'broken'):
                print(f"usage: generate-icon.py --tier {{normal,stale,broken}}", file=sys.stderr)
                sys.exit(2)
            tier_override = sys.argv[2]
        main(tier_override)
```

Behaviour:
- `generate-icon.py` → main() ✓
- `generate-icon.py --baseline DEST` → baseline mode ✓
- `generate-icon.py --tier broken` → tier override ✓
- `generate-icon.py --tier` (no value) → `len < 3` → silently falls through to `main()` ✗
- `generate-icon.py garbage foo` → silently falls through to `main()` ✗
- `generate-icon.py -h` / `--help` → silently runs main() ✗

The shell scripts and the GNOME extension always pass correct args, so this is more "API design" than "bug". But the silent fall-through is the kind of thing that bites later when someone tries to debug from the command line.

### Fix

Add a usage handler at the top and reject anything else:

```python
if __name__ == '__main__':
    USAGE = (
        "Usage: generate-icon.py                        # render from cache\n"
        "       generate-icon.py --baseline DEST        # render placeholder tile\n"
        "       generate-icon.py --tier {normal,stale,broken}  # override tier"
    )
    args = sys.argv[1:]
    if args and args[0] in ('-h', '--help'):
        print(USAGE); sys.exit(0)
    try:
        if args and args[0] == '--baseline':
            if len(args) != 2:
                print(USAGE, file=sys.stderr); sys.exit(2)
            generate(0, 0, dict(DEFAULTS), Path(args[1]), draw_rings=False)
            sys.exit(0)
        tier_override = None
        if args and args[0] == '--tier':
            if len(args) != 2 or args[1] not in ('normal', 'stale', 'broken'):
                print(USAGE, file=sys.stderr); sys.exit(2)
            tier_override = args[1]
        elif args:
            print(USAGE, file=sys.stderr); sys.exit(2)
        main(tier_override)
    # ...
```

Matches the CLAUDE.md rule "All shell scripts handle `-h`/`--help`" — extended to Python entry-points.

---

## 9. T‑7 — `tooltip.py::update_desktop` has structurally dead branches (Low)

**File:** `server/tooltip.py:117-129`

```python
lines = DESKTOP.read_text().splitlines()
out = []
for line in lines:
    if line.startswith('Name='):
        out.append(f'Name={name}')
    elif line.startswith('Icon='):
        out.append(f'Icon={icon_path}')
    elif line.startswith('#'):
        out.append(line)
    elif line.startswith('[') or '=' in line or line == '':
        out.append(line)
    else:
        out.append(line)
```

The last three branches all do `out.append(line)`. The elif/else split has no observable effect — every line that isn't `Name=` or `Icon=` ends up appended unchanged regardless of which branch wins.

The intent was probably to drop "unknown" lines for safety, but the catch-all `else` branch defeats that. Either:

- **Tighten to drop unknown content**: change the `else` to a `continue` (or drop it), and add explicit drop logic for non-desktop-entry-shaped lines.
- **Simplify to one branch**: collapse to `else: out.append(line)`.

The first interpretation is brittle (a future `.desktop` format addition would be silently stripped). Recommend the second:

```python
for line in lines:
    if line.startswith('Name='):
        out.append(f'Name={name}')
    elif line.startswith('Icon='):
        out.append(f'Icon={icon_path}')
    else:
        out.append(line)
```

Three lines of net deletion. The behavior is identical to what's currently shipping.

---

## 10. HM‑1 — `do_POST` Content-Type comparison is case-sensitive (Low)

**File:** `server/usage-server.py:212-218`

```python
ct = self.headers.get('Content-Type', '').split(';')[0].strip()
if ct != 'application/json':
    self.send_response(415)
    # ...
```

Per [RFC 7231 §3.1.1.1](https://www.rfc-editor.org/rfc/rfc7231#section-3.1.1.1), media type values are case-insensitive. The server should accept `Application/JSON`, `APPLICATION/JSON`, etc. Chrome always sends lowercase so this is theoretical, but the one-character fix is:

```python
if ct.lower() != 'application/json':
```

Belt-and-braces. No downside.

---

## 11. L‑2 — Top-level unknown keys pass through merge into the cache (Low)

**File:** `server/usage-server.py:279`

```python
body = {**prev, **body}
```

The merge spreads prev then body. The validator only rejects *malformed* known keys; unknown keys at top level are silently accepted and persisted. A buggy or malicious Chrome ext could POST `{"_my_field": "anything"}` and the field lands in `usage.json` forever, surviving every subsequent merge.

Counterargument: this is intentional (`_period_lengths`-style accumulator forward-compat) and bounded by the 256 KiB payload limit. The Chrome ext is the only source of POSTs, and it's controlled by us. So the risk surface is "a buggy future Chrome ext stamps garbage that we then can't easily clean out."

The redaction pattern is already implemented for `_anthropic_status` keys (lines 245-253) — same pattern at the top level would close the gap:

```python
# Drop unknown top-level keys to prevent garbage accumulation
_VALID_TOP_KEYS = {'meters', 'plan', '_timestamp', '_scrape_fail_count',
                   '_anthropic_status', '_period_lengths', '_ext_version',
                   '_schema', '_buffered_at'}  # _buffered_at: from offline flush
body = {k: v for k, v in body.items() if k in _VALID_TOP_KEYS}
```

But this can also break forward compat: a future Chrome ext that adds a new top-level field can't ship until the server is updated to whitelist it. The asymmetry between forward-compat at top level vs. inside `_anthropic_status` is mild and probably acceptable. Carry as Low.

---

## 12. CI‑3 — Live-smoke fixture hardcodes `_ext_version: '0.11.1'` (Info)

**File:** `packaging/test-deb-live.sh:93`

```bash
-d '{"meters":[{"pct":42,"label":"live-smoke","reset":null,"reset_minutes":120}],"_ext_version":"0.11.1"}'
```

The fixture uses `0.11.1` regardless of the actual release version. Every CI run produces a "Chrome extension v0.11.1 differs from server-expected v0.11.10" warning in the test journal. The smoke test doesn't check for this warning, but it pollutes the log signal — a real version-mismatch issue in the field would be lost in the noise of CI-induced warnings.

### Fix

Read the version from the manifest at test time:

```bash
EXT_VER=$(python3 -c "import json; print(json.load(open('$REPO_DIR/chrome-extension/manifest.json'))['version'])")
# ...
run_as curl -sf -X POST "http://127.0.0.1:$PORT/update" \
    -H 'Content-Type: application/json' \
    -d "{\"meters\":[...],\"_ext_version\":\"$EXT_VER\"}" >/dev/null
```

(Where `REPO_DIR` would need to be the source repo root — the script doesn't currently know it. Alternative: read from `/usr/share/claude-usage/chrome-extension/manifest.json` since the .deb is already installed.)

Keep one POST with the *old* version too — that's the second POST (line 100-102) labelled "old-shape probe payload (no _ext_version, no reset_minutes)", which intentionally exercises the V-1 backcompat path. Good as-is.

---

## 13. CI‑4 — Docker image cache key misses upstream Ubuntu drift (Info)

**File:** `.github/workflows/release.yml:43-44`

```yaml
- name: Cache 24.04 test image
  uses: actions/cache@v4
  id: docker-cache-2404
  with:
    path: /tmp/test-image-2404.tar
    key: deb-test-image-2404-${{ hashFiles('packaging/control', 'packaging/test-deb.Dockerfile') }}
```

The cache key changes only when `packaging/control` or `Dockerfile` change. If `ubuntu:24.04` is updated upstream (security patches, Python point releases, etc.), the cached test image still runs on the *old* apt index. A regression introduced by a new upstream package version wouldn't be caught until the cache key happens to change.

This is a known tradeoff for fast CI. Mitigations:
- Add a weekly cache bust: include `${{ github.run_number }}` divided by some number, or a calendar-week token.
- Add a smoke step that runs against a fresh `ubuntu:24.04` periodically (cron-triggered workflow, not on every release).

Both are infrastructure changes beyond the .deb code itself. Carry as Info — visible only if upstream Ubuntu evolves in a way that breaks our package.

---

## 14. CD‑1 — `_VALID_INDICATORS` constant defined inside `_validate()` (Info)

**File:** `server/usage-server.py:142`

```python
def _validate(body):
    # ...
    if astat is not None:
        # ...
        ind = astat.get('indicator')
        _VALID_INDICATORS = (None, 'none', 'minor', 'major', 'critical', 'maintenance')
        if ind not in _VALID_INDICATORS:
            return f"..."
```

The other validator-side constants (`_VALID_ANTHROPIC_KEYS`, `MAX_STR_LEN`, `CACHE_SCHEMA`) live at module scope. `_VALID_INDICATORS` should too — it's reconstructed on every call right now. Performance impact is negligible; correctness impact is zero. Move for consistency.

If AS‑1 is fixed by loosening the validator, this finding is moot.

---

## 15. Items verified as non-issues this pass

Sanity-checked while reading the source. Recorded so they don't surface again.

| Item | Verdict | Why |
|------|---------|-----|
| `Handler.end_headers` adds X-Claude-Usage-Server on all responses incl. 404/415 | ✓ correct | Buffered headers — the signature ships with every response, even error ones. Chrome ext's `isOurs` check works on 4xx as intended. |
| `_period_lengths: {}` eviction on no-meters POST | ✓ guarded | Line 299 `if current_labels:` prevents eviction when the POST is status-only (no meters). Accumulator survives. |
| `_iconNormal`/`_iconRed` GIcon refs leak on destroy | ✓ non-issue | Already documented in wont-fix.md; GJS GCs the refs. |
| Race between `_loadData` async callback and `destroy` | ✓ fixed (L-1 from pass 13) | `_destroyed` flag guards both call site and callback. |
| Race between server-spawned `generate-icon.py` and GNOME-ext-spawned `generate-icon.py` | ✓ non-issue | Both use timestamped output paths + atomic `.desktop` writes; last write wins; cleanup is mtime-based with 1 s grace window. |
| `do_POST` body field validates `_ext_version` length-only | ✓ correct by design | Bounded string per V-1; format check would be over-engineering. |
| `fetchUsage` finally → `createdTab` rename | ✓ fixed (P-1 from port-discovery) | Verified at line 437-440; `createdTab` references match the declaration at line 331. |
| `postUpdate` requires `X-Claude-Usage-Server` header on every response | ✓ correct | `isOurs` check at line 72; squatters without our middleware return without the header and trip the re-probe path. |
| `parseResetMinutes` returns `null` for unknown day in three-char form | ✓ correct | Line 153: `if (!(day in wdMap)) return null;` — happy-path day strings are exhaustive. |
| `scrapeAndPost` Section 1 label filter (`Plan usage limits`, `Weekly limits`, `Learn more`) | ✓ correct | Catches header rows; tested in scraper.test.js. |
| `update_desktop` icon_path=None tick avoids clobbering Icon= line | ✓ correct | Targeted `re.sub` on Name= only when icon_path is None — concurrent generate-icon.py's Icon= write is preserved. |
| `_bind` fail with both `CLAUDE_USAGE_PORT` set AND range exhausted | ✓ correct | Lines 386-403: pin uses single-candidate list; range exhaustion message is clear. |
| `_anthropic_status` redaction (line 250-253) survives merge | ✓ correct | Redaction runs on `body[...]` before the `body = {**prev, **body}` merge, so the cleaned dict is what gets spread. |
| `meterOpacity` applied to `PopupMenuItem.opacity` (new in 0.11.10) | ✓ correct | Re-applied on every `_updateDisplay()` rebuild; old items are removed in `removeAll()`. |
| `formatRows` Sonnet-0% filter | ✓ correct | Single check in extension.js:458; filter is "label contains sonnet AND pct === 0". |
| `_isSelectable` filter for panel-metric scroll | ✓ correct | Same Sonnet-0% rule layered on `_isEligible`. |
| Schema mismatch warning fires once per session | ✓ correct | `this._schemaWarned` instance attribute survives multiple `_loadData` calls within one extension lifetime. |
| `parseResetMinutes` weekday-form min 24-day cap | ✓ correct | `Math.min(..., 60 * 24 * 31)` at line 163; matches validator's reset_minutes upper bound. |

---

## 16. Items deliberately not in scope

These could be tightened but the cost-benefit doesn't justify the change at current maturity:

| Item | Why deferred |
|------|--------------|
| Compact JSON cache file (`json.dumps(body)` vs `indent=2`) | Saves ~50% disk per write but harms human readability in `cat ~/.cache/claude-usage/usage.json`. Cache is < 2 KB anyway. |
| Slow loris on POST body read | Server binds 127.0.0.1 only; the attacker is the local user, who has easier paths. |
| Chunked transfer encoding support | Chrome ext never uses chunked. Defensive coding for a path no real client takes. |
| Throttle `generate-icon.py` spawns | Server spawn rate is 1 per POST = 1 per 7 min max. Already low. |
| HTML escaping in `Statuspage description` field | Field is plain text into a GNOME `set_text` call (St.Label), not HTML. No XSS surface. |
| Persist tier across `enable/disable` (`_lastTier` resets) | Cost: one redundant icon regen per session start. Already minimal. |

---

## 17. Recommended action order

| # | Sev | Effort | Action |
|---|-----|--------|--------|
| 1 | **High** | XS | **V‑2** — derive `VERSION` from `chrome-extension/manifest.json` at module load. One function definition + one line change. The drift is real *today* on the live system. |
| 2 | Medium | S | **AS‑1** — loosen `_anthropic_status.indicator` validation to a bounded string; or drop unknown values silently. Closes the "Anthropic adds a new indicator and our cache dies" failure class. |
| 3 | Medium | XS | **TL‑1** — `test-deb-live.sh` reads `~/.cache/claude-usage/port` after starting the service instead of hardcoding 7331. Simultaneously exercises the port-file write path. |
| 4 | Medium | XS | **E‑12** — distinguish 4xx vs network-error log messages in `scrapeAndPost`'s catch. One-line conditional. |
| 5 | Low | XS | **T‑6** — change `tooltip.py`'s 24 h threshold to 12 h for parity with extension.js's `formatReset`. |
| 6 | Low | XS | **C‑4** — display indicator whitelist as a human-readable string in the error message. Moot if AS‑1 fixes it. |
| 7 | Low | S | **G‑4** — add `-h`/`--help` to `generate-icon.py`; reject unrecognised args. |
| 8 | Low | XS | **T‑7** — collapse the three identical `out.append(line)` branches in `tooltip.py::update_desktop`. |
| 9 | Low | XS | **HM‑1** — lowercase the Content-Type comparison in `do_POST`. |
| 10 | Low | M | **L‑2** — top-level key whitelist in `do_POST` (judgement call: tightens cache shape but reduces forward-compat). |
| 11 | Info | XS | **CI‑3** — read manifest version in `test-deb-live.sh` for the fixture POST. |
| 12 | Info | M | **CI‑4** — periodic cache-bust on the docker test image. |
| 13 | Info | XS | **CD‑1** — move `_VALID_INDICATORS` to module scope. Moot if AS‑1 lands. |

**Items 1-4 should ship together as 0.11.11.** V‑2 is concrete drift; AS‑1 closes a foreseeable Anthropic-API-evolution failure; TL‑1 makes CI honest; E‑12 routes diagnostics correctly. Everything else is polish.

---

## 18. Cost vs. catch

This pass took about 45 min of focused attention: full reads of every source file with prior reviews as ground-truth lookup, live runtime verification of `/hello` and `X-Claude-Usage-Server`, and a deliberate look at every file the port-discovery review's narrow scope skipped (`tooltip.py`, `scripts/claude-usage-status.py`, `gnome-extension/prefs.js`, `packaging/*`, `Taskfile.yml`).

**13 new findings.** One High (V-2 materialised — the most viscerally satisfying catch of the pass, because the previous review *predicted* it and the prediction came true on the very next release). Three Mediums: AS-1 (forward-compat hazard the validator currently fails), TL-1 (port-discovery feature didn't update its own test), E-12 (logging routes the user wrong). The rest are paper cuts.

Patterns from this pass:

1. **Predicted-Info findings reify as bugs.** V-2 was rated Info three days ago and became real before any other finding from that review landed. Future Info-rated findings that name a specific file and a specific bump risk should probably be re-evaluated as Low and fixed proactively — the cost of fixing is small, and the cost of forgetting is exactly the kind of release-engineering miss we just saw.

2. **Feature work tends to forget its own tests.** TL-1 is dynamic port discovery's smoke test still hardcoding 7331. The plan that introduced the feature included verification steps but didn't update the existing CI test. Worth a checklist item: "for every feature that changes a runtime variable, audit the existing test fixtures."

3. **Cross-process UX consistency is fragile.** T-6 (12 h vs 24 h threshold) is two functions doing the same conceptual job at different points of the codebase. A constants module (`docs/ui-thresholds.md`? a shared `constants.py` imported by both?) might be overkill at current size, but the divergence already exists and will widen.

4. **Validators that whitelist external API values are a slow-motion incident.** AS-1 will produce a complete data-loss incident the day Anthropic adds a new indicator. We can't predict when; we can predict that it will happen. The fix is cheap — apply it.

5. **The diff trap is gone.** Pass-13's recurring observation was "reviewers read the diff, not the surrounding code." Pass-14 caught nothing in the surrounding code that hadn't been caught already — meaning either the previous passes' full reads cleaned house, or this pass missed similar bugs. The new findings are all at the seams (validator/API, test/feature, log message/diagnostic), not in the bodies of any function. That's where mature code rots next.
