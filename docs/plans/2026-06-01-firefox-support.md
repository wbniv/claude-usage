# 2026-06-01 — Firefox support (core-first)

## Context

Usage data is collected by a Chrome MV3 extension that scrapes the rendered DOM of
`claude.ai/settings/usage`. This plan adds **Firefox** as a second supported browser.

**Why an extension at all (and why not Chrome-only):** the meters exist only as
client-rendered React DOM behind the user's logged-in session — there is no JSON API in
use, so a plain HTTP fetch returns an empty SPA shell, and auth is the browser's cookie
jar. Non-extension alternatives (headless browser, on-disk cookie replay) are heavier and
brittle. But the browser→local coupling is already **browser-agnostic**: `background.js`
does a plain `fetch` POST to `http://127.0.0.1:7331-7340/update` and `server/usage-server.py`
is an ordinary HTTP server — **no Chrome native messaging**. The only Chrome-flavored parts
are the manifest and the `chrome.*` calls in `background.js` (the injected scraper is pure
DOM). Chromium-family browsers (Brave/Edge/Vivaldi) already work unchanged; the KDE browsers
(Falkon/Konqueror) can't run WebExtensions, so **Firefox** is the meaningful new target.

**Decisions:**
- **Distribution = AMO-signed unlisted `.xpi`** (permanent install on stock Firefox/ESR;
  Firefox refuses permanently-installed *unsigned* extensions). This change delivers the
  build + a documented `web-ext sign` path; **automating signing in CI is deferred**.
- **Scope = core-first.** Deliver: run-in-Firefox + build + server change + tests + docs.
  **Deferred to a follow-up:** `.deb` staging of a Firefox copy, `release.yml` asset +
  CI `web-ext sign`, optional `web-ext lint` task, public AMO listing.
- **Background = event page** (`background.scripts`, Firefox ≥115 ESR), not a service worker
  (FF ≥121 only). `background.js` uses only `fetch`/timers/extension APIs — no
  service-worker- or window-only globals — so an event page is a clean fit.
- **Shim = a committed 1-line `chrome-compat.js`** referenced only by the Firefox manifest
  (zero edits to `background.js`).
- **Keep the `chrome-extension/` directory name** (referenced in ~12 places; renaming is pure
  churn). Firefox consumes the shared source; only the manifest is generated.

## Implementation

Single shared source in `chrome-extension/`. Firefox ships the **same** `background.js`,
`scraper.js`, and icons; the manifest is **generated** from the Chrome one at build time, and
a 1-line shim aliases `chrome`→`browser`. The generator's `--check` is the anti-drift gate
(the FF manifest is derived from the Chrome manifest, so they can't silently diverge).

### 1. Compat shim — `chrome-extension/chrome-compat.js` (new, one line)
```js
globalThis.chrome ??= globalThis.browser;
```
`background.js` calls `chrome.*` with `await` (Chrome returns promises); in Firefox the
promise namespace is `browser.*`. Aliasing makes all ~51 call sites work with **zero edits**.
No-op on Chrome and FF ≥121. Must load **before** `background.js` (top-level
`chrome.runtime.getManifest()` at `background.js:264`) — guaranteed by listing it first in
the Firefox manifest's `background.scripts`.

### 2. Generated Firefox manifest — `scripts/gen-firefox-manifest.py` (new)
Reads `chrome-extension/manifest.json`, prints the FF manifest, with a `--check` mode
(mirrors `scripts/gen-js-defaults.py`). Exactly three transforms; everything else identical:
1. `background` → `{ "scripts": ["chrome-compat.js", "background.js"] }` (drop `service_worker`).
2. Add `"browser_specific_settings": { "gecko": { "id": "claude-usage@indri.studio",
   "strict_min_version": "115.0" } }`.
3. Keep `manifest_version`, `name`, `version`, `description`, `permissions` (all five are
   FF-supported), `host_permissions` (incl. the ten loopback ports), `action`, `icons`.
The FF manifest is **not** committed into `chrome-extension/` (that would create the divergent
copy this design avoids and break `_read_manifest_version`/`build-chrome-zip`, which glob
`manifest.json`).

### 3. Build
- **`packaging/build-firefox-zip.sh`** (new; mirrors `build-chrome-zip.sh`): `VERSION` from
  `chrome-extension/manifest.json`; stage to `mktemp -d` via rsync with the same exclusions
  (`test/`, `__pycache__`, `*.pyc`, `.DS_Store`) **plus** the Chrome `manifest.json`; write
  `gen-firefox-manifest.py` output as `manifest.json`; carry `chrome-compat.js`; `zip` to
  `dist/claude-usage-firefox-${VERSION}.zip`; echo `web-ext sign --channel=unlisted` guidance.
- **`packaging/build-chrome-zip.sh`** (edit): add `-x "chrome-compat.js"` so the Chrome
  artifact stays byte-minimal (the shim is FF-only).

### 4. Server — `server/usage-server.py` (edit; 127.0.0.1-only, so safe)
- `_cors()` (lines 499–503): wildcard branch also accepts `moz-extension://`:
  ```python
  (ALLOWED_ORIGINS is None and (origin.startswith('chrome-extension://')
                                or origin.startswith('moz-extension://')))
  ```
  Update the comment at lines 494–498 to name both schemes.
- `ALLOWED_ORIGINS`/warning (lines 54–61): mention both schemes in the warning. (Optional
  `CLAUDE_USAGE_FIREFOX_ID` pin is a follow-up — Firefox's `moz-extension://` host is a
  per-install UUID, not the gecko id, so the unset wildcard is the normal case.)

### 5. Tests (keep Chrome green, prove Firefox path)
- Existing `chrome-extension/test/*.test.js` stub `chrome` and exercise the Chrome path —
  stay **byte-untouched and green** (shared source unchanged).
- **`chrome-extension/test/firefox-compat.test.js`** (new, vm): load `chrome-compat.js` then
  `background.js` with global `chrome` **undefined** and a `browser` stub (reuse the existing
  test's stub + unhandled-rejection drain); assert no throw, `globalThis.chrome ===
  globalThis.browser`, and that `EXT_VERSION` resolved.
- **Server CORS test** under `server/tests/` (new `test_cors.py` or extend): `moz-extension://`
  allowed, `chrome-extension://` allowed, web origin rejected.
- **`gen-firefox-manifest.py --check`** wired into `task test` as the parity gate.

### 6. Taskfile + docs
- **`Taskfile.yml`** (edit): `build-firefox-zip` task (`generates:
  dist/claude-usage-firefox-{{.VERSION}}.zip`); append `gen-firefox-manifest --check` + the new
  node test to the aggregate `test`/`test-scraper` tasks.
- **`install.sh`** (edit): Firefox section after the Chrome one — primary path = install the
  signed `.xpi`; document `about:debugging` → Load Temporary Add-on as the **developer-only**
  path, explicitly noting temporary add-ons are wiped on restart. Generate a Firefox-ready copy
  (shared files + generated manifest) into `$SERVER_DIR/firefox-extension/`.
- **`MANUAL.md`** (edit): Requirements → "Google Chrome **or** Mozilla Firefox (logged in to
  Claude.ai)"; add "Load the Firefox extension" (signed `.xpi` + dev path) + a short
  "Publishing to AMO" note (`task build-firefox-zip` + `web-ext sign`).
- **`PRIVACY.md` / `SECURITY.md`** (edit): generalize "Chrome extension" → "browser extension
  (Chrome/Firefox)"; in SECURITY's drive-by-pages bullet, state `Allow-Origin` is emitted only
  for `chrome-extension://` **or** `moz-extension://`. `lint-security-doc.py` stays green
  (host_permissions are shared/unchanged).

## Deferred (follow-up, not in this change)
`.deb` staging of `firefox-extension/` + `packaging/control` Recommends (`firefox |
firefox-esr`); `release.yml` Firefox asset + automated `web-ext sign` (needs
`AMO_JWT_ISSUER`/`AMO_JWT_SECRET`); optional `web-ext lint` task; public AMO listing.

## Critical files
- `chrome-extension/background.js` — ~51 `chrome.*` sites; top-level `getManifest()` at line
  264; **stays unedited** (shim handles it).
- `chrome-extension/manifest.json` — single source for the generated FF manifest + version.
- `server/usage-server.py` — `_cors()` 494–507, `ALLOWED_ORIGINS` 54–61.
- `packaging/build-chrome-zip.sh` — template for `build-firefox-zip.sh`.
- `scripts/gen-js-defaults.py` — pattern for `gen-firefox-manifest.py --check`.

## Verification
1. `task test` — existing JS tests + new `firefox-compat.test.js` + `gen-firefox-manifest
   --check` + server pytest (incl. new CORS cases) + unchanged `lint-security-doc`/
   `lint-scraper-parity` all pass. Chrome path provably unaffected (`background.js`
   byte-identical).
2. `task build-chrome-zip` — unchanged output, now excluding `chrome-compat.js`.
3. `task build-firefox-zip` — produces the FF zip; unzip and confirm `manifest.json` has
   `background.scripts:[chrome-compat.js, background.js]`, `browser_specific_settings.gecko.id`,
   identical permissions/host_permissions; `background.js` byte-identical.
4. Manual Firefox load: `about:debugging` → Load Temporary Add-on → generated `manifest.json`;
   open `claude.ai/settings/usage`; confirm a scrape POSTs and
   `~/.cache/claude-usage/usage.json` updates; toolbar action title updates on hover (proves
   `action.setTitle` via the alias).
5. Chrome regression: reload the unpacked Chrome extension; identical behavior.
6. CORS: with the server running, a `moz-extension://` preflight gets
   `Access-Control-Allow-Origin`; a web-page origin does not.
7. Signed-xpi smoke (when AMO creds available): `web-ext sign --channel=unlisted`, install the
   `.xpi` on stock Firefox, **restart**, confirm it persists and keeps scraping.
