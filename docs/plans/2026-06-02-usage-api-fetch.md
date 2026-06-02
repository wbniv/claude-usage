# 2026-06-02 — Replace DOM-scrape with the claude.ai usage API (fixes FF-1)

## Context

The extension currently reads usage by **opening a background tab on
`claude.ai/settings/usage`, waiting up to 30s for React to hydrate, then parsing
`document.body.innerText`** (`chrome-extension/background.js:363-476`,
`scraper.js`). That long, tab-bound operation is exactly what unloads Firefox's
non-persistent event page mid-scrape → **FF-1** (the 7-min alarm and page-visit
refresh don't keep the cache fresh; only a forced toolbar click works).

Network inspection found the SPA's own data source — a single authenticated JSON
call the page makes:

```
GET https://claude.ai/api/organizations/{org_id}/usage   → application/json, ~565 B, ~400 ms
```
Auth = the session **cookie** (sent automatically with `credentials: 'include'`)
plus header `anthropic-client-platform: web_claude_ai` (and `anthropic-client-version`).
Response (real sample):
```json
{"five_hour":{"utilization":50.0,"resets_at":"2026-06-02T11:50:00+00:00"},
 "seven_day":{"utilization":15.0,"resets_at":"2026-06-03T15:59:59+00:00"},
 "seven_day_sonnet":{"utilization":0.0,"resets_at":"2026-06-03T16:00:00+00:00"},
 "seven_day_opus":null,"seven_day_oauth_apps":null,…,
 "extra_usage":{"is_enabled":false,"monthly_limit":null,"used_credits":null,"utilization":null}}
```

A direct `fetch()` of this is ~400 ms with **no tab and no hydration wait** — it
finishes inside Firefox's event-page wake window, **closing FF-1**, and removes a
large amount of fragile text-parsing on *both* browsers.

> **Security:** the capture used to find this exposed a live `sessionKey`. Rotate
> it (log out + back in) before/while doing the live steps below.

## Design — minimal blast radius

**Keep `usage.json` byte-compatible.** The server (`usage-server.py` validation +
`_period_lengths` accumulation) and every consumer (GNOME `extension.js`, KDE QML,
`tooltip.py`, `generate-icon.py`) key off a `meters[]` array of
`{pct, label, reset, reset_minutes, …}` and **match meters by label substring**.
So the new path must emit the *same* `meters[]` shape with the *same* label
strings — then nothing downstream changes.

### Field mapping (API → existing `meters[]`)
| API field | → `label` (must contain) | pct | reset_minutes / reset |
|---|---|---|---|
| `five_hour` | **"Current session"** (`session`/`current`) | `round(utilization)` | from `resets_at` |
| `seven_day` | **"All models"** (`all`) | `round(utilization)` | from `resets_at` |
| `seven_day_opus` (if non-null) | **"Opus"** | … | … |
| `seven_day_sonnet` (if non-null) | **"Sonnet only"** (`sonnet`) | … | … |
| `extra_usage` (if `is_enabled`) | **"Extra usage"** | `round(utilization||0)` | spent/balance from `used_credits`/`monthly_limit` |

- `reset_minutes = clamp(round((Date.parse(resets_at) - now)/60000), 0, 44640)`.
  The server accumulates `max(reset_minutes)` per label into `_period_lengths`
  exactly as today (five_hour→~300, seven_day→~10080), so **pacing is unchanged**.
- `reset` string replicates the scraper's formats so `tooltip.py`/`extension.js`
  display identically: `"Resets in H hr M min"` / `"Resets in M min"` for <24 h,
  else `"Resets {Day} {h}:{mm} {AM/PM}"` in local time (verified: `seven_day`
  `2026-06-03T15:59:59Z` → "Resets Wed 9:00 AM", matching the live page).
- The 0%-Sonnet hiding, "all"-fallback selection, and label-keyed `_period_lengths`
  all keep working because the labels are unchanged.

### Fetch path (the FF-1 crux) — Approach A, B fallback
- **A (target): background fetch, no tab.** `fetch(USAGE_API, {credentials:'include',
  headers:{'anthropic-client-platform':'web_claude_ai','anthropic-client-version':'1.0.0'}})`
  straight from the SW/event page (claude.ai is already in `host_permissions`).
  Fast, tabless → fixes FF-1. **Risk: cross-origin from the extension origin** —
  Cloudflare / the API may reject non-`same-origin` requests. **Must de-risk live.**
- **B (fallback): injected same-origin fetch.** If A is blocked, keep opening a
  tab but inject `fetch('/api/organizations/{org}/usage')` instead of scraping the
  DOM — no hydration wait (read the API the instant the page context exists).
  Better than today, weaker FF-1 win.

### org_id + plan label
- **org_id**: present in the `lastActiveOrg` cookie, but reading cookies needs a
  new permission. Prefer fetching it without that — `GET /api/bootstrap` or
  `/api/organizations` (with credentials) returns the org(s); pick the active one.
  *(Confirm the exact org-discovery endpoint during de-risk.)*
- **plan label** ("Max (5x)") is **not** in `/usage` and is **cosmetic**
  (`derive_tier` uses `_anthropic_status`+`_scrape_fail_count`, not `plan`). Defer:
  fetch from a bootstrap/subscription endpoint later, or omit initially.

## Scope (from the dependency audit)
**New / changed**
- `chrome-extension/usage-api.js` (NEW) — pure `mapUsageResponse(api, nowMs)` →
  `meters[]` + `formatReset()`. ES-module for tests; loaded into the runtime
  alongside `background.js` (FF `background.scripts:[…, usage-api.js, background.js]`;
  Chrome SW `importScripts('usage-api.js')`).
- `chrome-extension/test/usage-api.test.js` (NEW) — maps the real sample → expected
  meters; reset-string formats; edge cases (null buckets, extra_usage).
- `chrome-extension/background.js` — replace `scrapeAndPost`/tab path in `fetchUsage`
  with `fetchUsageApi()` (org_id + GET /usage + `mapUsageResponse`), keep the same
  `postUpdate` payload (`meters`, `plan?`, `_timestamp`, `_scrape_fail_count`,
  `_anthropic_status`, `_ext_version`). Keep DOM-scrape as a **fallback** initially.
- `scripts/gen-firefox-manifest.py` — add `usage-api.js` to the FF `background.scripts`.
- `packaging/build-chrome-zip.sh` — ensure `usage-api.js` ships (it's not excluded).

**Obsolete after the API is primary & stable (Phase 3 cleanup, not now)**
- `chrome-extension/scraper.js` + `test/scraper.test.js` (DOM text parsing).
- `lint-scraper-parity.py` sub-checks `check_scraper_parity` + `check_anchor_strings`
  (regex/anchor parity between scraper.js and the inline copy). **Keep**
  `check_pacing_parity` + `check_pair_inventory` (data-source-agnostic).

**Unaffected** (no changes): `usage-server.py` validation/merge, `tooltip.py`,
`generate-icon.py`, all desktop consumers, `lint-kde-parity` field allowlist
(same meter fields), `lint-pacing-parity`, `lint-gnome`, `lint-qml`, the moz CORS
fix. `background-load`/`background-runtime` tests survive (update the
`executeScript`/fetch mock shape only).

## Phases
0. **De-risk (live):** confirm Approach A works — a fetch from the extension
   background to `/api/organizations/{org}/usage` returns 200 JSON. Settle the
   org-discovery endpoint. If A fails → switch to B.
1. **Mapping module + tests** (offline, no browser) — `usage-api.js` validated
   against the real sample. *(Doing now.)*
2. **Wire** `fetchUsageApi()` into `background.js` (primary = API, fallback =
   scrape), update manifest/build, rebuild `firefox-unpacked`.
3. **Live validate FF-1** — load, leave idle, confirm the 7-min alarm refreshes
   the cache on its own (the hands-off test). Confirm Chrome unaffected.
4. **Cleanup** (separate commit) — remove the DOM scraper + obsolete lint checks +
   scraper.test.js; drop `scraper.js` from the package.

## Verification
- `task test` green throughout (new `usage-api.test.js`; scraper tests stay until
  Phase 4).
- Phase 0: extension-console fetch returns the JSON (200) cross-origin.
- Phase 3 (the real proof): hands-off watcher sees the cache refresh on the 7-min
  alarm with no clicks and no Inspect window — i.e., FF-1 closed.
- Chrome: reload unpacked, confirm identical `meters[]` and behavior.
- Spot-check the mapped values equal the live page (session/all/sonnet %, resets).

## Critical files
- `chrome-extension/background.js` — `fetchUsage`/`scrapeAndPost`/`postUpdate` (replace acquisition).
- `chrome-extension/usage-api.js` (new) + `test/usage-api.test.js` (new).
- `server/usage-server.py` — **no change** (consumes the same `meters[]`).
- `scripts/gen-firefox-manifest.py`, `packaging/build-chrome-zip.sh` — ship `usage-api.js`.
