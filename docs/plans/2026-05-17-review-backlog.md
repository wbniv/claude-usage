# Review Backlog — Post Pass-7 Fixes

**Date:** 2026-05-17  
**Status:** Complete  
**Triggered by:** Pass 4–7 review backlog items remaining after pass-7 fixes landed

## Scope

Closed six deferred review items in one session. All were sub-release-threshold changes; no version bump. One commit per item.

## Changes

| ID | Commit | Description |
|----|--------|-------------|
| A1 | `ab35186` | GitHub Actions `release.yml` on `v*.*.*` tag push; cache prebaked test image; `task release` becomes preflight-only |
| A3 | `8b0544d` | MANUAL.md: warn against mixing `.deb` + source installs (systemd unit conflict) |
| CQ6-13 | `2fee72e` | SPA navigation auto-scrape: add `webNavigation` permission + `onHistoryStateUpdated` listener; extract `_autoScrapeIfEligible()` helper |
| CQ pass-5 | `1a53e2a` | Replace `scripts/claude-usage-status.sh` (bash+heredoc) with pure Python `scripts/claude-usage-status.py` |
| CQ6-14 | `9738eae` | MANUAL.md: fix status example text to match actual Statuspage format (`"Minor Service Outage"`) |
| Hardening | `0db082c` | Add 9 systemd hardening directives to `claude-usage-fetch.service` |

## Details

### A1 — GitHub Actions CI

`.github/workflows/release.yml` triggered on `v*.*.*` tag push. Caches the prebaked `claude-usage-test:latest` Docker image in GitHub Actions cache (keyed on `packaging/control` + `test-deb.Dockerfile`); warm runs take ~10 s. Workflow: load/build image → `task build` → inline docker test → `task build-chrome-zip` → `gh release create`.

`task release` strips `deps: [build, build-chrome-zip, test-deb]` and the `gh release create` step; becomes: preflight checks → `git push origin main` → `git tag` → `git push origin TAG`.

See [2026-05-17-github-actions-ci.md](2026-05-17-github-actions-ci.md) for full detail.

### A3 — Install conflict doc note

Added a blockquote between Option B and "Both paths" in `MANUAL.md` explaining the systemd unit precedence conflict when both install methods are active simultaneously, with a pointer to the Uninstall section.

### CQ6-13 — SPA navigation

`chrome.tabs.onUpdated` only fires `status: complete` on hard page loads. SPA navigation via `history.pushState` (claude.ai sidebar → Settings → Usage) produces `webNavigation.onHistoryStateUpdated` instead.

Added `"webNavigation"` to `manifest.json` permissions. Extracted `_autoScrapeIfEligible(tabId, url)` from the existing `tabs.onUpdated` listener body. Both the hard-nav and SPA-nav listeners now call the shared helper. The URL filter `{ hostEquals: 'claude.ai' }` on the `webNavigation` listener prevents the background SW from waking for unrelated SPA apps.

### CQ pass-5 — Python diagnostics binary

`scripts/claude-usage-status.sh` was a bash wrapper with a Python heredoc for all the meaningful logic. Replaced with `scripts/claude-usage-status.py` using `subprocess.run()` for `systemctl` and `gnome-extensions` calls. Updated `packaging/build-deb.sh`, `install.sh` (source path `.sh` → `.py`), and `packaging/test-deb-verify.sh` (`bash -n` → `python3 -m py_compile`).

### CQ6-14 — MANUAL.md example text

Changed `"Elevated 5xx on Claude.ai"` (incident-specific, never actually sent by Statuspage) to `"Minor Service Outage"` (actual page-level status string format).

### Systemd hardening

Added to `[Service]` in `systemd/claude-usage-fetch.service`:

```ini
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectControlGroups=yes
ProtectKernelModules=yes
ProtectKernelTunables=yes
RestrictAddressFamilies=AF_INET AF_UNIX
RestrictNamespaces=yes
LockPersonality=yes
```

Omitted: `ProtectHome=` (breaks home-dir writes), `PrivateNetwork=yes` (breaks HTTP server), `MemoryDenyWriteExecute=yes` (can conflict with pycairo/PIL). Verified with `systemd-analyze verify`, live restart, and POST smoke test.

## Remaining Backlog

| Item | Status |
|------|--------|
| CQ8 (pass 5) — `Name=` overwrite in `update_desktop` affects Activities search | Deferred — needs live GNOME session test |
| A2 — `metadata.json` has `version: 1` | Deferred — only relevant for EGO (extensions.gnome.org) submission |
| A5 — `dist/` accumulates old `.deb` versions | Deferred — cosmetic |
| CQ6-6 — server-spawned generate-icon missing `--tier` | Won't fix — asymmetry by design |
| CQ6-7 — `_period_lengths` accumulates labels forever | Won't fix — bounded by label universe |
