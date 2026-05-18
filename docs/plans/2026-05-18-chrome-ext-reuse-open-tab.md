# 2026-05-18 — Chrome extension: reuse open user tab in `fetchUsage`

## Context

After commit `51acb16` (0.11.2) fixed the "extension reload takes minutes to update" issue by calling `fetchUsage()` directly from `onInstalled`/`onStartup`, the remaining latency in a scrape cycle is dominated by tab create + page load (5–30 s, depending on network and claude.ai's auth path).

If the user already has `claude.ai/settings/usage` open in any tab — which is common for anyone watching their meters — we can scrape that tab directly via `chrome.scripting.executeScript`. No tab create, no page load, no hydration wait beyond what the scraper itself does.

`executeScript` runs in an isolated world: the user's tab is read, not modified. They see nothing.

## Scope

Single function change in `chrome-extension/background.js` plus version bump and a one-line doc tweak. No new abstractions; users without the page open keep the existing background-tab path as the fallback.

## Files modified

### `chrome-extension/background.js` — `fetchUsage()`

1. Rename `let tab = null` → `let createdTab = null` to make the "we own this tab, clean it up in `finally`" intent explicit.
2. After the orphan-cleanup block, query `chrome.tabs.query({ url: 'https://claude.ai/settings/usage*' })`.
3. Pick the first candidate whose `status === 'complete'` AND whose URL path (query-stripped) exactly equals `USAGE_URL`. If found, use that tab's id directly.
4. Fall through to the existing `chrome.tabs.create` + load-wait path only when no reusable tab exists.
5. `finally` only closes `createdTab` — never the user's tab.

Safety guarantees baked in:
- The reused tab id is **never** written to `_scrape_tabs` storage. The orphan-cleanup at the top of the next `fetchUsage` cycle will therefore never close a user tab.
- The `tabs.query` call is wrapped in `try/catch` — a query failure falls through to the create path rather than aborting the whole scrape.
- The exact path match (`split(/[?#]/)[0] === USAGE_URL`) guards against the query pattern's wildcard matching extra path segments like `/settings/usage/something-else`.

### `chrome-extension/manifest.json` and `packaging/control`

Version bump 0.11.2 → 0.11.3. Per `feedback_semver_patch_bumps` + `project_version_locations`: both files move together with patch-level bumps.

### `MANUAL.md` and `README.md` (line 121, identical text in both)

Current:
> Data updates every 7 minutes — the Chrome extension opens `claude.ai/settings/usage` in a background tab, scrapes the meters, and writes `~/.cache/claude-usage/usage.json`. The panel indicator updates immediately when the file changes.

Proposed:
> Data updates every 7 minutes — the Chrome extension scrapes `claude.ai/settings/usage` and writes `~/.cache/claude-usage/usage.json`. If you already have that page open in a tab, it reads from there; otherwise it opens a temporary background tab. The panel indicator updates immediately when the file changes.

## Verification

1. Reload the extension at `chrome://extensions` with the Usage tab already open.
   - Expected: server `usage.json` mtime updates within ~2–3 s (no tab create + page load).
   - Watch via: `stat -c '%y' ~/.cache/claude-usage/usage.json` before/after reload.
2. Reload the extension with NO Usage tab open.
   - Expected: server `usage.json` mtime updates within ~15–30 s (background tab path, same as 0.11.2).
   - A new background tab briefly appears in the tab strip and is auto-closed after scraping.
3. Open the Usage tab and watch the tab strip during a 7-min alarm tick.
   - Expected: NO new tab appears — the existing tab is scraped silently.
   - The page does not refresh, the URL does not change, no flicker.
4. Close all Usage tabs and let the next 7-min alarm tick fire.
   - Expected: A short-lived background tab appears and disappears; data updates.
5. `node --check chrome-extension/background.js` returns clean.
6. Run the scraper test suite to confirm no regression in extracted data.

## Out of scope

- Reusing a tab that is still loading (`status: 'loading'`) — adds complexity (wait + race against navigation) for marginal benefit; falling through to a background tab is simpler.
- Bringing the reused tab to the foreground or refreshing it — defeats the "invisible to the user" property.
- Updating line 126 of the docs ("Open `claude.ai/settings/usage` in any normal tab…") — that paragraph is about *manual* triggering via `tabs.onUpdated`, which is unchanged.
