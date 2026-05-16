# Pass-4 Polish: Stale-Notification Hint + MANUAL.md Uninstall Note

**Date:** 2026-05-16
**Status:** Implemented

## Context

Two open suggestions from pass-4 code review (`docs/investigations/2026-05-16-code-review-pass4.md` §Architecture Observations) — both polish, not bugs. They were left out of the `e704f14` pass-4 fix batch because they're UX/docs rather than correctness.

1. **Stale-data notification is opaque about *which* failure mode it's signalling.** The single toast says "No update in N min — click the Chrome extension icon to refresh", but that advice only helps for one of the three failure modes (Chrome closed). For "extension crashed" or "server down" the click does nothing and the user has no next step. The diagnostic script `claude-usage-status` already distinguishes all three, but users only discover it via MANUAL.md.

2. **`MANUAL.md` `.deb` uninstall section is misleading.** It tells users `rm -rf ~/.config/claude-usage` for "optional user config" — but that path is never written by any script in the codebase. Worse, it gives the false impression that's the only per-user leftover, when `claude-usage-setup` actually drops a `.desktop` launcher in `~/.local/share/applications/` (visible as a broken entry in Activities search after `apt remove`) and the server accumulates a runtime cache at `~/.cache/claude-usage/`.

The intended outcome: users hit by a stale-data alert know the one command to run; users uninstalling the `.deb` get accurate cleanup steps.

## Change 1 — `gnome-extension/extension.js:215-217`

Current:

```javascript
if (stale && !this._wasStale)
    Main.notify('Claude Usage', `No update in ${age} min — click the Chrome extension icon to refresh`);
```

Replace the body string so it covers the cheap fix first, then points at the diagnostic for the other two failure modes:

```javascript
if (stale && !this._wasStale)
    Main.notify('Claude Usage',
        `No update in ${age} min. Open Chrome and click the extension icon, or run claude-usage-status to diagnose.`);
```

Rationale:
- "Open Chrome and click the extension icon" handles the most common case (Chrome was closed for a while).
- "run claude-usage-status to diagnose" is the catch-all for the other two failure modes the reviewer named — the script already prints which of the three is at fault.
- One-shot edge (`!this._wasStale`) and threshold are untouched.

## Change 2 — `MANUAL.md` uninstall section (lines 241–256)

Current text:

````markdown
**.deb install:**

```bash
sudo apt remove claude-usage
rm -rf ~/.config/claude-usage   # optional: remove user config
```

Both: open `chrome://extensions`, remove Claude Usage Tracker, and log out.
````

Replace the `.deb install` subsection with the accurate cleanup. `~/.config/claude-usage` is never written by any script — drop it. Add the two real leftovers and a one-line note on why they're left behind:

````markdown
**.deb install:**

```bash
sudo apt remove claude-usage
```

`postrm` runs as root, so it only cleans system files under `/usr/share/`. Per-user state from `claude-usage-setup` is left behind — remove it manually for a full wipe:

```bash
rm -f  ~/.local/share/applications/claude-usage.desktop
rm -rf ~/.cache/claude-usage
```

(The `org.gnome.shell.enabled-extensions` dconf entry is harmless once the extension files are gone — GNOME Shell silently ignores unknown UUIDs.)
````

Keep the unchanged trailing line:

```markdown
Both: open `chrome://extensions`, remove Claude Usage Tracker, and log out.
```

## Why this shape

- **Notification gets the hint, not the panel label.** Panel real-estate is too tight; the toast is already the user's first signal and has room for two short sentences. One change, single user-facing surface.
- **No new diagnostic surface in the popup.** The reviewer suggested distinguishing the three failure modes in the popup. The toast already fires on the same edge, and adding a hint row to the popup would mean restructuring `_metersSection.removeAll()` and the row-build loop (`extension.js:229-249`) — disproportionate for "tell the user about a script that already exists".
- **MANUAL.md change is purely accuracy cleanup**, not an apologia. Don't list dconf cleanup — it's harmless and the cleanup recipe (`gsettings set ... enabled-extensions` with a sed dance) is more dangerous than the leftover.
- **No `claude-usage-teardown` script.** Tempting to add `claude-usage-setup --uninstall` symmetrically, but pass-4 didn't ask for it and `.deb` users rarely uninstall. Two `rm` lines in the manual is enough.

## Version bump

Per project convention (semver patch bumps for small fixes): `0.9.6 → 0.9.7`. Both files:

- `packaging/control` (`Version:` field)
- `chrome-extension/manifest.json` (`"version":` field)

## Critical files

- `gnome-extension/extension.js` — single string change at line 216.
- `MANUAL.md` — `.deb install` subsection of the Uninstall block (~lines 247–252).
- `packaging/control` — version bump.
- `chrome-extension/manifest.json` — version bump.

## Verification

### Step 1 — JS syntax

```bash
node --check gnome-extension/extension.js
```

```
OK
```

PASS.

### Step 2 — Notification string lives in source

```bash
grep -n 'claude-usage-status to diagnose' gnome-extension/extension.js
```

```
217:                `No update in ${age} min. Open Chrome and click the extension icon, or run claude-usage-status to diagnose.`);
```

PASS.

### Step 3 — Dead path removed from MANUAL.md

```bash
grep -n '~/\.config/claude-usage' MANUAL.md
```

```
absent (good)
```

PASS — no hits.

### Step 4 — New cleanup lines present

```bash
grep -n 'claude-usage\.desktop' MANUAL.md
grep -n '~/\.cache/claude-usage' MANUAL.md
```

```
258:rm -f  ~/.local/share/applications/claude-usage.desktop
105:**Data updates every 15 minutes** — the Chrome extension opens `claude.ai/settings/usage` in a background tab, scrapes the meters, and writes `~/.cache/claude-usage/usage.json`. The panel indicator updates immediately when the file changes.
112:cat ~/.cache/claude-usage/usage.json
259:rm -rf ~/.cache/claude-usage
```

PASS — `.desktop` and cache cleanup lines present (lines 258, 259); the lines 105/112 hits are pre-existing references in the user-facing data-flow section, expected.

### Step 5 — Markdown preview

Not run during the implementation turn (would require user attention to eyeball the rendering). The edit is structurally simple — one fenced bash block removed, one fenced bash block + an italic-free explanatory sentence added, trailing paragraph preserved. Visual confirmation deferred to the user's next `task md -- MANUAL.md` invocation.

### Step 6 — Version bumps in lockstep

```bash
grep -H Version packaging/control
grep -H '"version"' chrome-extension/manifest.json
```

```
packaging/control:Version: 0.9.7
chrome-extension/manifest.json:  "version": "0.9.7",
```

PASS — both files at 0.9.7.

### Step 7 — No live-system disruption

The notification text change won't take effect until the extension is reloaded (Wayland session restart). Per project memory (`feedback_logout_disruption.md`), logout was **not** suggested as a verification step — the source-level grep at step 2 is the verification. The user can confirm the new toast text the next time they happen to log out or test the next `.deb` build.

PASS.
