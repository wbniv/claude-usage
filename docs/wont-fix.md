# Won't Fix

Permanent deferrals from all code review passes. Check this file before reopening any of these items in future reviews.

---

## BUG‑5 — Sonnet ring ignores warning/critical color thresholds

**Source:** [pass-1 review](investigations/2026-05-16-code-review.md)  
**Verdict:** By design

Blue always = Sonnet so users can distinguish the current-session ring from the all-models ring by color family at a glance. Applying warning/critical thresholds to the Sonnet ring would break that visual invariant. A comment in the source documents the intent.

---

## CQ6‑5 — `release` task `deps:` run before preflight checks

**Source:** [pass-6 review](investigations/2026-05-17-code-review-pass6.md)  
**Verdict:** Moot (resolved differently)

The structural issue — go-task runs `deps:` in parallel before the first `cmds:` step, so a dirty tree would still build the `.deb` before aborting — was real but the fix would have required restructuring the task. Resolved instead by removing the `deps: [build, build-chrome-zip, test-deb]` entries from `task release` entirely (A1): `task release` is now preflight-only and CI handles build/test/publish. The issue no longer exists.

---

## CQ6‑6 — Server-spawned `generate-icon.py` missing `--tier`

**Source:** [pass-6 review](investigations/2026-05-17-code-review-pass6.md), [pass-7 review](investigations/2026-05-17-code-review-pass7.md)  
**Verdict:** Asymmetry by design

When the server's POST handler invokes `generate-icon.py` it does not pass `--tier`, so the icon always uses the default (no-outage) color regardless of current Statuspage state. The asymmetry is intentional: the extension's 30 s timer fires `generate-icon.py --tier <current>` on each cycle, so any tier mismatch is self-correcting within 30 s. The server is the icon-rendering trigger on the happy path (fresh scrape just landed); the extension is the trigger on the unhappy path (stale data, outage transitions). The two call sites are not interchangeable and do not need to be.

---

## CQ6‑7 — `_period_lengths` dict accumulates labels forever

**Source:** [pass-6 review](investigations/2026-05-17-code-review-pass6.md), [pass-7 review](investigations/2026-05-17-code-review-pass7.md)  
**Verdict:** Won't fix — bounded by label universe

`server/usage_server.py` stores one entry per unique period label (e.g. `"claude.ai Pro"`, `"claude.ai Max"`). The dict grows without eviction, but the universe of labels is controlled entirely by Anthropic and is practically bounded to a small fixed set (~dozen entries). An eviction strategy would add complexity for no real benefit. If Anthropic ever ships hundreds of distinct billing tiers, revisit.

---

## B‑3 — `_scrape_tabs` tab leak between `tabs.create` and `storage.set`

**Source:** [pass-9 review](investigations/2026-05-17-code-review-pass9.md)  
**Verdict:** Can't fix — gap is structurally unavoidable

The concern: if the service worker is suspended in the single microtask turn between `chrome.tabs.create` resolving and `chrome.storage.local.set` completing, the tab ID is never persisted and the orphan-cleanup loop on next wake-up won't find it.

Why it doesn't matter: Chrome service workers can only be suspended at `await` boundaries when the task queue is empty. `tabs.create` just resolved, so the engine is still processing that microtask checkpoint — suspension cannot fire here. The window is real in theory but unreachable in Chrome's scheduler. The alternative (persist before create) is impossible because the ID doesn't exist until after `tabs.create` returns. No fix available that reduces risk meaningfully.

---

## Won't Fix — Not a Bug

### I‑1 — `install.sh` missing `set -euo pipefail`

**Source:** [pass-9 review](investigations/2026-05-17-code-review-pass9.md)

`install.sh` line 2 is `set -euo pipefail`. Already present; review was incorrect.

### M‑1 — Version mismatch between `manifest.json` and README

**Source:** [pass-9 review](investigations/2026-05-17-code-review-pass9.md)

README contains no version string. There is nothing to mismatch; review was incorrect.

---

### BUG‑4 — Weekday numbering inconsistency (Python vs JavaScript)

**Source:** [pass-1 review](investigations/2026-05-16-code-review.md)

Python's `WD_MAP` uses Mon=0…Sun=6, matching `datetime.weekday()`. The JavaScript `wdMap` uses Sun=0…Sat=6, matching `Date.getDay()`. Both are internally consistent with their host language conventions and produce identical reset-day results. The original review made an arithmetic error in comparing them.

### BUG‑6 — Chrome scraper DOM index lacks lower-bound guard

**Source:** [pass-1 review](investigations/2026-05-16-code-review.md)

Every `lines[i-1]` access in `chrome-extension/background.js` is guarded by `i >= 1`; every `lines[i-2]` access is guarded by `i >= 2`. Guards were already consistently applied at all call sites.

---

## Won't Fix — Not a Bug (Comprehensive Review, 2026-05-18)

### CP‑1 — `pacingPct()` division by zero when `period === 0`

**Source:** [2026-05-18 comprehensive review](investigations/2026-05-18-code-review-comprehensive.md)

`extension.js` L64 has `if (rm == null || !period) return pct;` — `!period` is truthy for `0`, so division by zero is already guarded. Pass 10 explicitly confirmed as non-issue.

### CP‑2 — `critMeter` null dereference in notification

**Source:** [2026-05-18 comprehensive review](investigations/2026-05-18-code-review-comprehensive.md)

`critMeter` is only accessed inside the `else if (!this._anyCrit)` branch, which is only entered when `anyCrit` (computed by `some()` on the same array) is `true`, guaranteeing `find()` succeeds. Pass 10 explicitly confirmed as non-issue.

### CP‑3 — GSettings IPC per render (6 D-Bus calls)

**Source:** [2026-05-18 comprehensive review](investigations/2026-05-18-code-review-comprehensive.md)

Reads are intentionally hoisted to the top of `_updateDisplay()` (comment at L277); GSettings also has an in-process cache that batches D-Bus round-trips. No actual per-render IPC cost.

### CP‑4 — `claude-usage-status.py` fragile `systemctl` parsing

**Source:** [2026-05-18 comprehensive review](investigations/2026-05-18-code-review-comprehensive.md)

Service check uses `systemctl show --property=MainPID --value` (clean single-value output, not subject to localization or format variation); extension check parses `gnome-extensions show` with `split(':', 1)` on stable output lines. No fragility.

### CP‑5 — `tooltip.py` silent no-op when `Name=` missing

**Source:** [2026-05-18 comprehensive review](investigations/2026-05-18-code-review-comprehensive.md)

`re.sub` returns `text` unchanged when no match → `new_text == text` → early return is the correct fallback behavior, not a silent bug. Acceptable by design.
