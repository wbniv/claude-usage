# Code Review — Dynamic Port Discovery (0.11.7)

**Date:** 2026-05-18
**Reviewer:** Claude (Opus 4.7, max effort, 1M context)
**Scope:** Just the diff of commit `d23bb4c feat: dynamic port discovery (7331-7340); bump 0.11.7` against `c717d45` (0.11.6). Plus one CRITICAL pre-existing bug caught incidentally while reading the surrounding code.
**Related:** [Plan](../plans/2026-05-18-dynamic-port-discovery.md), [pass-13 review](2026-05-18-code-review-pass13.md)

---

## 1. Executive Summary

| Sev | # | ID | Title |
|-----|---|----|-------|
| **CRITICAL** | 1 | **P‑1** | *Pre-existing, not from this diff:* `fetchUsage()` finally references undeclared `tab` (should be `createdTab`). ReferenceError throws inside `finally`, `_fetching = false` never runs, ALL subsequent `fetchUsage` calls no-op. Bricks the extension after the first call. Introduced in commit `e36c83a` (0.11.3) by the tab-reuse rename; missed by every review since. **Blocks shipping 0.11.7 .deb.** |
| High | 2 | **PD‑1** | `postUpdate` checks `r.ok` but not response body shape. If chrome.storage's cached port holds a stale value AND a squatter on that port accepts the POST with 2xx, Chrome leaks usage data to the squatter. Re-probe never fires. Privacy regression vs. the hardcoded-port version. |
| Medium | 3 | **PD‑3** | `GET /hello` accepts requests from any origin (200 + JSON body). CORS blocks the body for non-extension origins, but the request itself succeeds. Side-channel fingerprint: a page on web.example.com can probe "is claude-usage installed on 127.0.0.1?" via timing. Bounded info disclosure. |
| Medium | 4 | **PD‑2** | `AbortSignal.timeout()` requires Chrome ≥ 102 (May 2022). `manifest.json` doesn't pin `minimum_chrome_version`. Stale Chrome installs throw "AbortSignal.timeout is not a function" on every probe; SW console errors but no user-visible signal. |
| Low | 5 | **PD‑4** | Probe filter is `j.app === 'claude-usage'` only — doesn't validate the `version` field. A local impersonator returning the right `app` string would win the probe race. Trivial mitigation: also require `typeof j.version === 'string'`. |
| Low | 6 | **PD‑5** | `do_GET` path match is exact `self.path == '/hello'` — `/hello?foo=bar` returns 404. Chrome ext only sends `/hello`, so non-issue today; documented in case future probes add query strings. |
| Low | 7 | **PD‑6** | Port file (`~/.cache/claude-usage/port`) is never cleaned up on server stop or .deb postrm — survives uninstall. Cosmetic clutter; the next install overwrites it. |
| Low | 8 | **PD‑7** | `claude-usage-status` doesn't surface the bound port. Adding `Port: 7332` to the output would close one diagnostic question users will hit. |
| Low | 9 | **A‑2-followup** | `claude-usage-status.py:42-46` still says "extension flips to STALE at 10 min" and "BROKEN at 20 min" — but `extension.js` was bumped to 15-min stale (commit `c717d45`, A-2). Diagnostics + extension drift. |
| Info | 10 | **V‑2** | `VERSION = '0.11.7'` is hardcoded in `usage-server.py:28`. Adds a fourth version file to keep in sync (was three). `/hello`'s version response is informational — no consumer validates it — so the cost of drift is cosmetic. Worth deriving from `packaging/control` at module load instead. |
| Info | 11 | **PD‑8** | 10 explicit `host_permissions` entries balloon the install permission prompt. Tradeoff for MV3 not supporting port wildcards — accepted by design per the plan. |

**Bottom line:** the port-discovery feature itself is well-designed and clean — the plan's verification steps demonstrate it works end-to-end on the server side. The two priority items aren't in the port-discovery diff:

- **P-1 is a pre-existing 0.11.3 bug** that this review caught only because I re-read `fetchUsage()` in full. It MUST be fixed before any 0.11.3+ .deb ships.
- **PD-1 is the privacy edge case** the design specifically called out (multi-instance handling: "if two `claude-usage` servers somehow run, the Chrome extension takes whichever responds first") — but the engineered behavior on the PROBE path doesn't extend to the POST path.

---

## 2. P-1 — `fetchUsage` finally references undeclared `tab` (CRITICAL, pre-existing)

**File:** `chrome-extension/background.js:419-425`

```js
} finally {
    if (tab) {                                                    // ← `tab` is undeclared
        try { await chrome.tabs.remove(tab.id); } catch (_) {}
        try { await chrome.storage.local.set({ _scrape_tabs: [] }); } catch (_) {}
    }
    _fetching = false;
}
```

The variable declared at line 313 is `let createdTab = null` (renamed in 0.11.3's tab-reuse refactor, commit `e36c83a`). The body was updated to use `createdTab`; the `finally` clause was not. Verified by `grep -nE '^(const|let|var) tab\b' chrome-extension/background.js` — zero matches.

### What goes wrong

Reading an undeclared identifier on the RHS of an expression throws `ReferenceError` in both strict and sloppy modes (per ECMAScript §6.2.4.6 `GetValue` — throws on unresolvable reference, regardless of mode). Confirmed in Node 24:

```
$ node -e "
async function fn() {
    let createdTab = null;
    let _fetching = true;
    try {} finally {
        if (tab) { console.log('cleanup'); }
        _fetching = false;
        console.log('reached end, _fetching=' + _fetching);
    }
}
fn().then(() => console.log('resolved')).catch(e => console.log('rejected:', e.message));
"
rejected: tab is not defined
```

`_fetching = false` never runs. `_fetching` stays `true` for the lifetime of the service worker. Next call to `fetchUsage()` hits `if (_fetching) return;` at line 311 and returns immediately. **Every subsequent scrape is a no-op until the SW is killed.**

In practice the SW does get killed (MV3 dormancy after ~30 s idle, restart on next event). So the failure mode is: each SW lifetime can scrape exactly once. The 7-min alarm wakes the SW, fetchUsage runs, fetchUsage throws (uncaught rejection), SW eventually goes dormant, next alarm wakes a fresh SW, fetchUsage runs once, throws, ...

**Net effect**: chrome ext IS posting data, but only once per SW wake — same cadence as before, just with a guaranteed uncaught rejection logged every cycle. The bricking is less catastrophic than I first feared (since SW restarts mask it), but the rejection storm + tab-leak (tab.remove never runs) are real:

- One uncaught rejection per scrape cycle (visible in chrome://extensions SW devtools console, not journal)
- Background scrape tab orphaned until next cycle's `_scrape_tabs` cleanup at line 349-355 picks it up
- `_scrape_tabs` storage value left set across SW restarts, so next SW's orphan-cleanup catches it

### Timeline

- `e36c83a` (0.11.3, commit by me) — introduced. Old `tab` references in finally never renamed.
- `c222817` (0.11.4) — added onActivated; didn't touch finally.
- `ed22954`/`5e1968d` (0.11.5) — L-1/W-1 in extension.js (not background.js).
- `c717d45` (0.11.6) — pass-13 batch: touched background.js for N-1/N-3, didn't touch finally.
- `d23bb4c` (0.11.7) — port discovery; diff explicitly preserves the `if (tab)` line.

Four commits and two code reviews (pass-13 + this one) missed it. The pattern: every reviewer focused on the diff hunk, none re-read the unchanged finally block.

### Fix

One-line change:

```diff
  } finally {
-     if (tab) {
-         try { await chrome.tabs.remove(tab.id); } catch (_) {}
+     if (createdTab) {
+         try { await chrome.tabs.remove(createdTab.id); } catch (_) {}
          try { await chrome.storage.local.set({ _scrape_tabs: [] }); } catch (_) {}
      }
      _fetching = false;
  }
```

**This is a blocker for shipping the 0.11.7 .deb.** If the user installs 0.11.7 with this bug, the extension's SW console fills with rejections and background scrape tabs accumulate (briefly — cleaned up on next cycle).

---

## 3. PD-1 — `postUpdate` doesn't verify response shape (High)

**File:** `chrome-extension/background.js:51-67`

```js
async function postUpdate(body) {
  // ...
  let url = await getServerUrl();
  if (url) {
    try {
      const r = await fetch(url, payload);
      if (r.ok || (r.status >= 400 && r.status < 500)) return r;   // ← no body check
    } catch (_) { /* network error — fall through to re-probe */ }
  }
  url = await getServerUrl({ forceProbe: true });
  // ...
}
```

The PROBE path validates that the server identifies as claude-usage:

```js
return j && j.app === 'claude-usage' ? port : null;
```

The POST path does not. If the chrome.storage cache holds port 7331 from yesterday and 7331 is now bound by some other local server (e.g., `python3 -m http.server`, livereload, vite preview, jupyter notebook), `fetch(http://127.0.0.1:7331/update, {POST, ...})` will hit that server. Most HTTP servers return 404/405/501 for unknown POST routes → POSTs fail → re-probe → finds the real server. Safe path.

But: some servers return 200 to all routes (catch-all reverse proxies, certain frameworks in default config). For those, the POST appears successful to the Chrome extension. The data is silently delivered to the wrong server. No re-probe ever fires; the cache stays valid for an hour.

### Concrete risk surface

A user with concurrent local dev work:
- `npm run dev` (Vite) on 5173 — no collision
- `jupyter notebook` on 8888 — no collision
- `python3 -m http.server 7331` for ad-hoc file serving — collides. Default response is 200 for GET, 501 for POST. POST fails → re-probe → safe.
- `caddy` with a catch-all 200 reverse proxy on 7331 — collides. POSTs return 200 → leak.

The Caddy case is uncommon but real. More common: a dev tool that's only ever bound to 7331 because the user picked the port and then forgot. Once it accepts POSTs (even with `400 bad json` for the body), Chrome may think the POST succeeded.

Actually re-reading more carefully — the code says `r.ok || (r.status >= 400 && r.status < 500)`. The 4xx case is treated as a real server response (validator rejection). So a 400 from a squatter would NOT trigger re-probe, and the chrome ext would discard the buffered offline payload thinking it's malformed (background.js:333-339). That's WORSE than a leak: it's data loss + Chrome silently happy.

### Fix

Verify the response body shape. Two options:

1. **Check the body of every POST response** — `usage-server.py` returns `b'ok'` on success. Verify `await r.text() === 'ok'` for 2xx. Adds one await per POST. Cheap.
2. **Include the server identity in the response** — change `usage-server.py` to respond with `{"app":"claude-usage","saved":N}` instead of `b'ok'`. Chrome ext verifies `body.app === 'claude-usage'`. Slightly more invasive but the more robust signature.

Recommend option 2 — same pattern as `/hello`. The validation logic is identical and the body is structured.

---

## 4. PD-3 — `/hello` accepts cross-origin GETs (Medium, info disclosure)

**File:** `server/usage-server.py:184-200`

```python
def do_GET(self):
    if self.path == '/hello':
        payload = json.dumps({'app': 'claude-usage', 'version': VERSION}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self._cors()                              # only emits Allow-Origin for chrome-extension://
        self.end_headers()
        self.wfile.write(payload)
```

CORS prevents a page on `evil.com` from READING the response body (no `Access-Control-Allow-Origin: https://evil.com` is emitted). But the GET itself succeeds. The page can detect from timing or `fetch().catch()` whether `127.0.0.1:7331/hello` returned a JSON-typed response — i.e., fingerprint "is claude-usage installed on this user's machine?"

### Why this matters

Local-network info disclosure is a known browser concern (Chrome's "Private Network Access" RFC, deprecated APIs, etc.). Identifying which dev tools a user runs is enumeration that bounded malware uses for targeting. Not a high-priority threat for this app specifically, but the previous version of the server had no GET endpoint at all and was immune by construction.

### Fix

Either reject all non-extension origins on `/hello`:

```python
def do_GET(self):
    origin = self.headers.get('Origin', '')
    if not (origin == '' or origin.startswith('chrome-extension://')):
        self.send_response(403)
        self.end_headers()
        return
    if self.path == '/hello':
        # ...
```

Or, more strictly, require the chrome.storage-cached origin be present (the extension always sends Origin when fetching). The first is cheap and acceptable.

Note: an empty Origin (which is what Chrome sends for `fetch(...)` from a service worker to 127.0.0.1) needs to be permitted — that's the happy path.

---

## 5. PD-2 — `AbortSignal.timeout` requires Chrome ≥ 102 (Medium)

**File:** `chrome-extension/background.js:20`

```js
const r = await fetch(`http://127.0.0.1:${port}/hello`,
  { signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) });
```

`AbortSignal.timeout()` shipped in Chrome 102 (May 2022). On older Chrome installs it throws `TypeError: AbortSignal.timeout is not a function` — and the `try/catch` around the probe swallows it as `null` (failed probe). Every probe fails. No server is found. No POSTs land.

`chrome-extension/manifest.json` has no `minimum_chrome_version` field, so Chrome doesn't refuse to install. The failure is silent until the user notices the panel never updates.

### Fix

Add to manifest:

```json
"minimum_chrome_version": "102"
```

Documented at https://developer.chrome.com/docs/extensions/reference/manifest/minimum-chrome-version. Chrome refuses to install / disables the extension on older browsers with a user-visible "requires Chrome 102+" message. Cleaner failure mode than silent breakage.

Alternative (smaller blast radius if anyone is genuinely on Chrome 101): manual timeout via `setTimeout` + `AbortController.abort()`:

```js
const ctl = new AbortController();
const timer = setTimeout(() => ctl.abort(), PROBE_TIMEOUT_MS);
try {
  const r = await fetch(url, { signal: ctl.signal });
  // ...
} finally {
  clearTimeout(timer);
}
```

This is what `fetchAnthropicStatus()` (lines 85-103) already does for the statuspage probe. Recommend either pinning `minimum_chrome_version` OR switching to the manual pattern for consistency with the rest of the file.

---

## 6. Lower-priority findings

### PD-4 — Probe filter doesn't validate `version` field (Low)

`background.js:24`: `return j && j.app === 'claude-usage' ? port : null;` — any local impersonator returning `{app: 'claude-usage'}` wins. Tightening to require `typeof j.version === 'string'` adds a trivial check that closes the impersonation-of-localhost gap.

### PD-5 — `/hello` exact-path match (Low)

`server/usage-server.py:189`: `if self.path == '/hello':` — `/hello?foo=bar` would 404. Chrome ext only sends `/hello`. Non-issue today; would matter if any consumer adds query strings (debugging, version probes).

### PD-6 — Port file not cleaned up on uninstall (Low)

`packaging/postrm` doesn't remove `~/.cache/claude-usage/port`. Stale file survives uninstall. Cosmetic; next install overwrites. Adding to postrm cleanup is one line.

### PD-7 — `claude-usage-status` doesn't show the bound port (Low)

The tool already reads `usage.json` but doesn't expose which port the server bound. Users discovering port-conflict issues will want to see "Port: 7332" near the service line. One line of code, one line of output.

### A‑2 followup — `claude-usage-status` thresholds didn't follow A‑2 (Low)

`scripts/claude-usage-status.py:42-46` still says "extension flips to STALE at 10 min" and "BROKEN at 20 min", but `extension.js` was bumped (commit `c717d45`, A-2 fix) so the stale threshold is now 15 min. Diagnostics drift from the runtime. Update the constants:

```python
if ts_min > 20:
    # ...
elif ts_min > 15:                                  # was > 10; track A-2 bump
    # ...
```

### V-2 — `VERSION = '0.11.7'` hardcoded in `usage-server.py` (Info)

`usage-server.py:28` adds a fourth file to the version-bump list (was `packaging/control`, `chrome-extension/manifest.json`, `gnome-extension/metadata.json`). `/hello`'s `version` field is informational only — no consumer validates it — so cosmetic drift if forgotten. Worth deriving at module load from `packaging/control` or `chrome-extension/manifest.json`:

```python
def _read_self_version():
    for p in (Path(__file__).resolve().parent / 'chrome-extension/manifest.json',
              Path('/usr/share/claude-usage/chrome-extension/manifest.json')):
        try:
            if p.exists():
                return json.loads(p.read_text()).get('version', '?')
        except Exception:
            pass
    return '?'
VERSION = _read_self_version()
```

`_read_expected_ext_version()` already does the equivalent for the version-handshake field — reuse the pattern.

### PD-8 — `host_permissions` bloat (Info)

10 explicit URL patterns balloon Chrome's install permission prompt. Documented tradeoff (MV3 doesn't support port wildcards). Accepted by design.

---

## 7. Items verified as non-issues

| Item | Verdict | Why |
|------|---------|-----|
| `_bind()` exits 1 on all-ports-busy | OK — systemd restart + `StartLimitBurst=5` handles, journal shows clear "failed to bind any port in N-M" message |
| Race between probe and chrome.storage write | OK — `probePorts()` runs to completion (Promise.all), then `chrome.storage.local.set` is awaited; no torn read |
| Port file at 0600 | OK — `_write_port_file` chmods before replace; only owner can read |
| Atomic port file write | OK — tmp + os.replace, same pattern as `OUTPUT` |
| /hello response Content-Length emitted | OK — explicit `send_header('Content-Length', ...)` |
| `getServerUrl({forceProbe:true})` re-probe loop | OK — only called once per POST attempt; no infinite loop |
| Extension permission prompt now reads "127.0.0.1:7331/* through 7340/*" | Cosmetic, acceptable per design |
| Cached port survives SW restart | OK — `chrome.storage.local` is the right home for this |
| Multiple Chrome profiles competing for port file | Out of scope per plan; one user one server |

---

## 8. Recommended action order

| # | Sev | Effort | Action |
|---|-----|--------|--------|
| 1 | **CRITICAL** | XS | **P-1** — rename `tab` → `createdTab` in `fetchUsage` finally (one-line). Bump 0.11.7 → 0.11.8. Block any .deb ship until landed. |
| 2 | High | S | **PD-1** — change server POST response from `b'ok'` to `{"app":"claude-usage","saved":N}`, verify in chrome ext's `postUpdate`. |
| 3 | Medium | XS | **PD-2** — add `"minimum_chrome_version": "102"` to manifest, OR rewrite the probe timeout via `AbortController`+`setTimeout` to match `fetchAnthropicStatus`'s pattern. |
| 4 | Medium | S | **PD-3** — reject non-extension origins on `/hello` GET (allow empty Origin). |
| 5 | Low | XS | **PD-4** — `probePorts` filter: also require `typeof j.version === 'string'`. |
| 6 | Low | XS | **PD-7** — show `Port: N` in `claude-usage-status` output. |
| 7 | Low | XS | **A-2 followup** — bump the threshold in `claude-usage-status.py` to match `extension.js`. |
| 8 | Low | XS | **PD-6** — add port file to .deb postrm cleanup. |
| 9 | Info | S | **V-2** — derive `VERSION` from manifest at module load. |
| 10 | Low | XS | **PD-5** — accept any path with `/hello` prefix (defensive). |

**Items 1-3 should ship together as 0.11.8** — they close the critical bug + the privacy edge case + the silent-on-old-Chrome failure. Items 4-10 are next-round polish.

---

## 9. What this pass cost vs caught

About 20 minutes of focused reading: the port-discovery diff is small (~90 lines net new), the plan was clear, the test plan in the plan file already gave most of the runtime evidence I'd need.

The plan + commit are well-structured and the implementation matches the design. The high/critical findings aren't about the design — P-1 is pre-existing code I should have caught in pass-13 (or any of the four earlier passes); PD-1 is the predictable edge case the design's "out of scope: multi-instance handling" line gestured at but didn't fully close.

**Recurring pattern across reviews:** every reviewer reads the diff hunks but not the unchanged surrounding code. P-1 is the second time this pass has caught a real bug only because I re-read the full function rather than the diff. (Pass-13's L-1 was the first — same pattern: a stable-looking function that's been wrong since a rename, missed by every subsequent diff review.) The fix is procedural: when a function is part of a diff, read the whole function, not just the changed lines.
