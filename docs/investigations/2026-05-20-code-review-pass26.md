# Code Review — Pass 26 (deep / max-effort / user-requested)

**Date:** 2026-05-20
**Reviewer:** Claude Opus 4.7 (ultrathink), five parallel general-purpose agents
**HEAD:** `2c6d2e8`
**Scope:** Full-codebase cross-cutting sweep — explicitly requested by the user after the auto-skip at pass-25, to find classes the diff-narrow passes (17–24) systematically missed.
**Prior work:** [pass-24](2026-05-20-code-review-pass24.md), [pass-25 auto-skip](2026-05-20-no-pass25-needed.md), [pass-23](2026-05-20-code-review-pass23.md)

---

## 1. Executive Summary

**29 findings:** 5 High, 14 Medium, 9 Low, 1 Info. The diff-narrow passes had hardened the obvious surfaces; this pass surfaces cross-cutting drift, lifecycle / lockscreen edge cases, release-pipeline gates, and a fourth tier-color mirror PS-1 didn't catch.

The high-impact theme: **release pipeline lacks pre-tag validation, and several drift routes the parity lints can't see** (hex colors, section-anchor strings, the `_doc_render._tier_color` fourth mirror).

| Sev | # | ID | Surface | Title |
|-----|---|----|---------|-------|
| **High** | 1 | ~~**RL‑1**~~ | release | ~~`task release` pushes tag *before* running tests; CI is the only gate, and a failing build leaves a broken public tag (history: v0.11.14, v0.11.15)~~ |
| **High** | 2 | **UX‑1** | gnome-ext | 30 s tick rebuilds the entire popup menu via `removeAll()` even while open — visible flicker + lost hover state |
| **High** | 3 | **PL‑1** | lints | Pacing-parity lint diffs only numeric literals; hex colors / period strings / role names drift invisibly |
| **High** | 4 | **TCM‑1** | docs/lints | `_doc_render._tier_color` is a 4th hand-written tier-color mirror (alongside extension.js, popup-preview.py, generate-icon.py) — not in PS-1's pair list |
| **High** | 5 | **GI‑1** | render | `generate-icon.py:286` hardcodes broken-tier red `'#e03030'`; should read `cfg['popup_color_critical']` |
| **Medium** | 6 | ~~**ACC‑1**~~ | server | ~~`is_full_scrape` tautology: after `body = {**prev, **body}` + auto-timestamp fill, the timestamp gate is always True — a 2-fake-meter POST wipes accumulated `period_lengths`~~ |
| **Medium** | 7 | ~~**NM‑1**~~ | server | ~~`_validate` accepts `{"meters": null}`; cache persists with `meters: None` and crashes every downstream consumer until hand-fixed~~ |
| **Medium** | 8 | **RV‑1** | render | Dock-icon ring returns before drawing the tick when `pct == 0`; popup bar still draws it — popup vs dock disagree at 0% mid-period |
| **Medium** | 9 | **AS‑1** | chrome-ext | `_autoScrapeIfEligible` seizes `_fetching` *before* the storage-backed eligibility check; ineligible auto-scrapes can starve a legitimate alarm fire for the next 7 min |
| **Medium** | 10 | **RD‑1** | chrome-ext | `chrome.idle.onStateChanged` 'active' fires on every screen unlock, not just wake-from-suspend; no debounce → claude.ai burn on every lockscreen toggle |
| ~~**Medium**~~ | ~~11~~ | ~~**PRT‑1**~~ | ~~chrome-ext~~ | ~~`probePorts()` uses `Promise.all` + `.find(p => p !== null)` — winner is array-index lowest port, not the fastest responder; a slow-but-valid squatter on 7331 beats a real server on 7332~~ |
| **Medium** | 12 | **PVS‑1** | gnome-ext | `pacingSegments` rounds both `fill` and `elapsedPos` to int — at e.g. pct=51 / elapsedFrac=0.5 / w=10 both become 5, so the over-pace cell renders as a `tick` (on-pace signal) instead of `over_pace` |
| **Medium** | 13 | **LC‑1** | gnome-ext | `_monitor.connect('changed', …)` handler ID is never stored — can't be disconnected on `destroy()`; small leak per Wayland session lock/unlock |
| **Medium** | 14 | ~~**SH‑1**~~ | shells | ~~`claude-usage-setup -h` actually re-runs the full setup (writes desktop entry, restarts systemd unit). Same on `build-deb.sh -h`, `build-chrome-zip.sh -h`. SRC CLAUDE.md rule violated~~ |
| **Medium** | 15 | ~~**VR‑1**~~ | build | ~~`VERSION` Taskfile var silently fills empty if `packaging/control:Version:` is malformed — builds `claude-usage__all.deb` with double underscore~~ |
| **Medium** | 16 | ~~**PYC‑1**~~ | build | ~~`.deb` chrome-extension rsync excludes `test/` but NOT `__pycache__/`, `*.pyc`, `.DS_Store`; chrome-zip excludes them. Asymmetry leaks dev artifacts into user .deb~~ |
| **Medium** | 17 | **SV‑1** | gnome-ext | `metadata.json:shell-version` whitelists 45-49; Ubuntu 26.04 (~Apr 2026, GNOME 50) silently fails to enable with no postinst warning |
| **Medium** | 18 | **PL‑3** | lints | Scraper parity lint diffs only regex literals — section anchors (`'Plan usage limits'`, `'Extra usage'`) and DOM selectors are unchecked |
| **Medium** | 19 | **TSP‑1** | tests | No regression test pins `pid_position` semantics — a future refactor moving the field could silently re-introduce TS-2's class |
| **Low** | 20 | ~~**SC‑1**~~ | server | ~~`signal.signal(SIGCHLD, SIG_IGN)` runs at module import — every test that imports `usage-server.py` silently mutates the global handler~~ |
| **Low** | 21 | ~~**UD‑1**~~ | server | ~~`update_desktop` rewrites every `Name=`/`Icon=` line including those inside `[Desktop Action …]` subgroups — latent today, breaks the moment we add an action~~ |
| **Low** | 22 | **PP‑1** | server | `render_panel_label` (popup-preview) picks the primary meter without the `is_sonnet_hidden` filter that `get_primary` applies three functions over — silent panel/popup drift |
| ~~**Low**~~ | ~~23~~ | ~~**TC‑1**~~ | ~~chrome-ext~~ | ~~Tab-load 30 s timeout resolves on `info.status === 'complete'` even for `chrome-error://` error pages; user sees mysterious "empty meters" not "claude.ai is down"~~ |
| ~~**Low**~~ | ~~24~~ | ~~**PR‑2**~~ | ~~chrome-ext~~ | ~~`postUpdate` retries exactly once on cache miss; a 5 s server restart strands the buffered scrape for the next 7-minute alarm tick~~ |
| **Low** | 25 | **I18N‑1** | gnome-ext | Panel label uses `margin-left` instead of CSS-logical `margin-start` — RTL locales (Arabic, Hebrew, Persian) get the gap on the wrong side |
| **Low** | 26 | **EVC‑1** | gnome-ext | Persistently-corrupt cache leaves the indicator silent (`No data yet` forever); no in-popup hint to check `journalctl` |
| **Low** | 27 | **TR‑1** | repo | `docs/transcripts/` is tracked + special-cased in `task release`'s dirty check → chronically dirty `git status`; pick either gitignore or commit-on-release |
| **Low** | 28 | **PL‑4** | lints | Pair list in `lint-scraper-parity.py` is hand-maintained; no auto-discovery means the next added JS↔Python twin is unprotected until manually added (PS-1, now TCM-1) |
| **Info** | 29 | **IN‑1** | chrome-ext | `tabs` permission is broader than the documented surface needs; `host_permissions` + `activeTab` would shrink the Chrome Web Store warning string |

---

## 2. Surface-by-surface

### Server / Python (5 findings)

**ACC‑1 (Medium)** — `usage-server.py:393-424`. PL-1 (pass-16) added `is_full_scrape = (_timestamp is not None AND len(meters) >= 2)` to gate eviction. But `body = {**prev, **body}` (line 393) merges prev, and the auto-timestamp fill (397-399) sets `_timestamp = int(time.time())` if missing. So after line 399, `body['_timestamp']` is *never* None — the timestamp conjunct is always True. The only real gate is `len(meters) >= 2`. A bogus 2-meter POST (`curl -X POST -d '{"meters":[{"label":"x","pct":1},{"label":"y","pct":1}]}'`) wipes accumulated `period_lengths` until re-accumulation (hours to days). **Fix:** compute `is_full_scrape` against the *incoming* request only, before the merge:
```python
incoming_has_ts = ('_timestamp' in body) or ('timestamp' in body)
incoming_meters = body.get('meters') or []
# ... existing merge ...
is_full_scrape = incoming_has_ts and isinstance(incoming_meters, list) and len(incoming_meters) >= 2
```

**NM‑1 (Medium)** — `usage-server.py:120-123, 446-448`. `_validate` skips the type check when `meters is None`. `{"meters": null}` validates clean, the cache writes `meters: None`, and every downstream call (`_tooltip_tick`, `generate-icon.py`, `claude-usage-status.py`) crashes on `len(None)` / `for m in None`. Recovery requires manual `rm ~/.cache/claude-usage/usage.json`. **Fix:** reject explicit-null OR normalize to `body.pop('meters', None)` at write time.

**RV‑1 (Medium)** — `generate-icon.py:163-164` vs `popup-preview.py:170-183`. `draw_ring` returns early when `pct <= 0` *before* drawing the elapsed-fraction tick; `pacing_segments` in popup-preview emits the tick at `elapsed_pos` even when `fill == 0` (the `'zero'` canonical case). User at 0% mid-period sees the tick in the popup but a featureless empty ring on the dock — silent surface drift the PS-1 parity lint doesn't catch (it pairs against popup-preview, not generate-icon). **Fix:** lift tick math into `_draw_tick` helper; call from both branches.

**SC‑1 (Low)** — `usage-server.py:12`. `signal.signal(SIGCHLD, SIG_IGN)` runs as a top-level import side-effect — every test in `server/tests/` that uses `importlib.util.spec_from_file_location` + `exec_module` mutates the global signal handler. Not a runtime bug today; a foot-gun for tests growing. **Fix:** move into `if __name__ == '__main__':`.

**UD‑1 (Low)** — `tooltip.py:136-148`. `update_desktop` rewrites every `Name=`/`Icon=` line in the `.desktop` file — including those inside `[Desktop Action xxx]` subgroups. Latent today (no actions); breaks the first time we add one. **Fix:** track `in_main = (section == '[Desktop Entry]')` and only mutate inside.

**PP‑1 (Low)** — `popup-preview.py:399-419`. `render_panel_label` picks the primary meter without calling `get_primary` (which applies `is_sonnet_hidden`). Debug-only path (not shipped) but it's exactly the kind of silent drift the file was supposed to surface. **Fix:** call `get_primary(meters, cfg)` instead of re-implementing.

---

### Chrome extension (6 findings)

**AS‑1 (Medium)** — `background.js:622-644`. R-1 (pass-16) added the `_fetching` mutex inside `_autoScrapeIfEligible`. But the mutex is now flipped to `true` *before* the storage-backed eligibility checks (`_scrape_tabs.includes(tabId)`, debounce window). If either check rejects, the function returns from the `try`; the `finally` releases the mutex — but in the 10-50 ms window, an arriving alarm-driven `fetchUsage()` sees `_fetching === true` and bails silently. Next alarm is 7 min away. **Fix:** do eligibility checks *before* seizing the mutex (still async but doesn't hold the mutex).

**RD‑1 (Medium)** — `background.js:702-706`. `chrome.idle.onStateChanged` 'active' fires on every screen unlock (gnome-screensaver lock cycle, screensaver dim, suspend wake) — and goes straight to `fetchUsage()` with no debounce. SPA-navigation paths funnel through `AUTO_DEBOUNCE_MS = 30s`; this path doesn't. Cost: claude.ai page-load + Statuspage hit per lockscreen toggle. **Fix:** add `WAKE_MIN_INTERVAL_MS = 5*60*1000` debounce against `_last_scrape_ts`.

**PRT‑1 (Medium)** — `background.js:19-43`. `probePorts()` uses `Promise.all(probes)` (waits for all to settle) + `.find(p => p !== null)` (returns *first array index* with non-null result). Despite the comment "Race all ports concurrently. First /hello response wins," winner is determined by port order, not by response time. A squatter on 7331 that takes 490 ms to respond beats a real server on 7332 that answered in 5 ms. Compounded by `isOurs` checking only header *presence*, not its semver-shaped value. **Fix:** use `Promise.any(probes)` (true race-to-first-resolve) + semver-validate the header value:
```javascript
const isOurs = r => /^\d+\.\d+\.\d+/.test(r.headers.get('x-claude-usage-server') || '');
```

**TC‑1 (Low)** — `background.js:565-587`. Tab-load 30 s timeout resolves on `info.status === 'complete'` — but error pages (claude.ai 502, DNS failure, corporate proxy injection) also fire `complete`. Scraper runs against the error DOM, finds no `% used`, hits the 30 s MutationObserver deadline → empty-meters POST → mysterious `_scrape_fail_count` with no diagnostic that "claude.ai returned an error page." **Fix:** check `tab.url.startsWith('chrome-error://')` in the listener.

**PR‑2 (Low)** — `background.js:169-198`. `postUpdate` retries exactly once on cache miss. A 5 s server restart (e.g. during `.deb` upgrade) strands the buffered scrape for the next 7-min alarm. **Fix:** three attempts with 1 s + 3 s back-off — catches sub-5 s restarts.

**IN‑1 (Info)** — `manifest.json:6-13`. `tabs` permission is broader than the documented surface needs. `host_permissions` + `activeTab` would let `tabs.query({url: '…'})` still return hydrated URLs without triggering the "Read your browsing history" Chrome Web Store install warning. Hardening for future publishing.

---

### GNOME extension (5 findings)

**UX‑1 (High)** — `extension.js:321-324, 577-619`. The 30 s tick unconditionally calls `_updateDisplay`, which calls `this._metersSection.removeAll()` and re-adds every `PopupMenuItem`. If the popup is open at tick time (the *intended* user behavior), every item is destroyed and recreated — visible flicker, lost hover state, layout shift. **Fix:** fingerprint the inputs and short-circuit when nothing changed:
```javascript
const fp = JSON.stringify({metersTs: d._timestamp, plan, tier, panelMetric, tWarn, tCrit, ...});
if (this._lastFp === fp && this.menu.isOpen) {
    this._statusItem.label.set_text(reason || `${plan}${ageStr}`);
    return;
}
this._lastFp = fp;
```

**PVS‑1 (Medium)** — `extension.js:128-148`. `pacingSegments` rounds both `fill = round(pct/100 * width)` and `elapsedPos = round(elapsedFrac * width)` to integers. At pct=51, elapsedFrac=0.5, width=10: both round to 5, `fill > elapsedPos` is false, and the renderer emits a `tick` (on-pace signal) at position 5 even though the user is 1% over pace. The Cairo dock-icon ring uses *unrounded* `fill_frac > elapsed_frac` and correctly shows two-tone. **Fix:** decide over-pace using raw fractions (`overPaceRaw = elapsedFrac != null && fillFrac > elapsedFrac`) and use that flag for both segment role assignment AND tick suppression.

**LC‑1 (Medium)** — `extension.js:340-361, 701-745`. `_monitor.connect('changed', …)` handler ID is never stored. On disable→re-enable (every Wayland session lock/unlock!), if any signal is queued in the main loop, it dispatches against a half-destroyed indicator. Small per-cycle leak. **Fix:** store the ID, call `this._monitor.disconnect(this._monitorChangedId)` in destroy.

**I18N‑1 (Low)** — `extension.js:268, 415, 461`. Panel label uses physical `margin-left` instead of CSS-logical `margin-start`. In RTL locales, the gap appears on the wrong side; icon and label collide. **Fix:** three-line s/margin-left/margin-start/.

**EVC‑1 (Low)** — `extension.js:392-400`. When the cache file is corrupt AND `_data` is null (e.g. on first-load after corruption), the status row shows `No data yet` forever — no hint to check journal. **Fix:** distinguish the parse-failed case and surface "Cache unreadable — check journalctl".

---

### Build / Install / CI (6 findings)

**RL‑1 (High)** — `Taskfile.yml:134-180`. `task release` runs preflight (branch/dirty/version-sync), then `git push origin main && git tag && git push origin <tag>`. No `task test`, no `task test-deb-fast`. The workflow fires `on: push.tags`, so by the time tests run, `v<X>` already points at the commit. History: `v0.11.14` (failed CI: missing cairo), `v0.11.15` (failed CI: BASE_ICON discovery) — public broken tags. **Fix:** prepend `task: test` + `task: test-deb-fast` to the release cmds list.

**SH‑1 (Medium)** — `packaging/claude-usage-setup`, `packaging/build-deb.sh`, `packaging/build-chrome-zip.sh`. None handle `-h`/`--help`. User typing `claude-usage-setup --help` to discover invocation silently does a full re-setup. SRC CLAUDE.md rule. **Fix:** four-line stanza per script:
```bash
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<EOF
Usage: $(basename "$0") [no arguments]
...
EOF
    exit 0
fi
```

**VR‑1 (Medium)** — `Taskfile.yml:4-6`. `VERSION` filled by `grep '^Version:' packaging/control | awk '{print $2}'`. If the line is malformed, missing, or capitalized differently, the substitution produces an empty string with no error; Task continues. Build writes `dist/claude-usage__all.deb` (double underscore). **Fix:** validate non-empty in the `sh:` block; exit 1 if empty.

**PYC‑1 (Medium)** — `packaging/build-deb.sh:50-55`. Rsync excludes `test/` but not `__pycache__/`, `*.pyc`, `.DS_Store`. Chrome-zip excludes all four. Asymmetry leaks dev artifacts into `/usr/share/claude-usage/chrome-extension/` on user machines whenever the source tree has them. **Fix:** add all four excludes; bonus, a `lint-bundle-parity` lint asserting the two scripts' exclude lists agree.

**SV‑1 (Medium)** — `gnome-extension/metadata.json:5-11`. `shell-version: [45,46,47,48,49]`. GNOME 50 ships in Ubuntu 26.04 (~April 2026) and rolling Fedora/Arch hosts already today. .deb installs; `gnome-extensions enable` silently refuses. No postinst warning. **Fix:** either preemptively add `"50"`/`"51"` after smoke-test, or add a postinst check that compares host's `gnome-shell --version` major to the whitelist and warns.

**TR‑1 (Low)** — `Taskfile.yml:148-154` + `docs/transcripts/`. Tracked but special-cased in release dirty check ("almost always has pending edits"). Tracked + chronically dirty + special-cased is the worst of both worlds. **Fix:** either gitignore it (purely-local) OR add `task transcripts-commit` and require clean status before release.

---

### Tests / Lints / Parity / Drift (6 findings)

**PL‑1 (High)** — `lint-scraper-parity.py:128`. The numeric-literal extractor `\b\d+\.?\d*\b` does not match hex colors (`'#888'`, `'#abcdef'`), string constants, role names, or threshold key paths (`cfg.tCrit` vs `cfg['tCrit']`). All four PS-1 pair functions have hex-color literals; today they happen to agree numerically (`'#888'` shares digits), but a swap to `'#aaa'` would silently pass the lint. **Fix:** extend extractor to also pull quoted string literals; compare as a typed set (numbers + strings).

**TCM‑1 (High)** — `scripts/_doc_render.py:114`. `_tier_color(pacing, cfg)` is the same logic as `colorFor`/`color_for`/`viz_colors` — fourth hand-written mirror. PS-1 added two of four to the lint; this one slipped through. The file's own comment claims "Mirrors extension.js:formatRows exactly," so the contract is real. **Fix:** delete `_tier_color`, replace its call site with `pp.color_for('empty', pacing, cfg)`. Alternatively, add a 5th pair to the lint.

**GI‑1 (High)** — `generate-icon.py:286`. `red = hex_to_rgba('#e03030')` — hardcoded literal for the broken-tier ring. *Happens* to match `popup_color_critical` schema default today; doesn't read from cfg. Customizing the critical color via GSettings leaves the dock ring stuck at literal red. `popup-preview.py:481` has the same literal in the same form for the error row. **Fix:** read from cfg in both sites; add a test asserting no `'#rrggbb'` literals in render paths (sans CSS string blocks).

**PL‑3 (Medium)** — `lint-scraper-parity.py:148`. The scraper parity diff extracts only regex literals, not string constants. Section anchors (`'Plan usage limits'`, `'Additional features'`, `'Extra usage'`, `'Last updated:'`) and DOM selectors (`[role="switch"][aria-label="Extra usage"]`) are duplicated between `scraper.js` and `background.js`'s inline scrape — invisible to the lint. If Anthropic renames a header and someone updates only `scraper.js` (which has the unit tests), production scraping breaks silently. **Fix:** add a string-literal pass to `check_scraper_parity` scoped to the two scrape regions.

**TSP‑1 (Medium)** — `server/tests/test_orphan_sweep.py`. Tests cover live-PID survives / dead-PID removed / unparseable-filename survives — but none pin the `pid_position` semantics. A future refactor moving the field could silently re-introduce TS-2's class. **Fix:** introspection test that reads `usage-server.py` source and asserts the two literal call sites (`pid_position=-2` for desktop, `pid_position=3` for icons) are present.

**PL‑4 (Low)** — `lint-scraper-parity.py:92`. Pair list is hand-maintained. PS-1 had to add `pacingSegments`/`colorFor` *after* drift had happened; TCM-1 is the same class today. **Fix:** add `check_pair_inventory` that scans JS source for `function FooBar(…)`, computes `foo_bar`, and warns if a matching `def foo_bar(…)` exists in the listed `py_file`s without being in `PAIRS`.

---

## 3. Carried-forward TODOs

Carry-forward backlog: empty — every deferred item from prior passes was resolved this session. The 29 findings above are all new this pass.

---

## 4. Recommended fix order

The findings split into three tiers:

**Tier A — pure mechanical, low risk, high value (12 findings).** Closeable in 2-3 thematic commits without any taste calls.
- I18N-1 (margin-start) — 1-line
- SH-1 (3 shell `-h` guards) — 4 lines per script, 3 scripts
- VR-1 (VERSION empty guard) — 5 lines
- PYC-1 (rsync excludes) — 3 lines
- TR-1 (gitignore docs/transcripts/) — 1 line + drop the Taskfile special-case
- SC-1 (SIGCHLD into `__main__`) — 1-line move
- UD-1 (subgroup-aware update_desktop) — 5 lines
- PP-1 (call get_primary in render_panel_label) — 1-line swap
- TC-1 (skip chrome-error pages) — 3 lines
- PR-2 (3-retry back-off in postUpdate) — 8 lines
- EVC-1 (cache-unreadable hint) — 4 lines
- PL-4 (parity pair auto-discovery) — 15 lines

**Tier B — substantive but mechanical (the 5 Highs + several Mediums, 9 findings).** Needs care but no taste call.
- RL-1 (gate `task release` on local tests) — 2 lines added to Taskfile
- UX-1 (fingerprint short-circuit in _updateDisplay) — 8 lines
- PL-1 (extend parity lint to string literals) — 15 lines
- TCM-1 (delete `_tier_color`, call `color_for`) — small refactor
- GI-1 (`#e03030` → `cfg['popup_color_critical']`) — 2 lines × 2 sites
- ACC-1 (compute is_full_scrape pre-merge) — 5 lines
- NM-1 (reject meters: null OR normalize) — 3 lines
- PVS-1 (decide over-pace on raw fractions) — 8 lines, must also fix popup-preview.py twin
- RV-1 (lift `_draw_tick` helper, call from pct==0 branch) — 8 lines

**Tier C — design calls / cross-context (6 findings + 1 info, 7 items).** Worth surfacing before changing:
- **AS‑1** — mutex placement change in autoScrapeIfEligible could surface new races; you may want to think about it
- **RD‑1** — what's the desired wake-debounce? 5 min? 15 min? Trade-off between catching genuine suspends and ignoring screen-lock noise
- **PRT‑1** — Promise.any change is mechanical, but the isOurs semver-validation is a semantic tightening; current code accepts any non-empty header. Is that intentional (forward-compat) or a bug?
- **LC‑1** — current code relies on `_destroyed` guard inside the callback; storing the handler ID is defensive but might not be strictly needed
- **SV‑1** — preemptively add GNOME 50 to whitelist (need smoke-test) OR add a postinst warning (lower-risk)?
- **PL‑3** — scraper string-literal parity needs scope decisions (which strings count? CSS class names? section headers only?)
- **TSP‑1** — pin via source-introspection test (brittle to formatting changes) OR pin via behavior test (need a PID-like number in the size slot)
- **IN‑1** — the `tabs` permission shrinkage needs verification that `tabs.query({url})` actually returns hydrated URL fields with just host_permissions (Chrome docs say yes, but worth testing)

---

## 5. Open question for the user

The user explicitly bypassed `/review-and-fix` and asked for a "code review" — implying review-only this turn. 29 findings is a lot to auto-fix without confirmation. **Recommended next move:**

Either:
1. **"Fix Tier A + B"** — 21 mechanical/substantive findings in ~5 thematic commits; defer the 7 design-call items to TODO.
2. **"Fix Tier A only"** — 12 trivial fixes, defer everything else.
3. **"Just file them all as TODO and stop"** — no commits this turn.
4. **Custom triage** — pick specific IDs to fix.

---

## 9. Resolution log

To be filled in as fixes land.

| ID | Title | Resolution |
|----|-------|-----------|
| RL‑1 | `task release` pre-tag test gate | Fixed — prepended `task: test` as first cmd in `release` task (`Taskfile.yml`) |
| SH‑1 | `-h`/`--help` guards missing on 3 scripts | Fixed — added 6-line `--help` stanza to `packaging/claude-usage-setup`, `packaging/build-deb.sh`, `packaging/build-chrome-zip.sh` |
| VR‑1 | `VERSION` var silently empty on malformed control | Fixed — `sh:` block now validates non-empty and exits 1 with a diagnostic (`Taskfile.yml`) |
| PYC‑1 | `.deb` rsync missing `__pycache__/` / `*.pyc` / `.DS_Store` excludes | Fixed — added all three missing excludes to `packaging/build-deb.sh` and `install.sh` rsync calls |

---

## 10. Loop status

Pass-26 was user-initiated despite the auto-skip verdict at pass-25. The next pass will fire per step 12 *if* fixes land — terminating only when a subsequent pass produces < 3 commits OR zero substantive findings.
