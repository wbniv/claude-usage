# Plan: Fix the outage status row so it's truly clickable (and ship it)

> Follow-up to `2026-05-28-clickable-status-page-on-outage.md`. That plan added the
> feature; this one fixes why it never actually behaves like a link on the running
> shell, and ships it.

## Context

User reported: the top popup row ("⚠ Anthropic reports: …") is supposed to be
clickable during an outage and open `https://status.claude.com/`, but isn't. Live
cache confirmed an active outage (`_anthropic_status = {indicator: "minor",
claude_ai_component_status: "partial_outage"}`) yet the row showed no `↗` and no
link behaviour. Two compounding causes:

1. **Deployment lag.** Installed package was **0.11.28**. The canonical-host fix
   (`status.anthropic.com` → `https://status.claude.com/`, commit `ea6ddf8`) and the
   `↗` affordance (commit `3eb8f98`) only existed in unreleased **0.11.29 source**.

2. **Latent reactivity bug (in 0.11.29 source too).** The row was built
   `new PopupMenu.PopupMenuItem('Loading…', {reactive: false})` and toggled
   `this._statusItem.reactive = wantLink` at runtime. In GNOME Shell 49,
   `PopupBaseMenuItem._init` fixes `track_hover`, the `hover→active` highlight
   binding (`bind_property('hover','active', SYNC_CREATE)` only created when
   `params.reactive && params.hover`), `_activatable`, and the
   `popup-inactive-menu-item` dimming class **at construction time**. A later
   `.reactive = true` restores none of them, so the row never highlighted on hover,
   stayed dimmed, and its click path was unreliable.

Outcome: during an Anthropic-reported outage the row hover-highlights, shows `↗`,
and a click opens `https://status.claude.com/` + closes the menu — on an installed
build.

## Implementation (done)

All in `desktop/gnome/extension.js`:

- **Construct reactive + connect once (~line 325):** drop `{reactive: false}`, add a
  single `connect('activate', …)` that opens `STATUS_URL` and closes the menu
  (mirrors "Open Usage Page" at line 333), then set `reactive = false` for the idle
  default. Construction-time wiring (binding/track_hover/_activatable, no inactive
  class) survives the later toggle.
- **Per-update gate:** replace the connect/disconnect churn with a single
  `this._statusItem.reactive = wantLink;`. The `↗` suffix (line 615–617),
  `STATUS_URL` (line 27 = `status.claude.com`), and `wantLink`/notification reuse
  are untouched.
- **Remove dead state:** `_statusItemLinked`, `_statusItemActivateId` fields and the
  `destroy()` disconnect block (handler now lives for the item's lifetime, torn down
  with the menu, same as `openItem`).

## Ship

- `task bump NEW=0.11.30` → `task test` → `task lint-gnome` → `task build` →
  `sudo dpkg -i ./dist/claude-usage_0.11.30_all.deb`.

## Critical Files

- `desktop/gnome/extension.js`
- `packaging/control`, `chrome-extension/manifest.json` (via `task bump`)

## Verification

1. `task test` — unit + parity/security lints pass.

```
task test exit code: 0
(test-scraper: all node --test suites ok; test-validate, format, parity lints green)
```
**PASS**

2. `task lint-gnome` — JS syntax + GNOME Shell API symbol verification pass.

```
lint-gnome: all API symbols verified
lint-gnome: extension.js source guards OK (DIFF-1, BASE-6a)
```
**PASS**

3. `task test-gnome UBUNTU_VERSION=26.04` — headless gnome-shell loads the extension
   without import/load errors. *(Not yet run — Docker headless smoke; optional, the
   construction change is covered by lint-gnome syntax + symbol checks.)* **PENDING**

4. `task build` + verify packaged contents:

```
Built: dist/claude-usage_0.11.30_all.deb
packaged extension.js:
  27: const STATUS_URL = 'https://status.claude.com/';
 331: this._statusItem = new PopupMenu.PopupMenuItem('Loading…');
 332: this._statusItem.connect('activate', () => { …STATUS_URL… menu.close() });
 336: this._statusItem.reactive = false;   // default
 630: this._statusItem.reactive = wantLink;
 626: (reason || …) + (wantLink ? ' ↗' : '')
  (no _statusItemLinked / _statusItemActivateId references)
```
**PASS** (package contains the fix). Install requires user sudo:
`sudo dpkg -i ./dist/claude-usage_0.11.30_all.deb` → then
`dpkg-query -W -f='${Version}' claude-usage` should read `0.11.30`. **PENDING (user)**

5. **Live (after next login — Wayland has no in-session shell reload):** with outage
   data present, the row shows `… ↗`, highlights on hover, click opens
   `https://status.claude.com/` and closes the menu. **PENDING (next login)**

6. **Negative:** `_scrape_fail_count: 3`, `_anthropic_status: {}` → row shows
   scrape-failure text, no `↗`, no highlight, not clickable. **PENDING (next login)**

7. **No warnings:** `journalctl --user -b 0 | grep -i claude-usage` clean after the
   new shell loads. **PENDING (next login)**
