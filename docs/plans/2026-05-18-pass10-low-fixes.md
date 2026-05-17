# Pass-10 Low-Priority Fixes

**Date:** 2026-05-18  
**Status:** In progress  
**Triggered by:** [Pass-10 code review](../investigations/2026-05-17-code-review-pass10.md) (continuation of [2026-05-17-pass10-fixes.md](2026-05-17-pass10-fixes.md))

## Scope

5 low-priority items remaining from pass-10 after high/medium were fixed on 2026-05-17.

## Changes

| ID | File | Fix |
|----|------|-----|
| B-5 | `chrome-extension/background.js`, `chrome-extension/scraper.js` | Add radix 10 to all `parseInt` calls |
| M-2 | `chrome-extension/manifest.json` | Tighten `host_permissions` to `settings/usage*` and `api/v2/*` |
| K-2 | `packaging/postinst`, `packaging/postrm` | `set -e` → `set -euo pipefail` |
| E-9 | `gnome-extension/extension.js` | Retry `_watchFile` after 30 s on failure |
| S-4 | `server/usage-server.py` | Skip live-PID files in orphan sweep |

## Verification

```
task test-scraper   # 45/45 pass
node --check chrome-extension/background.js
node --check chrome-extension/scraper.js
```
