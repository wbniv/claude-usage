# Code Review — Pass 29 (post-cross-desktop-rename full sweep)

**Date:** 2026-06-01
**Reviewer:** Claude Opus 4.8, four parallel general-purpose review agents + direct read-through
**HEAD:** `2837acb`
**Scope:** First full pass since pass-28 (`f904c3c`). 53 commits landed in between — a major architectural shift: the KDE Plasma 6 plasmoid (`desktop/kde/`, never covered by a numbered pass), the cross-desktop rename (gschema `org.gnome.shell.extensions.claude-usage` → `org.indri.claude-usage`; backends moved to `desktop/{gnome,kde}/`), the GNOME outage status-page link, new lints (`lint-kde-parity`, `lint-qml`, `lint-gnome`), and the CI/docs that surround them. Four reviewers split the surface: (A) KDE plasmoid QML, (B) server Python + the KDE config-mirror, (C) Chrome ext + GNOME extension.js, (D) build/CI/lints/packaging/docs.
**Prior work:** [pass-27](2026-05-20-code-review-pass27.md), [pass-28 (auto-skipped)](2026-05-20-no-pass28-needed.md). All six pass-27 carry-forward items (AS-1, RD-1, SV-1, PL-3, TR-1, IN-1) have since been closed.

---

## 1. Executive Summary

**21 findings:** 2 High, 8 Medium, 9 Low, 2 Info. **15 landed directly** (mechanical, with tests where the surface has a harness); **6 became TODO entries** (design calls). Green baseline (`task test`) confirmed before and after.

Headline: **SRV-1** (High) — `Gio.Settings.new()` on an unregistered gschema calls glib's `g_error()` → an **uncatchable SIGTRAP abort**, not a Python exception. On a KDE-only source install the schema is never compiled (`install.sh` skips it) and `~/.config/claude-usage/config.json` may not exist yet, so `generate-icon.py` hard-crashes on every invocation and the dock icon never renders. The `except Exception` around it gave false confidence. **KQ-1** (High) — the KDE scroll-to-cycle feature was wired to a `MouseArea` on the root `PlasmoidItem`, which receives no panel wheel events in Plasma 6 (only the active representation is laid into the panel) — the documented feature was dead.

| Sev | ID | Surface | Title | Disposition |
|-----|----|---------|-------|-------------|
| ~~**High**~~ | ~~**SRV‑1**~~ | ~~server~~ | ~~`Gio.Settings.new()` on a missing schema aborts the process (uncatchable); breaks the dock icon on KDE/dev installs~~ | ~~Fixed + test~~ |
| ~~**High**~~ | ~~**KQ‑1**~~ | ~~kde~~ | ~~scroll-to-cycle `MouseArea` on root `PlasmoidItem` gets no panel wheel events → feature dead~~ | ~~Fixed (relocated); `[verify][live]` TODO~~ |
| ~~**Med**~~ | ~~**STAT‑1**~~ | ~~scripts~~ | ~~`claude-usage-status.py` crashes on a non-numeric `_timestamp`/`_scrape_fail_count`/`pct` in a corrupt cache (3 sites)~~ | ~~Fixed + test~~ |
| ~~**Med**~~ | ~~**KQ‑4**~~ | ~~kde~~ | ~~`pacingColor` has no runtime `critical > warning` clamp; out-of-band persisted thresholds invert the colour ladder (GNOME has DR-1)~~ | ~~Fixed~~ |
| ~~**Med**~~ | ~~**KQ‑6**~~ | ~~kde~~ | ~~`MeterRow.qml` hardcodes white empty-bar cells + reset text → invisible on light Plasma themes~~ | ~~Fixed (theme colour)~~ |
| ~~**Med**~~ | ~~**CI‑1**~~ | ~~ci~~ | ~~`release.yml` `setup-node@v4` (Node 20); CLAUDE.md mandates the Node-24 major~~ | ~~Fixed (`@v6`)~~ |
| ~~**Med**~~ | ~~**CI‑2**~~ | ~~ci~~ | ~~`gnome-version-check.yml` `checkout@v4` + `github-script@v7` (Node 20), no FORCE env~~ | ~~Fixed (`@v6`/`@v8`)~~ |
| ~~**Med**~~ | ~~**DOC‑1**~~ | ~~docs~~ | ~~`PRIVACY.md` lists `tabs` (not declared) and omits `webNavigation`+`idle` (declared)~~ | ~~Fixed~~ |
| **Med** | **KQ‑2** | kde | count/total + Extra-usage meters render as `N%` + bar; GNOME shows `count/total`/spent-balance with no bar | TODO (design) |
| **Med** | **KQ‑3** | kde | no eligibility / Sonnet-0% filter — KDE shows a dead "Sonnet 0%" row + offers it as a panel metric; GNOME filters | TODO (design) |
| ~~**Low**~~ | ~~**ICN‑1**~~ | ~~server~~ | ~~config.json thresholds `int()`-coerced (DIFF-4) but not range-checked: `threshold_warning:0` → ring permanently amber~~ | ~~Fixed + test~~ |
| ~~**Low**~~ | ~~**KQ‑5**~~ | ~~kde~~ | ~~`FullRepresentation` age not clamped ≥ 0 (parity with BASE-6); not user-visible (the `<1→"just now"` branch absorbs negatives) but landed for parity~~ | ~~Fixed (parity)~~ |
| ~~**Low**~~ | ~~**PKG‑1**~~ | ~~packaging~~ | ~~`build-deb.sh` `cp -r desktop/gnome/.` ships `test/format.test.js` into the release `.deb`~~ | ~~Fixed (rsync --exclude)~~ |
| ~~**Low**~~ | ~~**EXT‑1**~~ | ~~gnome~~ | ~~outage notification's "View Status Page" action shown even for local-only broken (scrape-fail/age), inconsistent with the popup link gate~~ | ~~Fixed (gated on `wantLink`)~~ |
| ~~**Low**~~ | ~~**EXT‑2**~~ | ~~gnome~~ | ~~`STATUS_URL = status.anthropic.com` is a 302 redirect to `status.claude.com`; contradicts the commit's "direct URL" intent + every other ref~~ | ~~Fixed (`status.claude.com`)~~ |
| **Low** | **KQ‑7** | kde | latent ARGB-vs-RGBA 8-digit hex mismatch (Qt `color.toString()` → `#AARRGGBB` vs `hex_to_rgba` `#RRGGBBAA`); inert today (opaque ColorButton → 6-digit) | TODO (design) |
| **Low** | **KQ‑8** | kde | `fontCombo` `find()` at `Component.onCompleted` may highlight the wrong font in the dropdown (persisted value unaffected) | TODO (design) |
| **Low** | **LK‑1** | lints | `lint-kde-parity` config parity guards `<default>` only, not `<range>`/SpinBox `from`/`to` — UI bounds drift past it (bar-width to:40 vs 20, panel-icon to:64 vs 32) | TODO (design) |
| **Low** | **BUF‑1** | server | `_buffered_at` not dropped from `usage.json` on a subsequent live scrape (asymmetric with `_ext_version_mismatch`); inert — no consumer reads it from the cache | TODO (hygiene) |
| ~~**Info**~~ | ~~**EXT‑3**~~ | ~~gnome~~ | ~~popup skip-rebuild fingerprint omits count/total/spent/balance → held-open popup shows a stale count/extra row when pct rounds the same~~ | ~~Fixed~~ |
| ~~**Info**~~ | ~~**EXT‑4**~~ | ~~chrome~~ | ~~`background.js:368` comment says "10 s deadline"; the MutationObserver fallback is `30_000`~~ | ~~Fixed (comment)~~ |

Plus **INFO**: a stale, *locked* git worktree `.claude/worktrees/agent-abd669373a1f58f68/` holds the entire pre-rename layout (`gnome-extension/`, old gschema id) at commit `ac9b4e9`. It pollutes rename-fallout greps. Not touched this pass — it is locked and belongs to another session; left for the user to `git worktree remove --force` if desired.

---

## 2. Findings landed

### Server / scripts (Agent B)

**SRV‑1 (High)** — `server/generate-icon.py:103+`, `scripts/popup-preview.py:81+`. `Gio.Settings.new('org.indri.claude-usage')` on an **unregistered** schema id calls `g_error()` → SIGTRAP/abort (exit 133), which neither the inner `except Exception` nor `__main__`'s catch can intercept. Reachable on a KDE-only source install (`install.sh` runs only `kde_install_plasmoid`, skipping the `glib-compile-schemas` calls) and on any dev checkout, whenever `~/.config/claude-usage/config.json` is also absent (so `load_config` falls through to GSettings). Verified live: `SettingsSchemaSource.get_default().lookup('org.totally.fake', True)` returns `None` (catchable); the real id returns truthy. **Fix:** extracted `_gsettings_or_none()` — probes the schema source with `lookup()` (returns `None` instead of aborting) and returns `None` → `load_config` falls back to `DEFAULTS`. Same guard added to `popup-preview.py`. **Test:** `test_load_config_schema_absent_falls_back` (the GSettings-fallback path had zero coverage).

**STAT‑1 (Medium)** — `scripts/claude-usage-status.py:37,53,91` + the meter loop. The diagnostic — the tool a user runs *because* something's broken — wrapped only `json.loads` in `try/except`, then did `time.time() - _timestamp`, `sfc >= 2`, `_timestamp > 0`, and `f'{pct:3d}'` on trusted-but-possibly-corrupt cache fields. A non-numeric value (downgrade / hand-edit) → uncaught `TypeError`/`ValueError`. **Fix:** coerce `_timestamp`/`_scrape_fail_count`/`pct` defensively (bool ⊂ int, excluded). **Test:** `server/tests/test_status.py` — the new test immediately surfaced the third site (`:91 raw_ts > 0`) that the agent's read had missed.

**ICN‑1 (Low)** — `server/generate-icon.py:92`. DIFF-4 `int()`-coerces config.json thresholds but never range-checks them; `threshold_warning:0` from a hand-edited config makes `ring_color()` read every meter as warning. **Fix:** reject out-of-range values against `schema_defaults.RANGES`, falling back to the default (same shape as the existing invalid-colour fallback). **Test:** `test_config_json_out_of_range_threshold_falls_back`.

### KDE plasmoid (Agent A + direct read)

**KQ‑1 (High)** — `desktop/kde/contents/ui/main.qml`. Scroll-to-cycle lived in a `MouseArea { anchors.fill: parent }` on the root `PlasmoidItem`. In Plasma 6 only the active `compactRepresentation`/`fullRepresentation` is laid into the panel — the root item has no panel geometry, so the wheel handler never fired. The feature is documented (plan + 05-30 verification) but was dead. **Fix:** added `root.cycleMeter(delta)` and a `WheelHandler` in `CompactRepresentation.qml` (the item actually in the panel; `WheelHandler` doesn't participate in the layout and leaves click-to-expand to the framework). qmllint 6.10.2 parses all 8 QML files cleanly. Runtime behaviour can't be confirmed without a Plasma session → **`[verify][live]` TODO** via `task test-kde-live`.

**KQ‑4 (Medium)** — `main.qml:pacingColor`. No runtime `critical > warning` clamp; the SpinBox interlock only fires on user edits, so a threshold pair persisted out of order (kwriteconfig6 / migration) inverts the colour ladder. **Fix:** `const tCrit = Math.max(thresholdCritical, tWarn + 1)` — mirrors extension.js's DR-1.

**KQ‑6 (Medium)** — `MeterRow.qml:44,62`. Empty-bar cells (`Qt.rgba(1,1,1,0.2)`) and the reset hint (`Qt.rgba(1,1,1,0.6)`) were hardcoded white → invisible on a light Plasma theme. **Fix:** added `import org.kde.kirigami` + a `_dimColor: Kirigami.Theme.textColor` property; both now derive from the theme text colour.

**KQ‑5 (Low)** — `FullRepresentation.qml:26`. Age lacked `Math.max(0, …)` (vs BASE-6). The agent correctly downgraded this: the `ageMin < 1 → "just now"` branch already absorbs a negative age, so the feared "-5m ago" can't render. Landed the clamp anyway for cross-desktop parity/clarity; **not** a user-visible bug.

### GNOME / Chrome (Agent C)

**EXT‑1 (Low)** — `extension.js:629`. The broken-tier toast added a "View Status Page" action for *all* broken causes, including local-only ones (scrape-fail, age-timeout) where the popup `_statusItem` link is deliberately *not* offered. **Fix:** gate `addAction` on the same `wantLink` (Anthropic-reported-outage) condition.

**EXT‑2 (Low)** — `extension.js:23`. `STATUS_URL = https://status.anthropic.com/` — verified `curl -I` returns **302 → status.claude.com**, while `status.claude.com` is **200** (direct). The commit that landed this said "use direct URL instead of redirect" (it picked the redirect), and every other ref (`background.js`, `lint-security-doc.py`) uses `status.claude.com`. **Fix:** point at `status.claude.com`; tidied the adjacent `status.claude.ai` comment too. Both resolve today, so zero user risk; this just matches the canonical host and survives retirement of the vanity domain.

**EXT‑3 (Info)** — `extension.js:670`. The UX-1 open-popup skip-rebuild fingerprint omitted `count/total/spent/balance`, so a held-open popup wouldn't refresh a count/extra row that changed while `pct` rounded identically (100/201 → 100/200). **Fix:** added those fields to `meterKey`.

**EXT‑4 (Info)** — `background.js:368`. Comment said "10 s deadline"; the fallback is `30_000`. **Fix:** comment → 30 s.

### Build / CI / packaging / docs (Agent D)

**CI‑1 (Medium)** — `.github/workflows/release.yml:44`. `actions/setup-node@v4` (Node 20). The action has a Node-24 major; CLAUDE.md says pin the major rather than lean on `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` when one exists. **Fix:** `@v6` (verified Node 24).

**CI‑2 (Medium)** — `.github/workflows/gnome-version-check.yml:15,44`. `checkout@v4` + `github-script@v7` (both Node 20), and this workflow has **no** FORCE env, so after GitHub's 2026-06-02 default flip / 2026-09-16 removal they break. **Fix:** `checkout@v6`, `github-script@v8` (verified both run on Node 24; v8 is the non-breaking major over v9's ESM-only break).

**DOC‑1 (Medium)** — `PRIVACY.md:30-38`. The CWS privacy table listed `tabs` (not in the manifest) and omitted `webNavigation` + `idle` (both declared and user-visible at install). **Fix:** drop `tabs`; add `webNavigation`/`idle`; tighten the host rows to the manifest's exact patterns (`claude.ai/settings/usage*`, `status.claude.com/api/v2/*`). (`lint-security-doc.py` checks SECURITY.md only — see LK-1-adjacent note.)

**PKG‑1 (Low)** — `packaging/build-deb.sh:40`. `cp -r desktop/gnome/.` shipped `test/format.test.js` into the release `.deb`; the chrome copy already used `rsync --exclude=test/`. **Fix:** rsync with the same excludes. Verified: `dpkg-deb -c` shows no `test/`/`__pycache__`/`.pyc` in the artifact.

---

## 3. Deferred to TODO (design calls)

- **KQ‑2** — KDE renders count/total + Extra-usage meters as `N%` + bar; GNOME shows `count/total` (no bar) and spent/balance. Behavioural/UX parity decision.
- **KQ‑3** — KDE has no eligibility / Sonnet-0% filter on the popup, panel-metric radios, or scroll-cycle; GNOME hides Sonnet-0% and bars it from selection. UX decision.
- **KQ‑7** — latent ARGB(`#AARRGGBB`)-vs-RGBA(`#RRGGBBAA`) hex mismatch between Qt `color.toString()` and `generate-icon.py:hex_to_rgba`. Inert (ColorButton is opaque → 6-digit). Only bites if alpha is ever enabled.
- **KQ‑8** — `fontCombo` dropdown highlight may be wrong if `cfg_popupFontFamily` loads after the child `onCompleted`. Cosmetic; persisted value correct.
- **LK‑1** — extend `lint-kde-parity`'s config-parity to also compare gschema `<range>` against `ConfigGeneral.qml` SpinBox `from`/`to` (with a documented exception for the threshold-warning/critical offset). Today only `<default>` is guarded.
- **BUF‑1** — `usage-server.py` retains `_buffered_at` in `usage.json` after a later live scrape (asymmetric with the `_ext_version_mismatch` drop). Inert — no consumer reads it from the cache; cache-hygiene only.

---

## 4. Items dismissed / verified clean

- **KQ‑5's user-visible claim** — the `ageMin < 1 → "just now"` branch absorbs negative ages, so the "-5m ago" the original candidate feared cannot render. Landed the clamp for parity only.
- **scraper↔background parity, pacing math (JS↔Python↔QML), config-default parity, MV3 SW lifecycle (AS-1/RD-1/IN-1), GNOME 45–50 MessageTray path, atomic writes, orphan sweep, `_validate`** — all re-checked by the agents against live data and found correct (the recently-closed deferred items verified as correct fixes, not just closed).
- **The cross-desktop rename** — no stale `gnome-extension/` or old gschema id in any in-scope script/doc (all stale hits were in `docs/` history or the locked INFO worktree).

---

## 5. Recommended fix order (as applied)

1. `SRV-1` — schema-presence guard + test (highest impact: silent dock-icon death on KDE).
2. `STAT-1`, `ICN-1` — server hardening + tests.
3. `KQ-1`, `KQ-4`, `KQ-6`, `KQ-5` — KDE QML (verified via lint-qml + lint-kde-parity).
4. `EXT-1`, `EXT-2`, `EXT-3`, `EXT-4` — GNOME/Chrome (verified via test-scraper + test-gnome-format + lint-gnome).
5. `CI-1`, `CI-2`, `DOC-1`, `PKG-1` — build/CI/docs (PKG-1 verified via `dpkg-deb -c`).
6. TODO entries for the 6 design calls + the `[verify][live]` KQ-1 confirmation.

---

## 6. Resolution log

| ID | Title | Resolution |
|----|-------|------------|
| SRV‑1 | `Gio.Settings.new()` uncatchable abort on missing schema | **Fixed** — `_gsettings_or_none()` probes `SettingsSchemaSource.lookup()` first in `generate-icon.py` + `popup-preview.py`; `test_load_config_schema_absent_falls_back` added |
| KQ‑1 | scroll-to-cycle dead on root `PlasmoidItem` | **Fixed** — `cycleMeter()` + `WheelHandler` in `CompactRepresentation.qml`; lint-qml clean; `[verify][live]` TODO for live Plasma confirmation |
| STAT‑1 | diagnostic crashes on corrupt-cache numeric fields | **Fixed** — defensive coercion at all 3 sites (`:37/:53/:91`) + meter loop; `server/tests/test_status.py` added (caught the 3rd site) |
| KQ‑4 | `pacingColor` no critical>warning clamp | **Fixed** — `Math.max(thresholdCritical, tWarn+1)`, DR-1 parity |
| KQ‑6 | hardcoded white invisible on light themes | **Fixed** — `Kirigami.Theme.textColor` via `_dimColor` + Kirigami import |
| CI‑1 | `setup-node@v4` (Node 20) | **Fixed** — `@v6` |
| CI‑2 | `checkout@v4` + `github-script@v7` (Node 20) | **Fixed** — `@v6` + `@v8` |
| DOC‑1 | PRIVACY.md permission table wrong | **Fixed** — dropped `tabs`, added `webNavigation`/`idle`, tightened host rows |
| ICN‑1 | config.json threshold not range-checked | **Fixed** — range check vs `RANGES`, fallback to default; test added |
| KQ‑5 | age not clamped ≥ 0 | **Fixed (parity)** — `Math.max(0, …)`; not user-visible (downgraded) |
| PKG‑1 | `.deb` ships `test/format.test.js` | **Fixed** — rsync `--exclude`; verified via `dpkg-deb -c` |
| EXT‑1 | status-page action on local-only broken | **Fixed** — gated on `wantLink` |
| EXT‑2 | `STATUS_URL` is the redirect host | **Fixed** — `status.claude.com` (curl-verified 302) |
| EXT‑3 | popup fingerprint omits count/spent/balance | **Fixed** — added to `meterKey` |
| EXT‑4 | stale "10 s" comment | **Fixed** — → 30 s |
| KQ‑2 | count/Extra meter rendering parity | **Deferred** — TODO (design) |
| KQ‑3 | no eligibility / Sonnet-0% filter | **Deferred** — TODO (design) |
| KQ‑7 | latent ARGB/RGBA 8-digit mismatch | **Deferred** — TODO (design; inert today) |
| KQ‑8 | fontCombo dropdown highlight timing | **Deferred** — TODO (design; cosmetic) |
| LK‑1 | lint-kde-parity misses `<range>`/SpinBox bounds | **Deferred** — TODO (design) |
| BUF‑1 | `_buffered_at` not dropped on live scrape | **Deferred** — TODO (hygiene; inert) |
