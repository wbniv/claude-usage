# Tab Listener Cleanup on Timeout

**Date:** 2026-05-16  
**Status:** Implemented

## Problem

`background.js::fetchUsage()` wraps the tab-load wait in a `Promise` that registers a
`chrome.tabs.onUpdated` listener. The listener removed itself on success
(`status === 'complete'`), but the 30-second timeout path called `reject()` without first
calling `removeListener`. Each timed-out fetch left an orphaned listener registered
globally for the lifetime of the service worker. Chrome recycles tab IDs, so a stale
listener could eventually fire on an unrelated tab whose ID matched a previous failed run.

## Change

**File:** `chrome-extension/background.js:27–30`

Expanded the timeout callback from a one-liner into a two-step block:

```javascript
const timeout = setTimeout(() => {
    chrome.tabs.onUpdated.removeListener(listener);
    reject(new Error('tab load timeout'));
}, 30_000);
```

The listener is now removed unconditionally — on success (existing) and on timeout (new).

## Verification

Normal operation is unchanged. To exercise the timeout path manually, temporarily reduce
`30_000` to `100`, load the extension, and trigger a fetch — the console should log
`Claude Usage fetch failed: tab load timeout` with no stale listeners remaining.
