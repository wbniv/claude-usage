# Plan: Clickable Status Page on Outage

## Context

When Claude.ai has an outage, the GNOME extension fires a `Main.notify()` toast and marks the panel red — but neither surface lets the user navigate to the status page. This plan adds `https://status.claude.ai/` as a one-click action in two places: the notification toast itself (via `MessageTray.Notification.addAction()`) and the panel popup's status line (conditionally, only when Anthropic itself reports a problem).

---

## Implementation

### 1 — Add imports and constant

In `gnome-extension/extension.js`, alongside existing shell UI imports (~line 7–9):

```javascript
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
```

Near the existing `USAGE_URL` constant (~line 21):

```javascript
const STATUS_URL = 'https://status.claude.ai/';
```

### 2 — Replace broken-tier `Main.notify()` with actionable notification

**Location:** the `Main.notify(...)` call inside the `tier === 'broken'` transition block (~line 570).

Replace:
```javascript
Main.notify('Claude Usage', reason || `Status: ${tier}`);
```

With:
```javascript
const _src = MessageTray.getSystemSource();
const _notif = new MessageTray.Notification({
    source: _src,
    title: 'Claude Usage',
    body: reason || 'Service disruption detected',
    isTransient: true,
});
_notif.addAction('View Status Page', () => {
    Gio.AppInfo.launch_default_for_uri(STATUS_URL, null);
});
_src.addNotification(_notif);
```

Use `getSystemSource()` (shared system source, no private Source to manage/destroy). Use `isTransient: true` so the toast doesn't linger in the notification list. No manual cleanup needed — transient notifications auto-destroy.

**Do not** change the critical-pacing notification (~line 502). That's about the user's own usage rate, not an Anthropic outage.

### 3 — Make `_statusItem` conditionally clickable

**In `_init()`** (~line 312), add two instance variables:
```javascript
this._statusItemLinked = false;
this._statusItemActivateId = null;
```

**After the `_statusItem.label.set_text(...)` call** (~line 555), add reactive toggling:

```javascript
// Only link to status page when Anthropic itself reports a problem.
// Scrape-failure and age-timeout broken cases point to local issues.
const wantLink = tier === 'broken' &&
    (astat.indicator && astat.indicator !== 'none' ||
     astat.claude_ai_component_status && astat.claude_ai_component_status !== 'operational');
if (wantLink !== this._statusItemLinked) {
    this._statusItem.reactive = wantLink;
    if (wantLink) {
        this._statusItemActivateId = this._statusItem.connect('activate', () => {
            Gio.AppInfo.launch_default_for_uri(STATUS_URL, null);
            this.menu.close();
        });
    } else if (this._statusItemActivateId) {
        this._statusItem.disconnect(this._statusItemActivateId);
        this._statusItemActivateId = null;
    }
    this._statusItemLinked = wantLink;
}
```

The `_statusItem` text update runs before the `_menuFp` fingerprint guard, so this code runs on every `_updateDisplay()` call and is idempotent.

### 4 — Cleanup in `destroy()`

In the `destroy()` method (~line 732), before `super.destroy()`:

```javascript
if (this._statusItemActivateId) {
    this._statusItem.disconnect(this._statusItemActivateId);
    this._statusItemActivateId = null;
}
```

### 5 — KDE Plasmoid

No changes needed. The plasmoid has no notification infrastructure; this is GNOME-only.

---

## Critical Files

- `gnome-extension/extension.js` — all changes

---

## Verification

1. Run `task test` — should pass lint/parity checks with no syntax errors.
2. Run `task test-gnome` (Ubuntu container smoke test) — extension loads without import errors.
3. **Live session — notification toast:** Set `_lastNotifyTs = 0` and `_lastTier = 'normal'`, inject cache with `_anthropic_status: {indicator: 'minor', description: 'API degraded'}`. Broken-tier toast appears with "View Status Page" button; clicking opens `https://status.claude.ai/`.
4. **Live session — panel popup link:** With same injected cache, open panel popup. `_statusItem` has hover highlight and clicking it opens the status URL and closes the menu.
5. **Non-Anthropic broken tier:** Inject `_scrape_fail_count: 3`, `_anthropic_status: {}`. `_statusItem` shows scrape-failure text with `reactive: false` (no hover, not clickable).
6. **Stale tier:** Inject age 15–20 min. No notification fires; `_statusItem` not reactive.
7. **Destroy lifecycle:** Disable/re-enable extension; no GLib signal-disconnect warnings in `journalctl --user`.
