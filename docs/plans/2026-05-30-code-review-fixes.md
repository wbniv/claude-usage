# Code-review fixes — KDE plasmoid + diff/baseline findings

## Context

A max-effort code review (2026-05-29/30) covered the unreviewed wave since the
last loop pass (`d48d593..HEAD`) **and**, by user request, a fresh deep read of
the baseline. The headline: the **KDE Plasma plasmoid shipped completely
non-functional** in 0.11.27 — it throws on the first line of its data-load path
and never recovers. It slipped through because **CI has zero KDE/QML coverage**
(only `lint-gnome` + GNOME/server tests exist).

Root cause of the KDE breakage traces back to *this very plan's predecessor*
(`2026-05-24-kde-desktop-support.md`): it specified the wrong cache-read idiom
(`StandardPaths.HomeLocation + "/.cache/..."` with no `import QtCore`) and the
wrong JSON schema (line 51: "fields: `meters[]`, `status`, `last_update`"). The
implementation faithfully built the plan's wrong contract. The real server
schema is `meters[].reset_minutes`, top-level `_period_lengths`,
`_anthropic_status`, `_timestamp` (confirmed in `usage-server.py` /
`scraper.js` / `extension.js`).

This plan fixes the broken KDE feature, the clear diff regressions, the
server cache-corruption gap, and adds a KDE parity lint so the class can't
recur.

---

## Findings being fixed

| ID | Sev | File | Bug |
|----|-----|------|-----|
| KDE‑1 | CRIT | `main.qml:58,73` | `StandardPaths` used with no `import QtCore` → `loadData()` throws every call → plasmoid never loads data |
| KDE‑2 | HIGH | `main.qml`, `MeterRow.qml`, `FullRepresentation.qml` | reads `reset_ts`/`period_secs`/`status`/`last_update` — none exist (real: `reset_minutes`, `_period_lengths`, `_anthropic_status`, `_timestamp`) |
| KDE‑3 | MED | `CompactRepresentation.qml:13` | icon path `../../icons/` one level too high → bundled icon never loads |
| KDE‑4 | MED | `ConfigGeneral.qml:12` | `saveConfigJson()` is a `console.log`-only no-op → KDE config never reaches `generate-icon.py` |
| KDE‑5 | LOW | `main.xml`, `metadata.json` | 4 config keys read in QML but undeclared; `X-Plasma-API-Minimum-Version 5.27` but Plasma‑6-only `PlasmoidItem` |
| DIFF‑1 | HIGH | `extension.js:594` | GNOME 46+ notify API (`getSystemSource` + object `Notification`) but `metadata.json` declares `"45"` → throws on 45, wedges `_updateDisplay` |
| DIFF‑2 | MED | `background.js:556` | `_last_scrape_ts` only written on success-with-meters → empty-meters return skips it → idle/auto debounce defeated when logged out |
| DIFF‑3 | MED | `background.js:645` | removing `tabs` perm defeats the TC‑1 `chrome-error://` guard (host_permissions doesn't cover that origin) |
| DIFF‑4 | MED | `generate-icon.py:78` | new `config.json` reader validates colours but not thresholds → non-int → `int >= str` TypeError → icon gen aborts |
| BASE‑1 | MED | `usage-server.py:393,411,416` | CM‑1 guard validates only root dict; corrupt nested `prev` (`_period_lengths`/`meters`) → crash → 400, no write → permanent loop |
| BASE‑2 | MED | `background.js:538` | a stale offline buffer flushes over newer server data (ordering-blind merge) → cache regresses to an older snapshot |
| BASE‑3 | LOW | `background.js:626` | created-tab id persisted after `tabs.create`; SW death in the gap orphans a background tab |
| BASE‑4 | LOW | `tooltip.py:41` + `extension.js` | min-only reset renders `0:90` (no 60-rollover); same in the GNOME `formatReset` twin |
| BASE‑5 | LOW | `generate-icon.py:118,140` | `hex_to_rgba` drops 8-digit alpha; `pacing_pct` rejects float pct while JS accepts it |
| BASE‑6 | LOW | `extension.js:516` + `scraper.js`/`background.js` | future `_timestamp` → negative age; `parseResetMinutes` hr/min branches uncapped |

**Deferred** (logged in TODO): KDE‑2's deeper "generate the QML from a shared
source" dedup — the parity lint below is the interim guard. **BASE‑5(c)** (dock
ring tracks the `all` meter while the panel honours the user-selected metric) is
left as a deliberate design choice — the dock icon is a fixed overview, the panel
is selectable — not a defect.

---

## Implementation

### 1. KDE‑1 — `main.qml` imports + cache path
- Add `import QtCore` (defines the `StandardPaths` singleton, Qt 6.2+).
- Rewrite `loadData()` to use `StandardPaths.GenericCacheLocation` (= `$XDG_CACHE_HOME` or `~/.cache`, **no** app-name suffix — matches where `usage-server.py` writes), normalise url-vs-path, drop the dead `const path`.

### 2. KDE‑2 — real schema fields
- `main.qml`: single `pacingFraction(meter)` mirroring `extension.js:pacingPct` exactly — `reset_minutes` + `usageData._period_lengths[label]` (minutes), floor `max(15, period*0.05)`. Collapse `pacingColor`/`popupPacingColor` into one `pacingColor(meter, cNormal, cWarn, cCrit)` helper (also fixes the duplication finding).
- `MeterRow.qml`: reset countdown from `meter.reset_minutes` (minutes), not `reset_ts`.
- `FullRepresentation.qml`: status from `_anthropic_status` (`.indicator`/`.claude_ai_component_status`); age from `_timestamp` (epoch-s).

### 3. KDE‑3 — icon path
- `CompactRepresentation.qml:13` `../../icons/claude-22.png` → `../icons/claude-22.png`.

### 4. KDE‑5 — config schema + min version
- `main.xml`: add `barWidth`(10), `panelFontSize`(11), `popupFontSize`(10), `panelIconSize`(16) — defaults matching the gschema.
- `ConfigGeneral.qml`: add a "Sizes" section (SpinBoxes) so they're user-settable.
- `metadata.json`: `X-Plasma-API-Minimum-Version` `5.27` → `6.0`.

### 5. KDE‑4 — write `config.json` for real
- `ConfigGeneral.qml`: `saveConfigJson()` writes `~/.config/claude-usage/config.json` via `Plasma5Support.DataSource{engine:"executable"}`, base64-piped (injection-safe) — matches the predecessor plan's intent (its line 77).

### 6. DIFF‑1 — GNOME 45 notify fallback
- `extension.js`: feature-detect `typeof MessageTray.getSystemSource === 'function'`; on older shells fall back to `Main.notify('Claude Usage', body)` (no action button, but no throw). Restores declared 45 support.

### 7. DIFF‑2 — debounce hole
- `background.js`: move the `_last_scrape_ts` write to right after the scrape executes (`const data = result?.result;`), **before** the empty-meters early return, so a persistently-failing scrape still debounces.

### 8. DIFF‑3 — error-page guard without `tabs`
- `background.js`: add a one-shot `chrome.webNavigation.onErrorOccurred` listener (frame 0, host `claude.ai`) inside the created-tab load-wait Promise that rejects on nav failure — independent of `tab.url` visibility.

### 9. DIFF‑4 — config threshold validation
- `generate-icon.py:load_config()`: coerce `threshold_warning`/`threshold_critical` to `int` in the `config.json` branch (mirroring the colour validation); fall back to defaults on bad values.

### 10. BASE‑1 — server corrupt-cache hardening
- `usage-server.py`: after the CM‑1 root-dict check, sanitise `prev`'s nested shapes — drop a non-dict `_period_lengths`, filter its entries to `{str:int}`, drop a non-list `meters`, filter to dict elements. Add a regression test.

### 11. KDE parity lint
- `scripts/lint-kde-parity.py`: (a) any `kde-plasmoid` QML referencing `StandardPaths` must `import QtCore`; (b) `meter.<field>` / `usageData.<field>` reads must be in the known `usage.json` allowlist; (c) `main.xml` colour/threshold defaults must equal the gschema. Wire into `Taskfile` `test`.

### 12. BASE‑2 — offline buffer supersede
- `background.js`: drop the offline buffer (`claude_usage`) on a successful full-scrape post, so a later `fetchUsage` flush can't re-post a now-stale buffer over newer cache data (the server merge is ordering-blind). Also makes the flush's non-atomic `remove()` harmless. Chosen over a server-side `_timestamp`-monotonic guard, which would false-reject legitimately-newer data under client clock skew. Runtime test in `chrome-extension/test/background-runtime.test.js` (vm sandbox + stateful storage + stubbed server).

### 13–16. Deferred lows (BASE‑3..6)
- **BASE‑3** `background.js`: persist a `_scrape_tab_pending` marker before `tabs.create`; the orphan sweep closes background scrape tabs by URL only when that marker is stale (`active:false`-guarded, so a tab the user is viewing is never touched). Runtime test asserts it closes the orphan and that no pending marker means no URL-sweep.
- **BASE‑4** `tooltip.py::parse_reset` + `extension.js::formatReset`: normalise total minutes so a min-only / hr-min reset rolls over (`90 min` → `1:30`), consistently across both twins.
- **BASE‑5** `generate-icon.py`: `hex_to_rgba` honours an 8-digit `#RRGGBBAA` alpha; `pacing_pct` accepts float pct (matching `extension.js`'s `typeof number`). 5(c) left as a design choice.
- **BASE‑6** `extension.js` clamps age ≥ 0 (future `_timestamp`); `scraper.js` + `background.js` cap `parseResetMinutes` hr/min branches at 31 days (the server's `reset_minutes` bound).

### 17. KDE‑2 — pacing/URL parity (deep dedup)
- The plasmoid's QML re-implements the pacing curve and hardcodes the usage URL — a third copy after `extension.js` and `generate-icon.py`. Logic can't be shared across the JS/Python/QML runtimes, so the project's mechanism is a parity lint (the `pacingPct`↔`pacing_pct` twins are hand-synced + `lint-pacing-parity`-checked, not generated). `scripts/lint-kde-parity.py` gains two checks bringing the QML copy under the same guard: **(4)** `main.qml::pacingFraction`'s floor `Math.max(15, period*0.05)` must match `extension.js::pacingPct`; **(5)** the QML usage URL must equal `USAGE_URL`. Config defaults + fields were already covered (checks 2–3), so all four surfaces the dedup targeted (pacing/threshold/label/URL) are now drift-guarded. **No QML runtime change.** Full code-generation of a shared QML constants module was considered and rejected: it adds an unverifiable QML import path to a widget with no live CI, for no more protection than the lint already gives.

---

## Critical files

| File | Action |
|------|--------|
| `kde-plasmoid/contents/ui/main.qml` | import QtCore; rewrite loadData; dedupe pacing on real fields |
| `kde-plasmoid/contents/ui/MeterRow.qml` | reset countdown from reset_minutes |
| `kde-plasmoid/contents/ui/FullRepresentation.qml` | _anthropic_status / _timestamp |
| `kde-plasmoid/contents/ui/CompactRepresentation.qml` | icon path `../icons/` |
| `kde-plasmoid/contents/config/main.xml` | add barWidth/panelFontSize/popupFontSize/panelIconSize |
| `kde-plasmoid/contents/ui/config/ConfigGeneral.qml` | real config.json write; Sizes section |
| `kde-plasmoid/metadata.json` | min API 6.0 |
| `gnome-extension/extension.js` | GNOME-45 notify feature-detect |
| `chrome-extension/background.js` | _last_scrape_ts move; webNavigation error guard |
| `server/generate-icon.py` | threshold validation in config.json branch |
| `server/usage-server.py` | sanitise prev nested shapes |
| `server/tests/test_validate.py` | corrupt-cache regression test |
| `scripts/lint-kde-parity.py` | new lint |
| `Taskfile.yml` | wire lint-kde-parity into `test` |

---

## Verification

> Static/automated only — a live Plasma session and a live Chrome profile are
> not available on this (GNOME) box. Steps needing live KDE/Chrome are marked
> **[live]** and deferred to target hardware; everything else runs here.

1. **KDE‑1 import present:** `grep -L 'import QtCore' kde-plasmoid/contents/ui/main.qml` returns nothing (file has the import).

   ```
   >>> PASS: import present
   ```
   **PASS**

2. **KDE‑2 no phantom fields:** `grep -REn 'reset_ts|period_secs|usageData\.status|last_update' kde-plasmoid/` returns nothing.

   ```
   >>> PASS: none found
   ```
   **PASS** (also caught `popupPacingColor` leftover — none).

3. **KDE parity lint passes:** `python3 scripts/lint-kde-parity.py` → exit 0, reports import + field + default parity OK.

   ```
   lint-kde-parity: OK (6 QML files clean, 18 config keys match the gschema)
   exit=0
   ```
   Negative test — a planted bad QML (StandardPaths w/o import + `meter.reset_ts` + `usageData.last_update`) is rejected:
   ```
   lint-kde-parity: …: uses StandardPaths but imports neither QtCore nor Qt.labs.platform …
   lint-kde-parity: …:5: meter.reset_ts is not a known usage.json field …
   lint-kde-parity: …:5: usageData.last_update is not a known usage.json field …
   lint-kde-parity: FAIL (3 issue(s))   exit=1
   ```
   **PASS** (guards KDE‑1/2/5; fails on regression).

4. **KDE‑3 icon path resolves:** the path in `CompactRepresentation.qml` resolves to an existing file (`contents/icons/claude-22.png`).

   ```
   >>> PASS: ../icons/ + file exists
   ```
   **PASS**

5. **GNOME extension syntax + lint:** `task lint-gnome` passes; `extension.js` has the `getSystemSource` feature-detect.

   ```
   lint-gnome: syntax OK
   lint-gnome: PRESENT  getSystemSource / isTransient / addAction(label, callback) / launch_default_for_uri
   lint-gnome: all API symbols verified
   ```
   **PASS** (note: `lint-gnome` checks the *dev box's* libshell — the 46+ symbols are present here; the GNOME‑45 fallback is feature-detected at runtime, step 11).

6. **Chrome JS syntax:** `node --check chrome-extension/background.js && node --check gnome-extension/extension.js` → OK.

   ```
   background.js OK
   extension.js OK
   ```
   **PASS** (background.js load-time invariants test also green — see step 9).

7. **DIFF‑4 threshold validation:** a `config.json` with `"threshold_critical":"high"` no longer crashes `ring_color` (repro returns default, prints a warning).

   ```
   warning: invalid 'threshold_warning' in config.json, using default
   warning: invalid 'threshold_critical' in config.json, using default
   coerced thresholds: 70 90
   ring_color(95) => (1.0, 0.349…, 0.2, 1.0) (no TypeError = PASS)
   ```
   **PASS**

8. **BASE‑1 corrupt cache no longer loops:** the merge-step repro with a non-dict `_period_lengths` / non-list `meters` returns OK (sanitised), not a crash.

   ```
   server/tests/test_validate.py::test_corrupt_nested_prev_does_not_400_loop  1 passed in 0.05s
   ```
   **PASS** (5 corruption shapes; each POST now writes a clean cache instead of 400-looping).

9. **Full suite green:** `task test` → all unit tests + parity/security lints pass.

   ```
   # tests 57 / # pass 57 / # fail 0        (test-scraper: scraper + load-smoke + runtime; incl. lows)
   104 passed in 0.07s                      (test-validate: server pytest, 98 → +BASE-1/4/5)
   lint-scraper-parity / lint-anchor-strings / lint-pacing-parity ×4 / lint-pair-inventory: OK
   lint-security-doc: OK   lint-js-defaults: in sync   lint-kde-parity: OK   lint-gnome: verified
   task test: ALL PASS (exit 0)
   ```
   **PASS**

10. **[live] KDE plasmoid — Plasma 6 manual checklist.** Static lint now covers the import / field / default / pacing / URL drift classes (steps 1–4 + 14); what remains needs a running Plasma 6 session. On a Plasma 6 box with the Chrome extension + local server already populating `~/.cache/claude-usage/usage.json`:
    1. `task kde-install` (or install the .deb) → `~/.local/share/plasma/plasmoids/org.indri.claude-usage/` exists.
    2. Add the "Claude Usage" widget to a panel; `journalctl --user -f` shows **no** QML errors (especially no `StandardPaths is not defined`, no `PlasmoidItem is not a type`).
    3. Compact panel shows the live `%` in the pacing colour; the bundled icon renders (not the "C" text fallback).
    4. Popup shows meter rows with bars + "resets in …" countdowns, the "Updated Xm ago" age line, and "⚠ Anthropic service degraded" during an outage.
    5. Scroll the panel label → cycles meters; the choice persists (`panelMetric`).
    6. Config dialog → change a popup colour / threshold / font / dock-ring colour → values persist (KConfig) and `~/.config/claude-usage/config.json` is written; re-run `generate-icon.py` → dock icon reflects the dock-ring colours.
    7. `XDG_CACHE_HOME` set to a non-default dir → the plasmoid still finds `usage.json` (GenericCacheLocation).

    ```
    DEFERRED — no Plasma 6 session on this (GNOME 49/50) box.
    ```
    **DEFERRED** → TODO `[verify] [live]`.

11. **[live] GNOME 45:** on a GNOME-45 shell, force `tier=broken`; notification fires (no action button) with no `_updateDisplay` throw.

    ```
    DEFERRED — dev box is GNOME 49/50.
    ```
    **DEFERRED** → TODO `[verify] [live]`. Feature-detect logic verified by reading; runtime throw-path needs a real GNOME-45 shell.

12. **BASE‑2 buffer supersede:** `node --test …/background-runtime.test.js` — buffer cleared on successful post, retained on failure; fails with the fix reverted.

    ```
    ok 1 - clears a stale offline buffer after a successful full-scrape post
    ok 2 - writes the offline buffer when the post fails
    # tests 2 / # pass 2 / # fail 0
    --- negative (fix disabled): not ok 1 … / # fail 1
    ```
    **PASS** (real regression guard — bites when the fix is removed).

13. **Deferred lows (BASE‑3..6):** new tests pass; suite stays green.

    ```
    # tests 57 / # pass 57 / # fail 0   (scraper 52 + load 1 + runtime 4: BASE-2×2 + BASE-3×2)
    104 passed                          (server: +2 tooltip rollover, +2 hex-alpha, +1 pacing-float)
    BASE-3 negative (sweep guard disabled): # fail 1 — orphan test bites
    lint-scraper-parity: OK (regexes unchanged; scraper↔background cap kept in sync)
    task test: ALL PASS (exit 0)
    ```
    **PASS** — BASE‑3 pending-marker orphan recovery, BASE‑4 minute rollover (both twins), BASE‑5 float-pct + 8-digit alpha, BASE‑6 age clamp + reset cap.

14. **KDE‑2 pacing/URL parity:** `python3 scripts/lint-kde-parity.py` passes; both negative tests bite (exact in-memory restore, QML unchanged after).

    ```
    lint-kde-parity: OK (6 QML files clean, 18 config keys + pacing floor + usage URL mirror the canonical source)
    pacing-drift (15→20): exit 1 — "pacing floor drift: main.qml (20, 0.05) != extension.js pacingPct (15, 0.05)"
    url-drift (usage→usage2): exit 1 — "usage URL …/usage2 != … USAGE_URL …/usage"
    git diff --stat kde-plasmoid/ → empty (restored exactly)
    ```
    **PASS** — QML pacing floor + usage URL now drift-guarded against `extension.js`.

---

## Test coverage & gaps (review)

A review of the testing strategy after these fixes — what's in place and what's still open.

**In place:**
- **Unit:** 104 server (pytest) + 57 scraper/SW (node).
- **Parity lints (`task test`):** scraper↔background, JS↔gschema, security-doc, and `lint-kde-parity` (5 checks: StandardPaths-import, usage.json fields, main.xml↔gschema defaults, pacing floor, usage URL) — each negative-tested.
- **CI (`release.yml`):** `task test` → build .deb → static `test-deb` on Ubuntu 24.04 + 25.10 → live **server** smoke (`test-deb-live.sh`: starts the service, POSTs a probe, verifies the cache write).

**Gaps (ranked) — recommended testing follow-ups, not part of this fix pass:**
1. **Static QML validation via `qmllint` (HIGH).** Nothing parses the QML, which is why KDE‑1 shipped. `qmllint` is **headless** (no Plasma shell) and flags the unresolved-`StandardPaths` / syntax / `PlasmoidItem`-on-Plasma‑5 class directly — the *easy* gate the earlier "future `test-kde` needs a running shell" note wrongly conflated with the *hard* render smoke. Recommend a `task lint-qml` in `task test` (needs the `org.kde.plasma.*` QML modules installed, or those imports allowlisted). It also covers `lint-kde-parity`'s regex blind spots (e.g. a phantom field read via a differently-named variable: `const m = currentMeter(); m.reset_ts`).
2. **Missing regression tests (HIGH).** Of this pass's fixes, **DIFF‑1** (GNOME‑45 notify fallback), **DIFF‑3** (webNavigation error guard), **DIFF‑4** (config.json threshold validation) and **BASE‑6a** (age clamp) have no committed test; **DIFF‑2** (empty-meters debounce) is only indirect (the runtime test asserts `_last_scrape_ts` on a *successful* scrape, not the empty path that was the fix). The `background-runtime.test.js` harness + the DIFF‑4 repro make most cheap to add.
3. **GNOME 45 (declared min) untested (MED).** `lint-gnome` checks the dev's libshell (49/50); `test-gnome` defaults to 26.04 and isn't in CI; `gnome-version-check` only watches for *newer* versions. DIFF‑1 lived exactly here — add a GNOME‑45 image to `test-gnome` (in CI), or drop `"45"` from `shell-version`.
4. **`test-gnome` not in CI (MED).** The release pipeline smoke-tests the *server* but never loads the GNOME extension or the plasmoid; an extension-load regression ships unless a human runs `task test-gnome`.
5. **`test-deb` doesn't verify KDE files (LOW).** `build-deb.sh` ships the plasmoid to `/usr/share/plasma/plasmoids/`; `test-deb-verify.sh` only checks the GNOME files.

**Live (manual, Plasma 6):** the verification step‑10 checklist is the only render/behaviour check; tracked as the `[verify] [live]` TODO. The more that moves into `qmllint` (gap 1), the less rides on it.
