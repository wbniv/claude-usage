# Dynamic port discovery for the local usage server

## Context

`server/usage-server.py:27` hardcodes `PORT = 7331`. The port isn't IANA-reserved and any "leet"-flavoured tool could grab it; if something else is bound, the server fails to start and the Chrome extension's POSTs hit `connection refused` (or worse, leak to an unrelated app that happens to be on 7331).

The goal: server picks a free port from a small range, advertises it via a port file + a `/hello` signature endpoint; Chrome extension probes the range to find it.

The GNOME extension is **out of scope** — it reads the cache file directly (`gnome-extension/extension.js:12-13, 261-282`) and doesn't care which port the server uses.

---

## Design

**Range**: `7331..7340` (10 ports).

### Server (`server/usage-server.py`)

1. Replace `PORT = 7331` (L27) with `PORT_RANGE = range(7331, 7341)`.
2. Honour `CLAUDE_USAGE_PORT` env var: if set, use that single port only (no fallback). Preserves the override already used by `packaging/test-deb-live.sh:16`.
3. New `_bind()` helper: iterate `PORT_RANGE`, return first `HTTPServer` that binds; raise with a clear message listing tried ports if all fail. Use the SO_REUSEADDR-free default so a port held by another process actually errors instead of silently sharing.
4. New `GET /hello` route in `Handler.do_GET()`: returns `{"app":"claude-usage","version":"<version>"}`. Read version once at startup from `/usr/share/claude-usage/VERSION` (if present) or fall back to a module constant kept in sync with `packaging/control`. Idempotent, no auth — the signature is the body, not access control.
5. After successful bind: write chosen port atomically (`os.replace` from a temp file) to `~/.cache/claude-usage/port` (mode 0600). Reuse the `OUTPUT.parent.mkdir(...)` pattern from L287.
6. Replace L370 `HTTPServer(...)` call with the new `_bind()` result.

### Chrome extension

1. `chrome-extension/manifest.json:7-11` — replace the single `http://127.0.0.1:7331/*` entry with 10 explicit entries `http://127.0.0.1:7331/*` through `http://127.0.0.1:7340/*`. (MV3 match patterns do not support port wildcards — explicit list is the known-good approach. Re-check current MV3 docs at implementation time; if port wildcards work now, collapse to one entry.)
2. `chrome-extension/background.js:2` — replace `const LOCAL_SERVER = 'http://127.0.0.1:7331/update'` with a small discovery module:
   - `getServerPort()`: reads cached port from `chrome.storage.local`; if missing, runs `probePorts()`.
   - `probePorts()`: `Promise.allSettled` over `[7331..7340]`, each doing `fetch('http://127.0.0.1:<p>/hello', { signal: AbortSignal.timeout(500) })`. First response with parsed `body.app === 'claude-usage'` wins. Cache as `{ port, cachedAt }`.
   - On POST failure to `/update` (network error or non-2xx), invalidate the cache and re-probe **once** before falling back to the existing `chrome.storage.local` offline buffer at L244-247.
3. The existing offline-buffer fallback stays untouched — it kicks in only after probe + post both fail.

### Other touchpoints

| File | Change |
|------|--------|
| `packaging/test-deb-live.sh:16` | Already supports `CLAUDE_USAGE_PORT`; verify it pins exactly one port with no fallback. |
| `PRIVACY.md:17,38` | Mention port range `7331-7340` instead of just `7331`. |
| `MANUAL.md` | One-line note that `~/.cache/claude-usage/port` holds the live port. |
| `packaging/control` + `chrome-extension/manifest.json` | Semver patch bump per [[project_version_locations]] — bump both together. |

### Out of scope

- GNOME extension (file-only consumer).
- Multi-instance handling — if two `claude-usage` servers somehow run, the Chrome extension takes whichever responds first to `/hello`. Documented behaviour, not engineered around.

---

## Reused existing patterns

- `Path.mkdir(parents=True, exist_ok=True)` for cache dir (`server/usage-server.py:287`).
- `CLAUDE_USAGE_PORT` env override (already wired into `packaging/test-deb-live.sh:16`).
- `chrome.storage.local` for cached state (already used for offline buffer at `background.js:244`).
- Existing 7-min alarm cycle at `INTERVAL_MINUTES = 7` — discovery piggybacks on this; no new alarm needed.
- Atomic write pattern (`tmp + os.replace`) — same as existing `OUTPUT` write.

---

## Verification

Run against the source server (`python3 server/usage-server.py`) rather than the installed `.deb` (which is still at 0.11.6 until the next release build). The systemd service was stopped for the duration of these tests and restarted afterward.

1. **Server picks 7331 when free.**
   ```bash
   systemctl --user restart claude-usage-fetch
   cat ~/.cache/claude-usage/port            # expect: 7331
   ss -tlnp | grep 127.0.0.1:7331            # expect: python3 listening
   ```
   ```
   ==> /hello
   {"app": "claude-usage", "version": "0.11.7"}
   ==> port file
   7331
   ==> port file mode
   600 /home/will/.cache/claude-usage/port
   ==> log
   Claude Usage server listening on 127.0.0.1:7331
   ```
   **PASS** — chose 7331, port file is 0600, /hello returns the signature.

2. **Server falls back when 7331 is taken.**
   ```bash
   python3 -m http.server --bind 127.0.0.1 7331 &   # squat 7331
   systemctl --user restart claude-usage-fetch
   cat ~/.cache/claude-usage/port            # expect: 7332
   curl -s http://127.0.0.1:7332/hello | jq . # expect: {"app":"claude-usage","version":"..."}
   kill %1; systemctl --user restart claude-usage-fetch
   cat ~/.cache/claude-usage/port            # expect: 7331 again
   ```
   ```
   ==> 7331 squatted by PID 1170811
   ==> port file
   7332
   ==> /hello on chosen port
   {"app": "claude-usage", "version": "0.11.7"}
   ==> listening ports
   LISTEN 127.0.0.1:7331  python3 (squatter)
   LISTEN 127.0.0.1:7332  python3 (claude-usage)
   ```
   **PASS** — fell through to 7332 cleanly; /hello on 7332 returns the signature.

3. **`CLAUDE_USAGE_PORT` pins one port, no fallback.**
   ```bash
   CLAUDE_USAGE_PORT=9999 /usr/share/claude-usage/usage-server.py &
   cat ~/.cache/claude-usage/port            # expect: 9999
   kill %1
   python3 -m http.server --bind 127.0.0.1 9999 &
   CLAUDE_USAGE_PORT=9999 /usr/share/claude-usage/usage-server.py
   # expect: exits with clear "port 9999 in use" error, no fallback
   kill %1
   ```
   ```
   ==> port file
   9999
   ==> log (positive case)
   Claude Usage server listening on 127.0.0.1:9999

   ==> 9999 squatted
   ==> exit code: 1
   ==> log (negative case)
   failed to bind any port in 9999: [Errno 98] Address already in use
   ```
   **PASS** — pin works; squat-then-pin exits 1 with clear message; no fallback to other ports.

4. **`/hello` signature; `/update` still POST-only.**
   ```bash
   curl -s http://127.0.0.1:7331/hello | jq .app        # expect: "claude-usage"
   curl -sI http://127.0.0.1:7331/update | head -1      # expect: 501 / 405
   ```
   ```
   {"app": "claude-usage", "version": "0.11.7"}
   HTTP/1.0 501 Unsupported method ('HEAD')
   ==> CORS on /hello (with extension origin)
   Access-Control-Allow-Origin: chrome-extension://abcdefg
   Access-Control-Allow-Methods: POST, OPTIONS
   ```
   **PASS** — signature correct; CORS headers emit for chrome-extension origins. (`/update` returned 501 to HEAD as expected; POST is the only implemented method.)

5. **Chrome extension discovers via probe.**
   - Force the 7331→7332 fallback per step 2.
   - In Chrome `chrome://extensions/` → claude-usage → service-worker console:
     `chrome.storage.local.get('serverPort', console.log)` → expect `{ port: 7332, cachedAt: <recent> }` after next scrape cycle.
   - `journalctl --user -u claude-usage-fetch --since '1 min ago' -f` shows `Saved N meters` from the next POST.

   **DEFERRED** — Chrome-side probe testing requires reloading the unpacked extension in Chrome and observing the service-worker console; not run in this session. The user will validate after rebuilding the .deb and reloading the Chrome extension. Server-side fallback (steps 1-4) demonstrates the contract `/hello` provides to the probe.

6. **Stale cache recovery.**
   - With Chrome ext running and a cached port, kill the server.
   - Squat the cached port, restart the server (forcing it onto a different one).
   - Trigger a scrape; confirm Chrome re-probes and the next POST succeeds.

   **DEFERRED** — same reason as step 5; verifies the `postUpdate()` re-probe path which has been read-tested but not run against a live Chrome extension this session.

7. **Regression — no GNOME-side breakage.**
   - Panel indicator updates within one cycle after fallback (GNOME extension reads `usage.json`, which is at the same path regardless of port).

   **PASS by inspection** — no edits to `gnome-extension/`; the cache file path `~/.cache/claude-usage/usage.json` is unchanged. The systemd service was restarted at the end of this session and is healthy.

8. **Tests.** Existing `chrome-extension/test/scraper.test.js` suite still passes; add a unit test that `probePorts()` resolves to the right port when only `:7332` responds with the correct `/hello` body.

   ```
   # tests 45
   # pass 45
   # fail 0
   ```
   **Partial PASS** — existing 45-test scraper suite passes. Unit test for `probePorts()` deferred: testing it cleanly requires extracting the function into an ES-module file (the current service-worker `background.js` is not `type: module` and the function depends on `fetch` + `chrome.storage.local`). Steps 1-4 above provide end-to-end coverage of the contract `probePorts()` consumes.
