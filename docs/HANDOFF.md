# Handoff — Firefox support + usage-API rewrite (2026-06-02)

Picked-up context for the next agent/session. Read this, then
`docs/plans/2026-06-02-usage-api-fetch.md`, then `TODO.md` (`FF-1`).

## TL;DR — where things stand

- **`main` is the working branch**, in sync with `origin/main`. Everything below is committed + pushed.
- **Firefox support: SHIPPED and live-validated.** The extension loads, scrapes real
  meters, and POSTs to the local server on Firefox 151 — confirmed end-to-end with
  real Max-plan data. Chrome is unaffected.
- **One open limitation — `FF-1`:** on Firefox the *automatic/periodic* refresh is
  unreliable (the 7-min alarm and tab-reload don't keep the cache fresh because the
  non-persistent event page unloads during the up-to-30 s DOM scrape). **On-demand
  refresh works** (toolbar icon). Chrome is fine.
- **The proper `FF-1` fix is in progress: replace DOM-scraping with the usage JSON
  API.** Phase 1 (the data mapping) is done + tested. The rest is gated on a live
  de-risk that **needs a browser logged into claude.ai** (not available on the dev
  machine this session).

## What shipped this session (all on `main`)

1. Retired the stale local `kde-plasma-support` branch → archived as tag
   `archive/kde-plasma-support` (superseded; the KDE work was redone on `main`).
2. `test(kde)`: gschema↔`main.xml` **range-parity** check in `lint-kde-parity.py`.
3. **Firefox support** over the shared `chrome-extension/` source:
   - Generated FF manifest (`scripts/gen-firefox-manifest.py`) + 1-line
     `chrome-extension/chrome-compat.js` shim; `packaging/build-firefox-zip.sh`;
     `lint-firefox-manifest`; docs; `firefox-compat.test.js`.
   - Server CORS fix in `server/usage-server.py::_cors` (accept `moz-extension://`).
   - **Two bugs found by live testing** (unit tests structurally couldn't):
     (a) the shim was `chrome ??= browser` which **no-ops** because Firefox defines
     *both* `chrome` (callback) and `browser` (promise) — fixed to unconditional
     `chrome = browser`; (b) **Firefox enforces CORS on the extension's `127.0.0.1`
     fetch even with `host_permissions`** (Chrome doesn't) → the server must send
     `Access-Control-Allow-Origin` for `moz-extension://`.
4. **usage-API groundwork** (`ce93dc3`): `chrome-extension/usage-api.js` +
   `test/usage-api.test.js` + `docs/plans/2026-06-02-usage-api-fetch.md`.

## Hard-won facts — DO NOT re-derive these

- **Firefox 151 `background.service_worker` is DISABLED** (behind the
  `extensions.backgroundServiceWorker.enabled` pref, off by default) → a SW build
  refuses to install. **The event page (`background.scripts`) is the only option.**
- **Firefox MV3 auto-grants `host_permissions`** on load — no manual grant step.
- **Firefox enforces CORS on the extension→`127.0.0.1` fetch** even with
  host_permissions (Chrome bypasses it). The server's `_cors` now covers
  `moz-extension://`. *(A fresh install gets this from the committed code — see
  "Setting up a fresh machine".)*
- **`web-ext` cannot drive the snap Firefox** (the RDP debugger handshake fails) —
  use the manual `about:debugging` → "Load Temporary Add-on" for live testing.
- **`FF-1` root cause:** the long DOM scrape (open tab → wait ≤30 s for React
  hydration → read DOM) outlives/kills the event page. `alarms` themselves work in
  Firefox for *short* tasks (the popular `lugia19` add-on uses them) — so the fix is
  to make the data fetch fast and tabless.

## The usage API (the FF-1 fix) — everything you need

```
GET https://claude.ai/api/organizations/{org_id}/usage   → application/json, ~565 B, ~400 ms
```
- **Auth:** the session cookie (sent automatically with `credentials:'include'`) +
  header `anthropic-client-platform: web_claude_ai` (and `anthropic-client-version`).
- **`org_id`** is in the `lastActiveOrg` cookie (or fetch it — see Phase 0).
- **Response → meters mapping** (already implemented + tested in `usage-api.js`):
  | API bucket | `utilization` | → meter `label` |
  |---|---|---|
  | `five_hour` | session % | **"Current session"** |
  | `seven_day` | all-models % | **"All models"** |
  | `seven_day_opus` (if non-null) | opus % | **"Opus"** |
  | `seven_day_sonnet` (if non-null) | sonnet % | **"Sonnet only"** |
  | `extra_usage` (if `is_enabled`) | credits | **"Extra usage"** |
  Each bucket has `resets_at` (ISO) → `reset_minutes` + a "Resets …" string.
- **Why this works:** the mapping emits the *exact same* `meters[]` shape the server
  and every desktop consumer already key off (by label substring) — so the server,
  GNOME extension, KDE plasmoid, tooltip, and icon generator need **no changes**.

## Pick up here — remaining phases (see the plan doc for detail)

**Phase 0 — de-risk (NEEDS a browser logged into claude.ai):**
- Confirm a cross-origin fetch from the extension *background* returns the usage
  JSON (Approach A, the tabless fix). Probe in `about:debugging` → Claude Usage
  Tracker → Inspect → Console:
  `fetch('https://claude.ai/api/organizations/<org>/usage',{credentials:'include',headers:{'anthropic-client-platform':'web_claude_ai'}}).then(r=>r.json()).then(console.log).catch(console.error)`
  - 200 + JSON → **Approach A**. CORS/Cloudflare block → **Approach B** (keep opening
    a tab but inject a *same-origin* `fetch('/api/…/usage')` instead of scraping DOM).
- Settle **org-id discovery**: `lastActiveOrg` cookie (needs the `cookies` permission)
  vs an API call (`/api/bootstrap` or `/api/organizations`). Cookie is most reliable.

**Phase 2 — wire** `fetchUsageApi()` into `chrome-extension/background.js`
(replace `scrapeAndPost` in `fetchUsage`; reuse `mapUsageResponse`; keep the DOM
scrape as **fallback**). Load `usage-api.js` at runtime: FF
`background.scripts:[chrome-compat.js, usage-api.js, background.js]` (update
`gen-firefox-manifest.py`); Chrome SW `importScripts('usage-api.js')` at the top of
`background.js`. Ensure `build-chrome-zip.sh` ships `usage-api.js`. Rebuild
`dist/firefox-unpacked`.

**Phase 3 — validate FF-1** live: hands-off test — load, leave idle, confirm the
7-min alarm refreshes the cache on its own (no clicks, no Inspect window). Confirm
Chrome unchanged.

**Phase 4 — cleanup** (separate commit): remove `chrome-extension/scraper.js` +
`test/scraper.test.js`; drop `check_scraper_parity` + `check_anchor_strings` from
`scripts/lint-scraper-parity.py` (KEEP `check_pacing_parity` + `check_pair_inventory`,
they're data-source-agnostic). `lint-kde-parity` field allowlist is unaffected.

## Setting up a fresh machine

The next machine starts clean — **none of the original dev box's local state
transfers** (it isn't in git). To reach a testable setup:

- **Server:** run `install.sh` (or install the `.deb`). The committed
  `server/usage-server.py` already contains the `moz-extension://` CORS fix, so a
  fresh install serves Firefox correctly out of the box — no hand-patching needed.
  *(Context only: the original dev box had its pre-existing `0.11.22` server
  hand-patched mid-session to unblock testing. That's local, doesn't carry over,
  and is unnecessary on a clean install.)*
- **Firefox build to load:** `task build-firefox-zip`, unzip it, then load via
  `about:debugging` → "Load Temporary Add-on" → its `manifest.json`. (`dist/` is
  gitignored, so the build isn't in the repo.) `install.sh` also stages a ready
  copy under `$XDG_DATA_HOME/claude-usage/firefox-extension/`.
- **A claude.ai login is required** for the Phase 0 de-risk, and `org_id` is
  per-account — read it from the `lastActiveOrg` cookie; don't reuse a hardcoded one.
- **Retired KDE branch:** tag `archive/kde-plasma-support` (on `origin`) —
  `git switch -c restore archive/kde-plasma-support` to recover it.

## Verify
- `task test` — all green; `lint-qml` needs a networked container (passes in CI,
  may fail offline). The new mapping: `node --test chrome-extension/test/usage-api.test.js`.
- Build sanity: `task build-firefox-zip` / `task build-chrome-zip`.

## Gotchas for the operator
- This repo enforces a dated `docs/plans/YYYY-MM-DD-*.md` before code (a hook nags).
- Don't `pkill -f <pattern-in-your-own-command>` — it self-kills (happened twice this session).
- The previous operator couldn't cleanly copy multi-char commands out of chat
  (terminal padding pulled in whitespace); if you see the same, hand commands via a
  file or clipboard, or keep them short.
