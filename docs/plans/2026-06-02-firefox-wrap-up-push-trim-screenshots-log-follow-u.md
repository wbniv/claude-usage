# Plan: Firefox wrap-up — push, trim screenshots, log follow-up

## Context

Firefox support is implemented, committed, and **live-validated** (real Max-plan
meters scraped + POSTed via the extension; the `chrome→browser` shim bug and the
Firefox-CORS-on-localhost bug were both found live and fixed). The doc-fix commit
`2d47850` (tested MANUAL walkthrough + corrected `_cors` comment + 4 screenshots)
is **local-only**. Live use also surfaced one rough edge: the Firefox
non-persistent **event-page background doesn't reliably wake for the periodic
7-min alarm** (cache went ~10 min stale vs the live page; a forced toolbar scrape
works but lags). User asked to "do all 3 now."

## Actions

### 1. Trim screenshots (amend `2d47850`, don't add bloat to history)
Only `docs/screenshots/firefox-install/01-about-debugging-loaded.png` is
referenced (MANUAL.md). The other three (`02-about-addons-list.png`,
`03-extension-details-tab.png`, `04-permissions-and-data-tab.png`) are ~1.15 MB of
unreferenced 4K PNGs. Since `2d47850` is unpushed, **amend** it to drop them so the
bloat never enters pushed history:
- `git rm docs/screenshots/firefox-install/0{2,3,4}-*.png`
- `git commit --amend --no-edit`  (keeps MANUAL.md, the `_cors` comment fix, and `01`)

### 2. Log the periodic-refresh limitation in `TODO.md`
Add one bullet under `## Deferred` (match existing dated-bullet format):
> **2026-06-02** **FF-1** (Firefox): the FF port's non-persistent event-page
> background (`background.scripts`) doesn't reliably wake for the 7-min `alarms`
> scrape — live test left the cache ~10 min stale vs the page; a forced toolbar
> scrape refreshes but lags (event page unloads during the up-to-30s
> hydration-wait). Fix to try: emit `background.service_worker` instead of
> `scripts` for Firefox in `scripts/gen-firefox-manifest.py` (FF≥121; bump
> `strict_min_version` to `121`) so it behaves like Chrome's working MV3 worker,
> then re-test the auto/periodic refresh. The chrome→browser shim
> (`chrome-extension/chrome-compat.js`) already covers both background shapes.

Commit: `docs(todo): track Firefox periodic-refresh limitation (FF-1)`

### 3. Push
`git push origin main` — publishes the amended `2d47850` + the TODO commit.

## Critical files
- `docs/screenshots/firefox-install/` (remove 02/03/04, keep 01)
- `TODO.md` (append one Deferred bullet)
- (reference for the logged fix) `scripts/gen-firefox-manifest.py` — currently emits
  `background.scripts`; the follow-up would switch it to `background.service_worker`.

## Out of scope (logged, not done now)
Implementing the `service_worker` switch + re-test — that's the FF-1 follow-up.

## Verification
- `git show --stat HEAD~1` (amended doc commit) lists only `01-…png` + MANUAL.md + usage-server.py.
- `git log --oneline -2` shows the TODO commit on top.
- `git status` clean; `git push` reports `… main -> main`, branch in sync with origin.
- `TODO.md` Deferred section contains the FF-1 bullet.
