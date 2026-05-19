# Fix Pass-15 Low + Info Findings → 0.11.13

## Context

Pass-15 code review ([docs/investigations/2026-05-19-code-review-pass15.md](../investigations/2026-05-19-code-review-pass15.md)) listed 4 Low (HM‑2, SC‑2, I‑2, plus CI‑4 promoted from Info to Low on revisit) and 4 Info (SC‑3, PR‑1, TF‑1, L‑3) findings.

This plan ships **six of the seven** as 0.11.13. TF‑1 (`.desktop` Icon= per-second-precision path) is deliberately skipped per the review's own recommendation: *"Don't do solo; bundle with a future icon-rendering refactor."*

The 0.11.12 batch (`ef3a852`) closed the High and Medium findings. With the deploy pipeline now actually deploying (U‑1), shipping these polish items is meaningfully different from before — fixes will visibly land on user machines on the next `apt upgrade` instead of being silently stranded.

---

## Files modified

### 1. `server/usage-server.py` — HM‑2

**Line 231** raises `ValueError` from `int(Content-Length)` for non-numeric headers, dumping a Python traceback to the journal. Wrap and return 400, matching the pattern already used for `json.loads` at line 245:

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

### 2. `chrome-extension/background.js` — SC‑2

**Line 180** uses `document.body.textContent`; the actual `doScrape` reads `document.body.innerText`. Match the predicate to the consumer:

```js
function isHydrated() {
  return /\d+%\s*used/i.test(document.body.innerText);
}
```

### 3. `chrome-extension/background.js` — PR‑1

**Line 77** excludes 5xx-with-signature from the first-attempt success path. Currently unreachable (server's only 5xx path is the `except Exception` catch-all which returns 400) but structurally wrong. Extend the range to cover 5xx:

```js
if (r.status < 600 && isOurs(r)) return r;
```

Removes the 4xx-only branch in favor of "any well-formed response from our server" — defense in depth.

### 4. `install.sh` & `packaging/claude-usage-setup` — I‑2

Both branch on `gnome-extensions enable`'s exit code, but on Wayland that command returns 0 even though the extension code only loads after logout. Always print the "log out" hint so the success message is accurate on both X11 and Wayland.

`install.sh:150-153`:
```bash
gnome-extensions enable claude-usage@indri.studio 2>/dev/null \
    && echo "  ✓ GNOME extension enabled (log out and back in if the panel indicator isn't visible)" \
    || echo "  ℹ  GNOME extension registered — log out and back in to activate it"
```

`claude-usage-setup:37-51`:
```bash
if gnome-extensions enable "$UUID" 2>/dev/null; then
    echo "  ✓ GNOME extension enabled (log out and back in if the panel indicator isn't visible)"
else
    # … existing fallback unchanged …
fi
```

### 5. `chrome-extension/background.js` — L‑3

**Line 13**: bump `PORT_CACHE_TTL_MS` from 1 hour to 24 hours. The POST-path `isOurs` check already catches port-move scenarios within one scrape cycle; the TTL serves as long-tail safety net only.

```js
const PORT_CACHE_TTL_MS = 24 * 60 * 60 * 1000;
```

### 6. `scripts/lint-scraper-parity.py` (NEW) + `Taskfile.yml` + `.github/workflows/release.yml` — SC‑3

Add a CI lint that fails when `scraper.js::doScrape` body diverges from `background.js`'s inlined func body. Extract function bodies via regex, normalize whitespace, compare.

The script is ~50 lines and runs in CI as part of `task test`. The mitigation per pass-15: *"the risk is 'future change misses one side' — preventable with attention, not architecturally inevitable."*

Wire into:
- `Taskfile.yml`: new `lint-scraper-parity` task.
- The aggregate `test` task gains it as a dependency.
- `release.yml`: covered transitively via `task test`.

### 7. `.github/workflows/release.yml` — CI‑4 (revisited Low)

Docker cache keys at lines 44 and 64 hash only `packaging/control` + `Dockerfile`. Add a weekly calendar token so the image rebuilds at least every 7 days even when those files don't change, catching upstream Ubuntu drift:

```yaml
key: deb-test-image-2404-${{ hashFiles('packaging/control', 'packaging/test-deb.Dockerfile') }}-week-${{ steps.week.outputs.iso }}
```

with a preceding step:
```yaml
- id: week
  run: echo "iso=$(date -u +%G-W%V)" >> "$GITHUB_OUTPUT"
```

### 8. Version bumps — 0.11.12 → 0.11.13

- `packaging/control` line 2: `Version: 0.11.12` → `Version: 0.11.13`
- `chrome-extension/manifest.json` line 4: `"version": "0.11.12"` → `"version": "0.11.13"`
- `server/usage-server.py`: derives via V‑2 — no edit
- `gnome-extension/metadata.json`: auto-bumped by `task release` on tag push

---

## Out of scope

- **TF‑1** (`.desktop` Icon= per-second-precision path) — pass-15: *"Don't do solo; bundle with a future icon-rendering refactor."* Carry on the radar in TODO.md.
- **Defense-in-depth follow-up** from pass-15 §2 (have `claude-usage-status` warn when `/hello`'s version differs from on-disk manifest) — useful but separate concern from the Low/Info batch; defer.

---

## Verification

1. **Parse checks:**
   ```
   python3 -m py_compile server/usage-server.py scripts/lint-scraper-parity.py
   node --check chrome-extension/background.js
   bash -n install.sh packaging/claude-usage-setup
   ```

2. **Unit tests pass:** `task test` — covers test-scraper, test-validate, plus the new lint-scraper-parity.

3. **HM‑2 live check** (raw socket, since curl computes Content-Length itself):
   ```
   python3 -c "
   import socket
   PORT = open('/home/will/.cache/claude-usage/port').read().strip()
   s = socket.socket(); s.connect(('127.0.0.1', int(PORT)))
   s.send(b'POST /update HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: garbage\r\n\r\n{}')
   print(s.recv(4096).decode())
   "
   # expect: HTTP/1.0 400 with body "bad request: invalid Content-Length"
   # journal should NOT contain a Python traceback
   ```

4. **PR‑1 / SC‑2 / L‑3 live checks**: these run in the Chrome extension. After reload, no observable behavioral change unless the corresponding edge case fires. Code-review parity check sufficient.

5. **I‑2 visual check**: re-run `install.sh` or trigger postinst — success branch now mentions the log-out hint.

6. **SC‑3 lint check**: deliberately introduce a one-line diff between scraper.js and background.js's inline func, run `task lint-scraper-parity`, expect non-zero exit. Revert.

7. **Version sync:**
   ```
   grep '"version"' chrome-extension/manifest.json   # 0.11.13
   grep '^Version:' packaging/control                # 0.11.13
   ```

---

## Critical files at a glance

| File | Finding | Change |
|------|---------|--------|
| `server/usage-server.py:231` | HM‑2 | try/except around `int(Content-Length)` |
| `chrome-extension/background.js:13` | L‑3 | `PORT_CACHE_TTL_MS` 1h → 24h |
| `chrome-extension/background.js:77` | PR‑1 | `r.status < 600 && isOurs(r)` |
| `chrome-extension/background.js:180` | SC‑2 | `textContent` → `innerText` |
| `install.sh:150-153` | I‑2 | always-print log-out hint |
| `packaging/claude-usage-setup:37-51` | I‑2 | same |
| `scripts/lint-scraper-parity.py` (NEW) | SC‑3 | function-body diff |
| `Taskfile.yml` | SC‑3 | new task + wired into `test` |
| `.github/workflows/release.yml` | CI‑4 | weekly cache-bust token |
| `packaging/control` | bump | 0.11.13 |
| `chrome-extension/manifest.json` | bump | 0.11.13 |
