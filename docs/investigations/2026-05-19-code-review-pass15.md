# Code Review — Pass 15 (post-0.11.11, full-codebase sweep)

**Date:** 2026-05-19
**Reviewer:** Claude (Opus 4.7, max effort, 1M context, "ultrathink")
**Scope:** Full codebase at HEAD (`cb6ae18`). Code diff since pass-14 (`7c46e36..HEAD`) is one JSDoc-comment fix and an empty `.claude/settings.json` stub — so this pass is primarily a fresh-eyes re-read with deliberate attention to (a) live runtime evidence on the maintainer's machine, (b) areas pass-14 did not drill into (`postinst`/upgrade path, validator edge cases beyond the new bounded-string contract, Python ↔ JS parser parity), and (c) revisiting pass-14's two deferred items (L‑2, CI‑4).
**Prior work:** [pass-14](2026-05-18-code-review-pass14.md), [pass-13](2026-05-18-code-review-pass13.md), [port-discovery review](2026-05-18-port-discovery-review.md), [comprehensive review](2026-05-18-code-review-comprehensive.md), [docs/wont-fix.md](../wont-fix.md)

---

## 1. Executive Summary

| Sev | # | ID | Title |
|-----|---|----|-------|
| **High** | 1 | **U‑1** | `.deb` upgrade does not restart the running user service. The 0.11.11 .deb installs new code to `/usr/share/claude-usage/usage-server.py` but `postinst` → `claude-usage-setup` calls `systemctl --user enable --now`, which is a no-op against an already-running service. The maintainer's running server was still reporting `version: 0.11.8` at review-time, even though every other version source on disk is `0.11.11`. Pass-14's V‑2 fix landed in code; the deploy mechanism doesn't deploy it. |
| Medium | 2 | **TS‑1** | `_timestamp` is accepted unbounded by the validator. A future-dated browser clock OR a one-line malicious POST writes a cache with `_timestamp` years in the future. The GNOME extension's age calculation goes negative, every threshold (`age > 20`, `age > 15`) evaluates false, and the indicator stays pinned to NORMAL forever — silently disabling stale/broken-tier detection. Demonstrated live with `curl`. |
| Medium | 3 | **T‑8** | `server/tooltip.py::parse_reset` lacks the hour/minute range validation that the three JS twins (scraper.js, background.js, extension.js) all have. A malformed reset string (`Resets Tue 25:99 AM`) passes the regex and raises `ValueError: hour must be in 0..23` from `datetime.replace`. Caught by callers' try/except but adds full Python tracebacks to the journal where the JS twins quietly return `null`. Parity gap. |
| Low | 4 | **HM‑2** | Non-numeric `Content-Length` header crashes `do_POST` with `ValueError: invalid literal for int()` and emits a 9-line Python traceback to the journal per malformed request. Confirmed live with a raw socket POST. Not a security issue (localhost only), but a misbehaving client or a fuzzer fills the journal with tracebacks and the malformed-header case is exactly when concise diagnostics matter. |
| Low | 5 | **SC‑2** | `isHydrated()` checks `document.body.textContent`; `doScrape()` reads `document.body.innerText`. The two see different DOM (hidden nodes, `<script>` content). If hidden text contains `% used` before visible text does, hydration fires and the scrape returns zero meters. Bounded by the 30 s deadline that eventually triggers `doScrape` unconditionally. |
| Low | 6 | **I‑2** | `install.sh` and `claude-usage-setup` both branch on `gnome-extensions enable`'s exit code, but `enable` returns 0 on Wayland even though the extension code only loads after logout. The "✓ GNOME extension enabled" branch is reached *and* the user still needs to log out. Misleading success messaging. |
| Info | 7 | **SC‑3** | `chrome-extension/scraper.js` and the inlined `executeScript` func in `background.js` are structural duplicates; only the in-file comment "Keep both in sync" enforces parity. The test suite covers `scraper.js`; production runs the inlined copy. A parser fix in one path that misses the other ships green tests with a broken prod scrape. Known tradeoff (page-context can't import modules without a separate content-script entry); flagged so it remains visible. |
| Info | 8 | **PR‑1** | `postUpdate`'s first-attempt success condition is `(r.ok ‖ (r.status >= 400 && r.status < 500)) && isOurs(r)`. A 5xx response *with* our signature falls through to a full re-probe. The local server's only 5xx path is the `except Exception` catch-all that returns 400 (not 500), so this is structurally wrong but currently unreachable. Worth fixing in the same line that already handles 4xx — costs one character. |
| Info | 9 | **TF‑1** | The `.desktop` file's `Icon=` line holds an absolute path to a per-nanosecond-precision PNG in `~/.cache/claude-usage/`. `rm -rf ~/.cache/claude-usage` (a documented diagnostic step) leaves the dock launcher with a missing-icon glyph until the next regen. Self-heals within 60 s; flagged so a future "stable icon name with symlinked target" tweak is on the radar. |
| Info | 10 | **L‑3** | `serverPort` storage cache TTL is `60 * 60 * 1000` ms. After 1 hour, every `getServerUrl()` re-probes. With a 7 min scrape interval that's roughly one re-probe burst per nine scrapes; each burst fires 10 parallel `/hello` fetches. Cost is negligible (localhost), but the constant is unprincipled — extending the TTL to 12-24 h would match real-world port stability better. |

**Bottom line:** Pass-14 declared the code mature; pass-15 confirms — code drift since 0.11.11 is one JSDoc fix. The single material finding is **U‑1**, which is exactly the V‑2 pattern repeating one level up the stack: pass-14 found "running server self-reports stale version," shipped a manifest-derived-version fix, but the .deb deploy pathway never restarts the running service so the maintainer was running pass-13-era server code while the disk had pass-14's. Same failure mode (running ≠ disk), same place to look (release engineering), one step further along the pipeline.

**TS‑1** is the next-most-likely-to-bite — it's a sleeper that silently disables stale-data detection until a clock-skew or attack triggers it, and the fix is six lines.

Everything else (T‑8 down) is polish.

---

## 2. U‑1 — `.deb` upgrade does not restart the running user service (High, deploy-pipeline)

**Files:** `packaging/postinst:23-29`, `packaging/claude-usage-setup:28-30`

### Live evidence

At review start (`2026-05-19 17:25` ICT, maintainer's machine, `claude-usage` .deb installed at version 0.11.11):

```
$ md5sum /usr/share/claude-usage/usage-server.py
9e1205a4e525d34663461b8e9fd5c6cc  /usr/share/claude-usage/usage-server.py
$ grep "_MANIFEST_VERSION\|^VERSION" /usr/share/claude-usage/usage-server.py
_MANIFEST_VERSION = _read_manifest_version()
VERSION = _MANIFEST_VERSION or '0.0.0'
EXPECTED_EXT_VERSION = _MANIFEST_VERSION

$ curl -s http://127.0.0.1:7331/hello
{"app": "claude-usage", "version": "0.11.8"}
$ curl -sI http://127.0.0.1:7331/hello | grep X-Claude
X-Claude-Usage-Server: 0.11.8

$ systemctl --user status claude-usage-fetch.service | head -3
● claude-usage-fetch.service - …
     Active: active (running) since Mon 2026-05-18 23:26:46 +07; 17h ago
```

The disk file has pass-14's V‑2 derived-version code. The running server is reporting **0.11.8**, which is the literal-version code from `0.11.10` and earlier (pass-13-era). Service started time (23:26:46) predates the 0.11.11 commit (`7054f2c` at 02:26:57 the next morning).

Manual restart fixes it:

```
$ systemctl --user restart claude-usage-fetch.service
$ curl -s http://127.0.0.1:7331/hello
{"app": "claude-usage", "version": "0.11.11"}
```

### Root cause

`packaging/postinst` calls `claude-usage-setup` for the `SUDO_USER` on `configure`. `claude-usage-setup:28-30`:

```bash
systemctl --user daemon-reload
systemctl --user reset-failed claude-usage-fetch.service 2>/dev/null || true
systemctl --user enable --now claude-usage-fetch.service
```

Per systemctl(1):

> **--now** When used with `enable`, the units will be also started.

For an **already-running** unit, `enable --now` is structurally a no-op on the started side: it (re-)creates the symlink and exits 0 without touching the running process. `daemon-reload` reloads unit files in memory, but the running Python process has long since `exec()`'d and holds no inotify on its source file. The fresh code on disk never runs until the user manually restarts.

### Why it matters

- Every release ships a new server version that pass-14's V‑2 fix is now supposed to keep in sync via the manifest. But V‑2's whole point is "the server self-identifies via /hello" — and the server can't self-identify the new version if it's *still the old binary in memory*. The fix is logically correct but operationally void.
- Validator changes (AS‑1 in pass-14 loosened `_anthropic_status.indicator`) are not deployed either. The maintainer running 0.11.8 today would have whatever validator 0.11.8 shipped — not the newly-shipped one.
- The user has no visible signal that the upgrade didn't take. `claude-usage-status` reports "Service: running" without disambiguating "running which version."

### Fix

Replace `enable --now` with `enable` + `restart` in `claude-usage-setup:28-30`:

```bash
systemctl --user daemon-reload
systemctl --user reset-failed claude-usage-fetch.service 2>/dev/null || true
systemctl --user enable claude-usage-fetch.service
systemctl --user restart claude-usage-fetch.service
```

`restart` against an inactive unit is equivalent to `start`, so this covers both "fresh install" and "upgrade with running service" with one command. No conditional branching needed.

Equivalent change in `install.sh:140`.

Optional follow-up: have `claude-usage-status` surface a "running version differs from on-disk version" warning by comparing `/hello`'s version to `/usr/share/claude-usage/chrome-extension/manifest.json` — a one-shot check that would have flagged this at the moment the review started.

### Severity rationale

High because:
- It silently undeploys every release. The fix lands in code, the .deb builds, the apt install completes — but the user's actual server stays on the prior version until they happen to reboot or manually restart.
- Demonstrated *today* on the maintainer's own machine, not theoretical.
- The fix is two lines and matches the deploy-pipeline guidance in `~/SRC/CLAUDE.md`: "After installing, the entire stack must be rebuildable from code + a handful of secrets."

Not Critical only because the user-visible impact is bounded: an unrestarted 0.11.10 server still works correctly for users on 0.11.10 Chrome extensions; the silent drift is between the *intended* and *actual* deployment, not between the running components.

---

## 3. TS‑1 — Validator accepts unbounded `_timestamp` (Medium)

**File:** `server/usage-server.py:167-170`

```python
ts = body.get('_timestamp') or body.get('timestamp')
if ts is not None and (isinstance(ts, bool) or not isinstance(ts, (int, float))):
    return "'_timestamp' must be a number"
```

The validator checks that `_timestamp` is *some* number, but does not bound it. The downstream consumers all assume "seconds-since-epoch close to now":

- `gnome-extension/extension.js:380`: `age = Math.round((Date.now() / 1000 - d._timestamp) / 60)`
- `scripts/claude-usage-status.py:37`: `ts_min = int((time.time() - d.get('_timestamp', 0)) / 60)`
- `server/tooltip.py:32`: `elapsed_min = max(0, int((time.time() - anchor_ts) // 60))`

`tooltip.py`'s `max(0, …)` is the only site that defensively clamps.

### Confirmed live

```
$ curl -s -w "HTTP=%{http_code}\n" -X POST http://127.0.0.1:7331/update \
    -H 'Content-Type: application/json' \
    -d '{"_timestamp": 99999999999, "_ext_version": "0.11.11"}'
okHTTP=200

$ cat ~/.cache/claude-usage/usage.json | grep _timestamp
    "_timestamp": 99999999999,
```

99999999999 = year 5138. Server accepted and persisted.

### Concrete failure mode

In `extension.js:380-409` after this POST lands:
- `age = Math.round((Date.now()/1000 - 99999999999) / 60)` — large *negative* number
- `age > 20` — false (broken-tier branch skipped)
- `age > 15` — false (stale-tier branch skipped)
- The cache could be infinitely stale and the GNOME extension would never flip to stale/broken
- The age label flips to `… ${age}m ago` rendering negatives like `-1666612345m ago`

The icon stays normal. The popup status row shows a nonsense negative age. Stale-data detection is silently disabled until the next POST with a sane timestamp arrives.

Attack vector: a single curl from any process the user has running. Even without malice, a misconfigured browser clock (Date.now() pulled from a year-skewed system) would write this exact poisoned state every 7 minutes.

### Fix

Add a sanity bound to `_validate`:

```python
ts = body.get('_timestamp') or body.get('timestamp')
if ts is not None:
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return "'_timestamp' must be a number"
    # legacy `timestamp` is epoch-ms; current `_timestamp` is epoch-s. Bound both
    # to "within a year of now" — any clock skew that wide is bad data, not a
    # legitimate write we want to persist.
    now = time.time()
    ts_s = ts / 1000 if body.get('timestamp') and not body.get('_timestamp') else ts
    if not (now - 365*86400 < ts_s < now + 86400):
        return "'_timestamp' is implausibly far from server time"
```

The asymmetric tolerance (1 year past, 1 day future) keeps backfill scenarios working while clamping browser-clock skew. The legacy-`timestamp` epoch-ms path needs the `/1000` translation for the bound check (the existing assignment at line 296 already does this conversion downstream).

### Why Medium not Low

The exploit is one curl line, the impact is "stale-data detection silently broken," and the test surface (`server/tests/test_validate.py`) doesn't currently check for unreasonable timestamps. The threshold to "this is a bug a user would file" is one accidentally-future-dated VM.

---

## 4. T‑8 — `tooltip.py::parse_reset` lacks h/mn range check (Medium, parity gap)

**File:** `server/tooltip.py:42-46`

```python
m = re.match(r'[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)', reset)
if m:
    day, h, mn, ap = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    if day not in WD_MAP:
        return None
    if ap == 'PM' and h != 12: h += 12
```

The regex `(\d+):(\d+)` does not bound digit count. A literal like `Resets Tue 25:99 AM` passes; `h = 25`, `mn = 99`. Falls through to:

```python
target = (now + datetime.timedelta(days=ahead)).replace(
    hour=h, minute=mn, second=0, microsecond=0)
```

→ `ValueError: hour must be in 0..23`.

The JS twins all guard the ranges. `chrome-extension/scraper.js:21-22`:

```js
let h = parseInt(hStr, 10), mn = parseInt(mnStr, 10);
if (h < 1 || h > 12 || mn < 0 || mn > 59) return null;
```

Same in `background.js:148` and `gnome-extension/extension.js:44-49`.

### Caller behaviour

The exception isn't fatal — both call sites wrap:
- `server/usage-server.py:380-386` (`_tooltip_tick`): outer try/except logs `tooltip tick: …` and continues. Tooltip update for that tick is skipped, but the server stays up.
- `server/generate-icon.py:276-278` (`main`): outer try/except logs `generate-icon: …` and exits 1. Icon regen is skipped for that POST; next 60 s tick or next scrape retries.

So the impact today is "occasional tooltip/icon refresh skip + Python traceback in journal." Not user-facing-broken, but the traceback noise hides real errors.

### Fix

Add the same range check the JS side has:

```python
m = re.match(r'[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)', reset)
if m:
    day, h, mn, ap = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    if day not in WD_MAP:
        return None
    if not (1 <= h <= 12 and 0 <= mn <= 59):
        return None
    if ap == 'PM' and h != 12: h += 12
```

Three-line change.

### Why Medium

Pass-14 carries multiple "JS/Python parity" findings as Low. This one is upgraded to Medium because (a) the failure mode is a raised exception (vs the JS side's silent `null` return), and (b) the only thing keeping it bounded is two `except Exception` blocks that swallow all errors — adding more traceback noise to those swallowers makes legitimate failures harder to spot.

---

## 5. HM‑2 — `do_POST` Content-Length parse raises ValueError (Low)

**File:** `server/usage-server.py:231`

```python
length = int(self.headers.get('Content-Length', 0))
```

If the header is non-numeric, `int(...)` raises `ValueError` *before* the `length <= 0 or length > 256*1024` check. `BaseHTTPRequestHandler.handle_one_request` swallows the exception, dumps a full traceback to stderr (→ journal), and closes the connection without sending a response.

### Confirmed live

```
$ python3 -c '
import socket
s = socket.socket(); s.connect(("127.0.0.1", 7331))
s.send(b"POST /update HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: garbage\r\n\r\n{}")
print(s.recv(4096).decode())'

$ journalctl --user -u claude-usage-fetch.service -n 20 --no-pager
… File "/usr/share/claude-usage/usage-server.py", line 231, in do_POST
…     length = int(self.headers.get('Content-Length', 0))
… ValueError: invalid literal for int() with base 10: 'garbage'
```

Client gets an empty response (connection closed mid-status-line). Journal gets a 9-line traceback.

### Impact

- Not a security or correctness issue — server stays up, next request handled normally.
- Journal noise: every fuzzer probe, every misconfigured client, every `curl -H 'Content-Length: x'` accident produces a stack dump where a one-line "bad request: bad Content-Length" would be cleaner.
- Pass-14's HM‑1 (Content-Type case-insensitivity) made `do_POST` look like it's robust to header quirks. This one is the asymmetric gap.

### Fix

Wrap in a try/except (matches the pattern already used at line 245 for `json.loads`):

```python
try:
    length = int(self.headers.get('Content-Length', 0))
except (ValueError, TypeError):
    self.send_response(400)
    self._cors()
    self.end_headers()
    self.wfile.write(b'bad request: invalid Content-Length')
    return
```

### Why Low

- Localhost-only, no security surface.
- Doesn't break normal operation.
- Cleanup is journal-hygiene, not user-facing fix.

---

## 6. SC‑2 — `isHydrated` and `doScrape` read different DOM properties (Low)

**File:** `chrome-extension/background.js:179-184`

```js
function isHydrated() {
  return /\d+%\s*used/i.test(document.body.textContent);
}

function doScrape() {
  const body = document.body.innerText;
  …
}
```

`textContent` returns concatenated text of all descendants including `<script>`, `<style>`, and hidden elements. `innerText` returns the rendered, layout-aware text the user actually sees. Two different views of the DOM.

### Concrete failure mode

If claude.ai ever ships a hidden React-suspense placeholder containing `0% used` text (lazy loading template, hidden-by-css skeleton, etc.) that loads *before* the visible meters render:

1. `isHydrated()` matches the hidden text → resolves immediately.
2. `doScrape()` reads `innerText` → sees only the visible skeleton (no meters yet).
3. Function returns `{ meters: [] }`.
4. `scrapeAndPost` partial-update path: `_scrape_fail_count += 1`, no meters POSTed.

The 30 s observer deadline in line 261 would *also* fire a `doScrape()` against the same DOM state and still produce zero meters. So the 30 s safety isn't actually a fallback for *this* race — both paths converge on `innerText` reading the same wrong content.

The realistic frequency today is zero (claude.ai's current React tree doesn't have this pattern). But the inconsistency is the precondition; any DOM change on claude.ai's side could exhibit it.

### Fix

Use the same property in both checks:

```js
function isHydrated() {
  return /\d+%\s*used/i.test(document.body.innerText);
}
```

`innerText` is what `doScrape` consumes; matching the predicate to the consumer keeps them synchronized by construction. Slight perf cost (innerText forces layout) but only fires once-per-MutationObserver-callback — bounded.

The `scraper.js` test export already takes `textContent` as a parameter name (misleading) but is given whatever the caller passes. Update its JSDoc to match the actual input semantics. The pass-15 cleanup commit `44c655a` is on the right track.

---

## 7. I‑2 — install.sh & claude-usage-setup misreport extension-enable success on Wayland (Low)

**Files:** `install.sh:150-153`, `packaging/claude-usage-setup:37-51`

```bash
# install.sh
gnome-extensions enable claude-usage@indri.studio 2>/dev/null \
    && echo "  ✓ GNOME extension enabled" \
    || echo "  ℹ  GNOME extension registered — log out and back in to activate it"
```

```bash
# claude-usage-setup
if gnome-extensions enable "$UUID" 2>/dev/null; then
    echo "  ✓ GNOME extension enabled"
else
    …
    echo "  ℹ  GNOME extension queued — log out and back in to activate the panel"
fi
```

Both code paths assume `gnome-extensions enable` succeeds *only* when the extension is fully loaded. In practice:

- **X11**: `gnome-extensions enable` sets dconf *and* the running `gnome-shell` re-reads the extension dir on next dconf-changed signal. Extension activates without re-login. ✓ Success message accurate.
- **Wayland** (modern default): `gnome-extensions enable` sets dconf and returns 0. But `gnome-shell` cannot be restarted on Wayland — the running shell does *not* pick up freshly-installed extension code until the user logs out and back in. The success message claims the extension is enabled; the user sees no panel indicator until they happen to logout.

The "ℹ Log out" fallback only fires when `gnome-extensions enable` itself fails — typically because the extension UUID isn't known to gnome-shell yet (cold install where gnome-shell hasn't seen the .deb's files). After a `daemon-reload`-style refresh path runs, even Wayland users hit the 0-exit success branch.

### Fix

Two options:

**Option A** (minimal change): always print the log-out hint in both branches:

```bash
if gnome-extensions enable "$UUID" 2>/dev/null; then
    echo "  ✓ GNOME extension enabled (log out and back in if the panel indicator isn't visible)"
else
    …
fi
```

**Option B** (slightly more involved): detect session type and only suppress the hint on X11:

```bash
if gnome-extensions enable "$UUID" 2>/dev/null; then
    if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
        echo "  ✓ GNOME extension registered — log out and back in to activate the panel"
    else
        echo "  ✓ GNOME extension enabled"
    fi
fi
```

Option B is more accurate but adds branching for marginal gain. Recommend Option A.

### Why Low

- Functional path works (extension does activate after logout).
- Cosmetic confusion only — user sees "✓" then no panel, contacts support, gets told to log out, problem resolved.
- Existing CLAUDE.md value: "Logout is disruptive — exhaust static checks first" applies to *diagnosing* the user's session, not to the install messaging.

---

## 8. SC‑3 — `scraper.js` / `background.js` inlined-scrape duplication (Info)

**Files:** `chrome-extension/scraper.js`, `chrome-extension/background.js:178-269`

`scraper.js` exports `isHydrated`, `parseResetMinutes`, `doScrape` — the *tested* implementations. `background.js` inlines functionally-equivalent copies inside the `executeScript` `func:` callback (lines 179-256) because the page-context callback cannot import ES modules.

The in-file comment at `scraper.js:3` says:

> Keep both in sync when changing parsing logic.

That's the only enforcement. Test runs (`task test-scraper`) cover only `scraper.js`. Production code is the inlined copy. A parser fix that lands in `scraper.js` only ships green tests and a broken production scrape.

### Today's state

Diffed by hand. The two `doScrape`s are functionally identical except for one structural difference: `scraper.js` takes `extraToggleChecked` as a parameter; the inlined version reads `document.querySelector('[role="switch"][aria-label="Extra usage"]').getAttribute('aria-checked')`. Same logical result.

`isHydrated` is identical in both (modulo the SC‑2 textContent vs innerText quirk — which lives in `background.js` only).

`parseResetMinutes` is identical.

So no drift exists *right now*. The hazard is forward.

### Possible mitigations (all carry tradeoffs)

1. **Content script approach**: ship `scraper.js` as a `content_scripts` entry in `manifest.json`, hoist exports onto `window`, and call them from `executeScript`'s func. Doable but requires `webRequest` or `runtime.connect`-style coordination, and content scripts have their own lifecycle (run on every matching page navigation, not just on demand).

2. **Build-time inlining**: a tiny preprocessor that copies `scraper.js` source into `background.js`'s `executeScript` func. Adds a build step; small.

3. **Status quo**: keep the dual implementation; add a CI lint that diffs the two `doScrape` bodies and fails on mismatch.

Option 3 is the lowest-cost and the most aligned with the project's "no premature build infrastructure" stance. The lint script would be ~20 lines of node or python — strip whitespace, extract the function bodies, compare.

### Why Info (not actionable now)

- No drift today.
- All three mitigation options add complexity.
- The risk is "future change misses one side" — preventable with attention, not architecturally inevitable.

Carry on the radar.

---

## 9. PR‑1 — `postUpdate` first-attempt success condition skips 5xx-with-signature (Info)

**File:** `chrome-extension/background.js:74-78`

```js
let url = await getServerUrl();
if (url) {
  try {
    const r = await fetch(url, payload);
    if ((r.ok || (r.status >= 400 && r.status < 500)) && isOurs(r)) return r;
  } catch (_) { /* network error or wrong-server — fall through to re-probe */ }
}
```

The success condition is:
- `r.ok` (2xx/3xx) ✓
- OR 4xx within range ✓

Excluded:
- 5xx (any) — falls through to re-probe even if `isOurs(r)` is true.
- < 400 redirects with no `Location` — `r.ok` covers redirects, so this is fine.

### Reachability today

`do_POST` returns the following status codes:
- 200 (happy path)
- 400 (bad JSON, eventually HM-2's bad Content-Length when fixed)
- 413 (payload > 256 KiB)
- 415 (wrong Content-Type)
- 422 (validator rejection)

There's no path that emits 5xx. The `except Exception` block at line 344 returns 400 (`status, reply = 400, b'error'`). So PR-1 is structurally wrong but unreachable.

### Why this still rates a finding

- A future server change that returns 5xx (e.g., a `503` during in-flight reload) would trigger an unnecessary 10-fetch re-probe burst.
- The fix is one character — extend the range:

```js
if ((r.ok || (r.status >= 400 && r.status < 600)) && isOurs(r)) return r;
```

Or, semantically clearer:

```js
if (r.status < 600 && isOurs(r)) return r;
```

The second form trips on a network error (which throws, not returns), so it's equivalent for `fetch` semantics.

### Severity Info

- Unreachable in current code.
- Fix is trivial.
- Worth landing as defense-in-depth.

---

## 10. TF‑1 — `.desktop` Icon= points to a per-second-precision cache file (Info)

**Files:** `server/generate-icon.py:194-199`, `server/tooltip.py:127`

```python
# generate-icon.py:_next_icon_path
return CACHE_DIR / f'icon-{time.time_ns()}.png'

# tooltip.py:update_desktop (when icon_path is supplied)
out.append(f'Icon={icon_path}')
```

After every successful POST → `generate-icon.py` runs → writes a new PNG at a unique timestamped path → writes that absolute path into the `.desktop` file's `Icon=` line → deletes older `icon-*.png` files (line 234, `mtime < dest_mtime - 1.0`).

The system has exactly one valid icon path at any time. If the user clears the cache (documented diagnostic: `rm -rf ~/.cache/claude-usage`), the .desktop file's Icon= line still points to a file that no longer exists. The dock launcher shows the missing-icon glyph until the next scrape (≤ 7 min) or the next 60 s tooltip tick (no-op for Icon=) or the next manual `generate-icon.py` invocation.

### Why not Low

- Self-heals within 7 min on any working scrape pipeline.
- The diagnostic that triggers it (`rm -rf ~/.cache/claude-usage`) is explicitly destructive — users running it have already accepted "let me reset and see what happens."
- Pass-12+ shipped a fallback baseline icon at `/usr/share/pixmaps/claude-usage.png` for first-run state, but `tooltip.py::update_desktop` always rewrites `Icon=` on the first regen.

### Possible improvement

Have `update_desktop` write `Icon=claude-usage` (the system icon name) and use a symlink at `~/.cache/claude-usage/icon-current.png` → the latest timestamped PNG. The `.desktop` file's Icon would never need rewriting; GNOME would resolve via icon theme.

Costs: refactor of `_next_icon_path` (atomic symlink swap), need to verify GNOME picks up symlink target changes without re-reading .desktop. Probably not worth doing solo; bundle with a future icon-rendering refactor.

Carry on the radar.

---

## 11. L‑3 — `serverPort` storage cache TTL is short (Info)

**File:** `chrome-extension/background.js:13`

```js
const PORT_CACHE_TTL_MS = 60 * 60 * 1000;  // 1 hour
```

`getServerUrl()` re-probes every 1 hour even without errors. With a 7 min scrape cycle, that's roughly one re-probe every 9 scrapes. Each re-probe fires 10 parallel `/hello` GETs on 127.0.0.1.

### Cost

Negligible (localhost, 10 fetches with 500 ms timeout = bounded to 500 ms wallclock). But unprincipled — a port that's been stable for an hour is overwhelmingly likely to stay stable. The TTL is the only mechanism to *recover* from "server moved to a different port" (e.g., user changed `CLAUDE_USAGE_PORT` env and restarted service), but:

- Server-moved cases also trigger `postUpdate`'s POST-path re-probe (the `isOurs` header check), which catches them within one scrape cycle.
- The TTL only matters if the user moved the port AND the cached port is somehow still answering `/hello` with the right signature — which only happens if two claude-usage instances are running on different ports, the cached one is the old one, and the old one hasn't been killed. Very narrow.

### Possible improvement

Extend TTL to 24 h (`24 * 60 * 60 * 1000`). The POST-path `isOurs` check already covers the realistic "server moved" scenarios; the TTL serves as a long-tail safety net.

Or remove the TTL entirely and rely on POST-path `isOurs` + the cache invalidation in the catch block at line 78.

### Why Info

- No correctness or perf issue today.
- Fix is one number change.
- Worth thinking about in the next port-discovery polish pass.

---

## 12. Items verified as non-issues this pass

Sanity-checked while reading. Recorded so they don't surface again.

| Item | Verdict | Why |
|------|---------|-----|
| `HTTPServer` is single-threaded → `OUTPUT.with_suffix('.json.tmp')` race | ✓ non-issue | Single-thread serialization means no two `do_POST`s ever race on the same tmp filename. Comment in code noting this for any future ThreadingHTTPServer switch would be a nice-to-have. |
| `_period_lengths` merge logic in `do_POST` (lines 281-312) clobbers between `body = {**prev, **body}` and the explicit `body['_period_lengths'] = period_lengths` reassignment | ✓ correct | The explicit reassignment after the merge is the canonical write; the intermediate spread's `_period_lengths` is overwritten by the final assignment at line 312. Traced step-by-step. |
| `signal.signal(SIGCHLD, SIG_IGN)` at line 12 reapes generate-icon.py zombies | ✓ correct | POSIX behaviour: ignored SIGCHLD auto-reaps. Pass-14's notes confirmed. |
| `_anthropic_status` validator-side redaction (lines 256-264) survives `{**prev, **body}` merge | ✓ correct | Redaction runs on `body['_anthropic_status']` before the merge spread, so the cleaned dict is what gets spread. |
| `_tooltip_tick` daemon thread vs `generate-icon.py` subprocess concurrency | ✓ correct | Both use unique-tmp filenames + atomic rename. Last write wins; bounded blip ≤ 60 s. |
| `scraper.js` `parseResetMinutes` Sunday=0 vs Python `WD_MAP` Mon=0 | ✓ correct | Independent indexing schemes; both compute `(target_wd - now.getDay() + 7) % 7` correctly within their own scheme. Cross-checked by running both against `Resets Sun 9:00 AM` mentally. |
| `_check_chrome_orphans` reads `Chrome/Default/Preferences` JSON | ✓ safe | Caught `KeyError, json.JSONDecodeError`. Chrome's atomic writes mean partial reads return either the old complete JSON or the new complete JSON — never half. |
| `gnome-extensions enable` fallback in `claude-usage-setup` writes the UUID directly to `enabled-extensions` | ✓ correct | The python-AST gsettings parsing pattern matches the existing uninstall code in install.sh:35-40. Handles `@as []` empty-list form. |
| `_validate` accepts missing `meters` for status-only POSTs | ✓ correct by design | Documented at lines 89-93. Merge in `do_POST` preserves prev's meters. |
| `EXPECTED_EXT_VERSION = _MANIFEST_VERSION` (line 53) accepts None as "disable check" | ✓ correct | When manifest read fails, mismatch check disables itself rather than rejecting all POSTs. Documented in adjacent comment. |
| `_scrollTimer` cleanup on `destroy` (line 567-570) | ✓ correct (pass-13 W-1 fix) | Verified the source removal happens before `super.destroy()`. |
| Tier transition spawn-icon-regen vs `_lastTier` state machine | ✓ correct | Every non-normal → other path or other → normal path spawns regen. Normal → normal does not. Hysteresis-correct. |
| `_anyCrit` flash + 5 min notify rate-limit interaction | ✓ correct | Notify fires on entering critical IF 5 min elapsed since last notify. Flash fires unconditionally on entering critical (unless suppressed by popup-open). Persisted across sessions via `NOTIF_CRIT_TS_FILE`. |
| `_pendingMetric` scroll-debounce nullable handling | ✓ correct | `??` operator returns left only on null/undefined; `''` (cleared) is preserved as a valid metric value. |

---

## 13. Items revisited from pass-14's deferred list

| Item | Re-verdict | Reasoning |
|------|------------|-----------|
| **L‑2** (top-level unknown keys pass through merge) | **Carry as Low; do not implement** | Forward-compat tradeoff stands. Adding a whitelist would require touching the validator on every cache-shape addition. Current bound (256 KiB payload cap + Chrome ext is the only writer) keeps the surface small. |
| **CI‑4** (docker image cache key misses upstream drift) | **Promote to Low** (was Info in pass-14) | Pass-15 didn't find any drift, but the maintainer is shipping every ~12 h and the cache could survive multiple Ubuntu point releases under that cadence. A weekly cache bust (`key: …-${YYYY-WW}`) is a 2-line change to release.yml. Worth doing in the next CI pass. |

---

## 14. Items deliberately not in scope

Same list as pass-14 (compact JSON cache, slow-loris on POST body read, chunked transfer support, throttle generate-icon.py spawns, HTML escaping in Statuspage description, persist tier across enable/disable). All still hold; cost-benefit unchanged.

Two pass-14 finds explicitly off the table:
- **C‑4** (Python tuple repr in validator error) — already moot since AS‑1 dropped `_VALID_INDICATORS`.
- **CD‑1** (`_VALID_INDICATORS` constant scope) — already moot since AS‑1 dropped the constant.

---

## 15. Recommended action order

| # | Sev | Effort | Action |
|---|-----|--------|--------|
| 1 | **High** | XS | **U‑1** — replace `enable --now` with `enable` + `restart` in `claude-usage-setup:30` and `install.sh:140`. Add optional follow-up: `claude-usage-status` warns when `/hello`'s version differs from on-disk manifest. The U-1 fix is **the single highest-leverage change in this review** — without it, every other landed fix may not actually deploy. |
| 2 | Medium | S | **TS‑1** — add `_timestamp` plausibility bound to `_validate` (±1 year past, +1 day future). Update `server/tests/test_validate.py` to cover the new bound. |
| 3 | Medium | XS | **T‑8** — add the `1 <= h <= 12 and 0 <= mn <= 59` range check in `tooltip.py::parse_reset` to match JS twins. |
| 4 | Low | XS | **HM‑2** — wrap `int(Content-Length)` in try/except, return 400 on parse failure. |
| 5 | Low | XS | **SC‑2** — change `isHydrated` to read `innerText` (not `textContent`) for parity with `doScrape`. Update `scraper.js` JSDoc to match (the `44c655a` commit started this; this finishes it). |
| 6 | Low | XS | **I‑2** — always print the "log out" hint after the success branch in `install.sh` + `claude-usage-setup`. |
| 7 | Low | XS | **PR‑1** — extend `postUpdate`'s success condition to cover 5xx-with-signature. Defense-in-depth; current code can't reach it. |
| 8 | Info | M | **SC‑3** — add a CI lint that fails when `scraper.js::doScrape` body differs from `background.js`'s inlined func body. Mitigation for the duplication, not a removal. |
| 9 | Info | XS | **L‑3** — bump `PORT_CACHE_TTL_MS` to 24 h. |
| 10 | Info | M | **TF‑1** — sketch a stable-icon-name + symlink refactor for the next icon-rendering pass. Don't do solo. |
| 11 | Low | XS | **CI‑4 (revisited)** — add weekly cache-bust token to release.yml's docker cache keys (`${{ env.YYYYWW }}` or equivalent). |

**Items 1-3 should ship together as 0.11.12.** U‑1 unbreaks the deploy pipeline; TS‑1 closes a silent-failure attack; T‑8 closes a parity gap that would generate tracebacks. The rest is polish.

---

## 16. Cost vs. catch

Pass-15's catch rate is what you'd expect after pass-14: **one structural finding (U‑1) deep in the deploy mechanism that no source-only review would have surfaced**, two semi-structural ones (TS‑1, T‑8) found by combining static reading with live POST experimentation, and seven polish items.

Total: 10 findings. **The High one was found by reading `postinst` while looking at live `systemctl status` output — not by reading code in isolation.** The Mediums were found by `curl`-poking the running server.

This is consistent with the project's review trajectory: pure-source review yields diminishing returns at this maturity; **the next reviews should keep weight on live-system experimentation**, especially around the install/upgrade boundary and the validator's accept-set.

Estimated implementation cost for the recommended action order (items 1-7, the actionable batch): ~45 lines diff across 4 files. The full 0.11.12 batch would be smaller than 0.11.11's batch.
