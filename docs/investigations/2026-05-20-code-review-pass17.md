# Code Review — Pass 17 (post-0.11.19, full-codebase + recent-changes sweep)

**Date:** 2026-05-20
**Reviewer:** Claude Opus 4.7 (max effort), four parallel agents — recent-commits sweep, server Python, GNOME extension JS, Chrome extension + packaging + CI
**HEAD:** `2283398` (after the docs-image regen + multi-size icon + pacing-viz prototype work that landed today)
**Scope:** Full codebase. Pass-16 closed 10 of 10 findings in 0.11.17–0.11.18. The pacing-threshold schema widen shipped as 0.11.19. Since then: multi-size icon emission, gtk-update-icon-cache auto-refresh, pacing-viz prototype in `popup-preview.py`, lint-parity extension for the pacing-function pair, and five `render-*.py` doc-image scripts. This pass re-reads the whole codebase with fresh eyes — biased toward (a) the day's churn, (b) drift surfaces that pass-16 catalogued but didn't enumerate exhaustively (schema↔code↔docs↔diagnostic), (c) the loopback-IPC trust model (never explicitly reviewed).
**Prior work:** [pass-16](2026-05-19-code-review-pass16.md), [pass-15](2026-05-19-code-review-pass15.md), [docs/wont-fix.md](../wont-fix.md), [pacing-viz plan](../plans/2026-05-20-pacing-viz-tick-overpace.md)

---

## 1. Executive Summary

Three High-severity findings, twelve Medium, fifteen Low, four Info.

| Sev | # | ID | Title | New? |
|-----|---|----|-------|------|
| **High** | 1 | **PR‑1** | Prefs spinner upper bound stuck at `99` after `0.11.19` widened the schema range to `500`. Every user who opens preferences silently can't set the pacing thresholds the schema now allows — the very thing 0.11.19 was supposed to enable. | ✓ |
| **High** | 2 | **L‑1** | Flash-timeout callback writes `_label.opacity` without checking `_destroyed`. Every other long-lived async source in `extension.js` guards on the flag; this is the lone exception, and the state that triggers it (crit-pacing flash → user investigates → disables extension) is exactly the scenario. | ✓ |
| **High** | 3 | **DG‑1** | `generate-icon.py:62-69` `DEFAULTS` advertises `threshold_warning=50 / threshold_critical=80` while the gschema ships `70 / 90`. Comment at line 62 promises sync. Active when GIO is unavailable (non-GNOME envs) or schema unregistered (pre-install). | ✓ |
| Medium | 4 | **CI‑1** | `task lint-scraper-parity` exists but CI runs `task test-scraper` + `task test-validate` *individually*, not `task test` (which would include the lint). The whole point of pass-16's parity-lint extension is invalidated. | ✓ |
| Medium | 5 | **CM‑1** | `usage-server.py:321` catches `json.loads` failure, but the type check `prev = {k: v for k, v in prev.items() ...}` lives outside the try. A non-dict JSON cache (list, scalar) crashes every subsequent POST. | ✓ |
| Medium | 6 | **M‑1** | `_atomic_write_multisize` is per-size atomic but not transactional. Mid-loop failure leaves dock with split-vintage icons until next successful run. | ✓ |
| Medium | 7 | **LC‑1** | `_getPrimary`'s deferred `GLib.idle_add` source isn't stored; `destroy()` can't cancel it. Every other GLib source in the file is tracked. Slow leak across disable→enable cycles. | ✓ |
| Medium | 8 | **S‑1** | Scroll handler returns `EVENT_STOP` when `eligible.length < 2`, even though it did nothing. Asymmetric with the smooth-scroll EVENT_PROPAGATE path, and breaks future composability. | ✓ |
| Medium | 9 | **LK‑1** | Pass-16's `_strip_comments` extension to Python `#` regex is context-blind. Will eat hex-color string literals (`'#abc123' # comment` → `'`). Latent today; fragile to any future move of color logic into the comparison range. | ✓ |
| Medium | 10 | **I‑1** | `install.sh --uninstall` only `rm -f`s `64x64` and `128x128`. After multi-size landed (da6a2ac), the script orphans 48/96/256. MANUAL.md's glob (`*/apps/claude-usage.png`) is correct; the script wasn't updated. | ✓ |
| Medium | 11 | **PP‑1** | `scripts/popup-preview.py:28` hardcodes `REPO = Path('/home/will/SRC/claude-usage')`. Every other script uses `Path(__file__).resolve().parent.parent`. Un-runnable for any contributor on a different checkout. | ✓ |
| Medium | 12 | **T‑1** | Zero unit-test coverage for `derive_tier`, `format_tooltip`, `parse_reset`, `ring_color`. Passes 14–16 fixed real bugs (TS-1, D-1, WP-1, V-3, AS-1) in these, and there's no regression net. | ✓ |
| Medium | 13 | **IPC‑1** | Loopback discovery handshake (`/hello` + `X-Claude-Usage-Server`) is a signature, not authentication. Any same-user process can spoof. Honest documentation needed at minimum; UNIX-socket migration ideal. | ✓ |
| Medium | 14 | **L‑2** | `scraper.js` hard-codes English string anchors (`'Plan usage limits'`, `'Additional features'`, `'Extra usage'`, `'Current balance'`). Translated claude.ai page → empty `meters` → permanent BROKEN tier with no signal. | ✓ |
| Medium | 15 | **AS‑1** | Statuspage `description` (free-form, often > 128 chars) is POSTed verbatim; `MAX_STR_LEN=128` validator rejects → 422 → cache never updates → BROKEN tier during the exact outage the field was meant to surface. | ✓ |
| Medium | 16 | **O‑1** | Chrome extension has no observable error state (no badge, no popup, no title rewrite). `console.warn` in DevTools is the only signal. Worsens every other silent-failure mode. | ✓ |
| Low | 17 | **DR‑1** | `threshold-warning > threshold-critical` is permitted by the schema. Color tiers silently invert. | ✓ |
| Low | 18 | **DR‑2** | `popup-preview.py:97-99` GSettings-fail fallback hard-codes `#cccccc` for `popupNorm`/`panelNorm`; schema defaults are `#2a9a2a`/`#ffffff`. | ✓ |
| Low | 19 | **DR‑3** | `popup-preview.py:107` docstring points at `extension.js:458`; actual filter is at line 472. | ✓ |
| Low | 20 | **DR‑4** | `render-panel-screenshot.py:31` re-declares `PANEL_WARN_COLOR = '#d07000'` with "schema default" comment; drifts if schema changes. Same pattern: needs a schema-parse helper. | ✓ |
| Low | 21 | **L‑3** | `_loadData` calls `f.load_contents_async(null, ...)` — `null` cancellable. GIO completes the I/O after `destroy()`; callback no-ops, but the work runs. | ✓ |
| Low | 22 | **L‑4** | `prefs.js` spinner `value-changed` flushes to GSettings every step. Click-and-hold issues 10+ `set_uint` per second, each fires a synchronous `_updateDisplay` in the main process. No debounce on the write itself. | ✓ |
| Low | 23 | **L‑5** | `prefs.js:38` `_regenTimer` is module-scope. State that belongs to a single prefs session persists across window close/reopen. | ✓ |
| Low | 24 | **L‑6** | Tooltip-flash timeout's `_stopFlash` writes `this._label.opacity = 255` without `_destroyed` guard (sibling to L-1). | ✓ |
| Low | 25 | **MS‑1** | `_atomic_write_multisize` tmp leaks on `BaseException` (SIGINT, SIGTERM-then-cleanup-raise). Each crash leaks 5 hidden tmps under `~/.local/share/icons/hicolor/*x*/apps/`. `_sweep_orphan_tmps` in `usage-server.py` only globs `applications/`, not icon-theme dirs. | ✓ |
| Low | 26 | **MS‑2** | `_refresh_user_icon_cache` rebuilds only when `new_dir OR not cache.exists()`. A corrupt/zero-byte cache file persists indefinitely. Bare `try/except` also silences timeout-expired (10 s default) without log. | ✓ |
| Low | 27 | **V‑1** | `usage-server.py:91` whitelists `_buffered_at` as a top-level key but `_validate` never bounds it. Inconsistent with siblings (`_timestamp` etc.). | ✓ |
| Low | 28 | **V‑2** | `meters` list has no length cap. `_period_lengths` is capped at 100. Asymmetric. | ✓ |
| Low | 29 | **V‑3** | Validator's `allow_empty=True` on `_anthropic_status.indicator/description/claude_ai_component_status` lets empty strings flow through; `derive_tier` treats empty `indicator` as not-`'none'` → broken-tier trigger. | ✓ |
| Low | 30 | **D‑1** | `tooltip.update_desktop` silently drops `Name=` or `Icon=` if the .desktop already lacked them. Tooltip disappears with no diagnostic. | ✓ |
| Low | 31 | **DG‑2** | `load_config` `except Exception: return dict(DEFAULTS)` silently swallows GIO/schema errors. User edits in dconf-editor + broken schema → invisible no-op. | ✓ |
| Low | 32 | **DR‑5** | `popup-preview.py` writes `/tmp/claude-usage-popup-preview.html` — predictable filename, no `O_NOFOLLOW`, no per-PID suffix. Symlink-clobber surface on multi-user/CI hosts. | ✓ |
| Low | 33 | **N‑1** | CI workflow has no `actions/setup-node` step. Node version drifts with the GH-runner image refresh. `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` only affects Action runtime, not user shell. | ✓ |
| Low | 34 | **P‑1** | `cp -r chrome-extension` + `rm -rf chrome-extension/test` (both `install.sh` and `build-deb.sh`) creates a window where the test dir is at the destination. Replace with `rsync --exclude=test/`. | ✓ |
| Low | 35 | **P‑2** | Three-place version triple, two-place automation. `task release` enforces parity but doesn't *set*. `task bump VERSION=…` would write all three. Auto-memory codifies the manual discipline — a smell. | ✓ |
| Info | 36 | **L‑7** | `panel-color-*` and `popup-color-*` strings inserted into `St.set_style` without sanitization. `popup-font-family` *is* regex-validated. CSS injection via `gsettings set ...` is self-inflicted; asymmetric defense regardless. | ✓ |
| Info | 37 | **L‑8** | `anyCrit` scans unfiltered `d.meters`; popup uses `visibleMeters`. Today the Sonnet-0% filter makes them functionally equivalent (because `pacingPct` short-circuits on `pct === 0`), but the divergence is invisible-by-luck. | ✓ |
| Info | 38 | **L‑9** | `_clearingMetric` reset must precede `set_string('')` inside the idle to avoid lockup. Comment doesn't say so. Re-ordering on a future edit would silently brick the orphan-recovery path. | ✓ |
| Info | 39 | **CI‑2** | `chrome.alarms` does NOT fire missed periods on wake — one fetch per resume. Laptop sleep > 20 min produces BROKEN tier on resume until first post-wake fetch. `chrome.idle.onStateChanged` would fix it. | ✓ |

**Bottom line:** No critical or security-on-fire finding. **PR‑1** is the most important — the prefs UI invalidates the 0.11.19 schema widen for every user who opens preferences. **L‑1** is the most subtle: a tear-down race that's exactly bound to the user state most likely to trigger investigation. **CI‑1** and **T‑1** are the regression-prevention gap that lets the others recur.

Two cross-cutting themes thread through the findings list:

1. **Drift surfaces are everywhere** (DG-1, CI-1, I-1, PP-1, DR-1 through DR-5, P-2). The codebase has eleven moving parts that must stay synchronized — gschema defaults, gschema ranges, prefs.js spinner ranges, `extension.js` fallback constants, `generate-icon.py` `DEFAULTS` dict, `popup-preview.py` fallback dict, `_doc_render.py` `production_meter_row` constants, `render-*.py` hardcoded colors, MANUAL.md prose, `claude-usage-status` thresholds, `install.sh` uninstall paths. Pass-16 fixed *some* drift; new ones land every release. The structural fix is a single-source-of-truth helper that parses `gschema.xml` and exposes the values to both Python and JS — until that lands, drift will keep being discovered.

2. **Silent failure is the dominant failure mode** (CM-1, M-1, MS-1, MS-2, DG-2, D-1, O-1, V-3, L-2). The extension and server both prefer "return null / fall back to defaults / log to a stream nobody reads" over surfacing problems. The grey panel says "something's wrong" without saying what; `claude-usage-status` is the only diagnostic, but it sees only server state — the Chrome ext's view is invisible. **O-1** (no toolbar badge / no popup) is the lever that would multiply the value of every other observability improvement.

---

## 2. High-Severity Findings

### 2.1 PR‑1 — Prefs spinner stuck at 99 after schema widened to 500

**Files:** `gnome-extension/prefs.js:114,116`; `gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml:36,41`

The schema range was widened to `1..500` in commit `654ec63` (*"widen threshold-warning/critical range 99 → 500; bump 0.11.19"*) precisely because pacing percentages routinely exceed 100% early in a period. The `addSpinRow` calls in `prefs.js` were not updated:

```js
prefs.js:114: addSpinRow(g2, 'Warning threshold',  '… (must be below Critical)', 1, 99, true);
prefs.js:116: addSpinRow(g2, 'Critical threshold', '… (must exceed Warning)',    1, 99, true);
```

vs.

```xml
gschema.xml:33-42:
<key name="threshold-warning"  type="u"> <default>70</default> <range min="1" max="500"/>
<key name="threshold-critical" type="u"> <default>90</default> <range min="1" max="500"/>
```

The UI silently caps at 99. The user who wants to set `threshold-critical=150` (as the maintainer did earlier this session — see auto-memory and commit history for the `gsettings set` workaround) cannot do it through the official surface. They must drop to `gsettings set` from a terminal. **The 0.11.19 release is, in practice, inert from the prefs UI.**

**Fix:** Change both `addSpinRow` calls to pass `upper=500`. Better: derive the upper bound from `settings.get_default_value('threshold-warning')`-style schema introspection so the constant lives in exactly one place. The relational guard at `prefs.js:117-124` (warning < critical) still works at the new range. While there, the subtitle should mention this is *pacing %* not %; pacing is uncapped while raw pct caps at 100.

**Regression guard:** Schema-parse lint that parses `gschema.xml` and asserts every `<range>` matches every `addSpinRow` upper bound. Same machinery would catch DG-1 and DR-2/DR-4.

---

### 2.2 L‑1 — Flash timeout writes `_label.opacity` without `_destroyed` guard

**Files:** `gnome-extension/extension.js:503-507`; `_stopFlash` at line 516

Every long-lived async source in `extension.js` checks `this._destroyed` before touching widgets — `_loadData` callback (line 297), `_retryId` (line 281), `_scrollTimer` (line 174), `_getPrimary` idle (line 543). The flash timeout is the lone exception:

```js
this._flashId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
    this._label.opacity = vis ? 255 : 30;   // ← no _destroyed check
    vis = !vis;
    return GLib.SOURCE_CONTINUE;
});
```

`destroy()` sets `_destroyed = true` then calls `GLib.source_remove(this._flashId)` — but if a tick has already been dispatched to the main loop between `source_remove` resolving and `super.destroy()` actually disposing `_label`, the callback fires against a disposed `St.Label`. Window is microseconds, but exists exactly when the user is most likely to be poking at the extension: critical-pacing flash drew their attention → they open the menu → click "Disable".

`_stopFlash` has the same flaw on line ~516 (`this._label.opacity = 255` without guard).

**Fix:** Mirror the pattern used everywhere else in the file:

```js
this._flashId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
    if (this._destroyed) return GLib.SOURCE_REMOVE;
    this._label.opacity = vis ? 255 : 30;
    vis = !vis;
    return GLib.SOURCE_CONTINUE;
});
```

And wrap `_stopFlash`'s opacity write in `if (!this._destroyed) { ... }`.

**Regression guard:** A grep-lint that flags every `this._<widget>.<method>(` inside a `GLib.timeout_add` / `GLib.idle_add` callback that doesn't have a preceding `_destroyed` check. Cheap, catches the entire class.

---

### 2.3 DG‑1 — `generate-icon.py` DEFAULTS thresholds diverge from gschema

**Files:** `server/generate-icon.py:62-69`; `gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml:33-42`

```python
# server/generate-icon.py:62-69
DEFAULTS = {  # keep in sync with gschema.xml default= attributes
    ...
    'threshold_warning':  50,   # schema: 70
    'threshold_critical': 80,   # schema: 90
}
```

The comment claims sync; the values don't match. `load_config()` returns `dict(DEFAULTS)` on any `Gio.Settings.new(...)` failure — the path that runs whenever:

- The extension hasn't been installed yet (between `apt install claude-usage` and first GNOME session)
- Schema is registered but `gi.repository` is unavailable (non-GNOME env, fresh container)
- Schema lookup raises for any reason (corrupted dconf, locked-out gsettings)

In that window the dock icon flips amber at 50% and red at 80%, while the panel label flips at 70% and 90% (it reads gschema directly through the extension). **Icon and label disagree on tier color.**

Also reused by `scripts/render-dock-icon-screenshot.py:33` (`dict(g.DEFAULTS)`) and `scripts/render-tooltip-screenshot.py:56` — the docs PNGs exercise the wrong thresholds too.

**Fix:** Update `DEFAULTS` to `'threshold_warning': 70, 'threshold_critical': 90`. The comment claim becomes truthful. Verify by re-running `render-dock-icon-screenshot.py` and `render-tooltip-screenshot.py` — the existing 20%/10% mockup values are below both thresholds either way, so the docs PNGs won't visibly change.

**Regression guard:** `scripts/lint-defaults-parity.py` that parses the gschema XML and asserts every `DEFAULTS` value matches every `<default>` in the schema. Same machinery would catch PR-1 and DR-2/DR-4.

---

## 3. Medium-Severity Findings

### 3.1 CI‑1 — CI runs individual tasks, not the aggregate (lint never runs in CI)

**Files:** `.github/workflows/release.yml:40,46`; `Taskfile.yml` (`test` aggregator)

CI invokes `task test-scraper` and `task test-validate` separately. `task test` is the aggregator that ALSO runs `lint-scraper-parity`. The parity lint (commits 262ef30 + the SC-3 baseline) is the only protection against a numeric-constant or regex drift between `extension.js`/`generate-icon.py` and `scraper.js`/`background.js`. **With no CI guard, it's documentation, not enforcement.**

**Fix:** Replace the two CI step lines with a single `run: task test`. Or add `run: task lint-scraper-parity` as an extra step.

### 3.2 CM‑1 — Non-dict cache JSON crashes every subsequent POST

**Files:** `server/usage-server.py:321-335`

```python
try:
    prev = json.loads(OUTPUT.read_text())
except Exception: pass
...
prev = {k: v for k, v in prev.items() if k in _VALID_TOP_KEYS}  # ← outside try
```

If `usage.json` legitimately contains `[]`, `null`, a string, or a number (corruption, partial write, future schema change), `json.loads` succeeds but `prev.items()` raises `AttributeError`. The outer handler returns 400 → every subsequent POST repeats the same error → user must manually `rm ~/.cache/claude-usage/usage.json`.

**Fix:** Add a type-guard inside the try:

```python
try:
    prev = json.loads(OUTPUT.read_text())
    if not isinstance(prev, dict):
        print(f"warning: cache at {OUTPUT} is not a JSON object; resetting",
              file=sys.stderr, flush=True)
        prev = {}
except Exception:
    pass
```

### 3.3 M‑1 — `_atomic_write_multisize` not transactional across sizes

**Files:** `server/generate-icon.py:254-278`

Each per-size write is `(tmp.save → tmp.replace(dest))` and individually atomic. The loop is not. If size 48 succeeds and size 64 fails (PIL save raises, disk full, EPERM after a chmod), the dock now has new 48 but old 64/96/128/256 — the panel and dock pick different sizes and show different vintages of the icon.

**Fix:** Two-phase commit. Phase 1 saves all tmps (the expensive PIL resize); phase 2 calls `.replace()` for each, back-to-back. The window where consumers see a partial state shrinks from "PIL save + rename" (~hundreds of ms) to "5 renames" (~µs).

```python
def _atomic_write_multisize(img, sizes=ICON_SIZES):
    new_dir = False
    staged = []
    for size in sizes:
        dest = icon_path_for(size)
        new_dir = new_dir or not dest.parent.exists()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f'.claude-usage.tmp.{os.getpid()}.{time.time_ns()}.{size}.png')
        img.resize((size, size), RESAMPLE).save(tmp)  # all tmps written first
        staged.append((tmp, dest))
    try:
        for tmp, dest in staged:
            tmp.replace(dest)
    except Exception:
        for tmp, _ in staged:
            try: tmp.unlink()
            except OSError: pass
        raise
    if new_dir or not (THEME_DIR / 'icon-theme.cache').exists():
        _refresh_user_icon_cache()
```

### 3.4 LC‑1 — `_getPrimary` idle source not stored

**Files:** `gnome-extension/extension.js:542-547`

`destroy()` cleans up `_tickId`, `_flashId`, `_retryId`, `_scrollTimer`, file monitor, GSettings handler. The idle from `_getPrimary` is the lone unmanaged source. The callback does check `_destroyed`, so widgets are safe — but the GLib source holds a closure ref to the dead indicator until idle runs. Disable→enable cycles during development each queue one.

**Fix:** Store the source ID; remove in `destroy()`:

```js
this._clearMetricIdleId = GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
    this._clearMetricIdleId = null;
    if (this._destroyed) return GLib.SOURCE_REMOVE;
    this._clearingMetric = false;
    this._settings.set_string('panel-metric', '');
    return GLib.SOURCE_REMOVE;
});
```

### 3.5 S‑1 — Scroll EVENT_STOP for nothing-to-do case

**Files:** `gnome-extension/extension.js:164`

`if (eligible.length < 2) return Clutter.EVENT_STOP;` swallows the scroll event without doing anything. Other panel items (window list, workspace indicator) may use scroll, and future Shell versions may add scroll semantics to panel buttons. The default for "I didn't handle this" should be `EVENT_PROPAGATE`.

**Fix:** Change to `return Clutter.EVENT_PROPAGATE;`. Symmetric with the smooth-scroll branch at line 161.

### 3.6 LK‑1 — Lint Python `#` regex eats hex strings

**Files:** `scripts/lint-scraper-parity.py:51`

```python
text = re.sub(r'#[^\n]*', '', text)
```

`re.sub` doesn't know about string-literal context. Any `'#abc123'` inside a function being extracted becomes `'`. The docstring says *"crude — assumes neither appears inside a string literal in our codebase (true today)"* — `pacing_pct` has no hex strings today, so latent. Will silently misfire when color logic moves into a function the lint extracts.

**Fix:** Tokenize-aware stripping. Minimal patch for Python: use `tokenize.tokenize` and emit only non-`COMMENT` tokens. For JS the existing heuristics suffice; document the asymmetry.

### 3.7 I‑1 — `install.sh --uninstall` doesn't clean all five icon sizes

**Files:** `install.sh:47-50`

```bash
rm -f "$XDG_DATA_HOME/icons/hicolor/64x64/apps/claude-usage.png"
rm -f "$XDG_DATA_HOME/icons/hicolor/128x128/apps/claude-usage.png"
```

After `da6a2ac` (multi-size emission, ICON_SIZES = 48/64/96/128/256), `generate-icon.py` writes five hicolor sizes. `install.sh --uninstall` only removes two. MANUAL.md already has the correct glob (`*/apps/claude-usage.png`) — the script wasn't updated.

**Fix:** Replace with `rm -f "$XDG_DATA_HOME"/icons/hicolor/*/apps/claude-usage.png`. Also `rm -f "$XDG_DATA_HOME/icons/hicolor/icon-theme.cache"` to mirror the README. Pull `ICON_SIZES` from the Python via `python3 -c "import sys; sys.path.insert(0,'server'); from … import ICON_SIZES; print(' '.join(map(str,ICON_SIZES)))"` if you want a single source.

### 3.8 PP‑1 — `popup-preview.py` hardcodes maintainer's home

**Files:** `scripts/popup-preview.py:28`

```python
REPO = Path('/home/will/SRC/claude-usage')
```

Every other render script uses `Path(__file__).resolve().parent.parent`. This one was overlooked. A contributor checking out the repo can't run the pacing-viz preview without editing the script.

**Fix:** One-liner — `REPO = Path(__file__).resolve().parent.parent`.

### 3.9 T‑1 — No tests for tier/tooltip/reset/ring logic

**Files:** `server/tests/test_validate.py`, `server/tests/test_pacing.py`

`derive_tier`, `format_tooltip`, `parse_reset`, `ring_color`, `hex_to_rgba`, `load_config` have zero unit-test coverage. Passes 14-16 fixed real bugs in these (TS-1, D-1, WP-1, V-3, AS-1, the live-countdown path in parse_reset) — and there's no regression net. The CLAUDE.md "Regression guard" rule applies: when a bug is fixed, the test that catches it goes in the same commit. Several past fixes don't have tests.

**Fix:** Add `tests/test_tooltip.py` (parse_reset's three regex branches + the live-countdown path with `reset_minutes` + `anchor_ts`; format_tooltip's empty-meters / all-sonnet-only / missing-label paths) and `tests/test_icon.py` (derive_tier per broken-tier trigger; ring_color boundary tests at exactly the threshold values; hex_to_rgba edge cases — short/long/missing #).

### 3.10 IPC‑1 — Loopback handshake is signature, not authentication

**Files:** `chrome-extension/background.js:27-43`; `server/usage-server.py:243-256, 228-236`

The `/hello` probe → `{"app":"claude-usage","version":"..."}` body and the `X-Claude-Usage-Server` header are public. Any same-user process can bind 7331 first, respond with the right shape, and intercept POSTs. The comment at `usage-server.py:247` is honest: *"No auth; the signature is the body, not access control."*

Threat: a malicious or buggy same-user process can swallow the user's usage telemetry every 7 min (plan tier + balance + spend) and deny update propagation. Not outside scope: sandboxed Flatpaks, browser sub-processes, debugging tools, etc. all share the user's network namespace.

**Fix (tiered):**
- **Minimum:** add a `SECURITY.md` documenting the threat ("loopback IPC trusts any same-user process"). Stop implying auth in code comments. ~1 hour.
- **Better:** write a 32-byte token to `~/.cache/claude-usage/auth` (mode 0600), require it as a bearer header on POST. The Chrome ext reads it via the `chrome-extension://`-only `/token-handshake` endpoint. ~1 day.
- **Ideal:** UNIX domain socket under `$XDG_RUNTIME_DIR`. Requires Chrome MV4 or experimental flag. Defer.

### 3.11 L‑2 — Scraper hardcodes English string anchors

**Files:** `chrome-extension/scraper.js:58, 74-76, 92-93, 96, 105-106`; `chrome-extension/background.js:211-247` (inline copy)

```js
const planStart = lines.findIndex(l => l === 'Plan usage limits');
const addlStart = lines.findIndex(l => /^Additional features$/i.test(l));
const extraStart = lines.findIndex(l => l === 'Extra usage');
const balMatch = lines[i].match(/^...$/);
if (balMatch && /Current balance/i.test(lines[i + 1]))
```

If claude.ai ever serves the page in a non-English locale (de/fr/ja), every anchor misses → `meters = []` → status-only POST → `_scrape_fail_count` climbs → BROKEN tier with no signal that the cause is locale.

**Fix:** Two layers.
1. **Force English:** when opening the scrape tab, append `?lang=en` (if Anthropic honors it) or set `Accept-Language: en-US` for the scrape tab via `declarativeNetRequest`.
2. **Recovery signal:** if `meters === []` but `document.body.innerText` matches `\d+\s*%` somewhere (i.e., the page DID load, just couldn't parse), POST a distinguished `_parse_failure: 'locale'` so `claude-usage-status` and a future ext-popup can say "panel grey because locale parsing failed".

### 3.12 AS‑1 — Statuspage description over MAX_STR_LEN rejects the entire POST

**Files:** `server/usage-server.py:67, 102, 176-179`; `chrome-extension/background.js:118-124`

```python
MAX_STR_LEN = 128  # server/usage-server.py:67
```

`_anthropic_status.description` is free-form prose from Anthropic's Statuspage. Real-world descriptions exceed 128 chars routinely ("Investigating — We are seeing degraded throughput on Claude 3.7 Sonnet across the EU region…"). The validator rejects → 422 → cache never updates → BROKEN tier kicks in for the exact outage the field was meant to surface.

**Fix:** Both sides.
- Extension: `description: (j.status?.description ?? null)?.slice(0, 120) ?? null` (8 chars headroom).
- Server: auto-truncate `_anthropic_status.description` rather than reject. The validator already strips unknown keys; this is the same "be liberal in what you accept" pattern.

### 3.13 O‑1 — No observable error state in the Chrome extension

**Files:** `chrome-extension/background.js:330-343` (`postUpdate` failure); `chrome-extension/manifest.json:24-31` (no `default_popup`, no badge calls anywhere)

When `postUpdate` fails (no server in 7331-7340, scrape fails, server 422s), the only signal is `console.warn` in the SW DevTools — the user has to open `chrome://extensions` → SW link → DevTools to see it. There's no `chrome.action.setBadgeText`, no title rewrite, no popup. The user sees a grey GNOME panel and can't tell if the cause is "Chrome ext never loaded", "service down", "wrong port", "version skew", "scrape parse failure", or "Anthropic outage".

Every other silent-failure finding in this audit (L-2, AS-1, CM-1, MS-2, DG-2, V-3) is one degree worse without this.

**Fix (tiered):**
- **Cheap:** every postUpdate outcome updates the action title. `chrome.action.setTitle({ title: 'OK · last fetch 14:32' })` / `'⚠ server unreachable since 14:25 — see DevTools'`. Free, hover-reveals on every desktop env.
- **Real:** add `chrome-extension/popup.html` showing last fetch, last POST status (code + body summary), discovered port, ext version, "Force refetch" button. Wire `default_popup` (changes click-to-refresh semantics — relocate the refetch trigger inside the popup).

---

## 4. Low-Severity Findings

Brief descriptions; fix sketches in-line. Each is independently small but the cluster represents real maintenance cost.

| ID | Where | What | Fix |
|----|-------|------|-----|
| **DR‑1** | `gschema.xml:36,41` | `tWarn > tCrit` permitted; color tiers invert silently | Clamp in extension.js settings-read: `tCrit = Math.max(tCrit, tWarn + 1)`, log once |
| **DR‑2** | `popup-preview.py:97-99` | Fallback `popupNorm/panelNorm` is `#cccccc`; schema is `#2a9a2a`/`#ffffff` | Use schema values |
| **DR‑3** | `popup-preview.py:107` | Docstring references `extension.js:458`; real line is 472 | Update line ref (or use textual anchor) |
| **DR‑4** | `render-panel-screenshot.py:31` | `PANEL_WARN_COLOR = '#d07000'` hardcoded with "schema default" comment | Parse gschema XML once |
| **L‑3** | `extension.js:296` | `load_contents_async(null, ...)` not cancellable; GIO completes I/O after `destroy()` | Plumb `Gio.Cancellable` through |
| **L‑4** | `prefs.js:62-67` | Spinner `set_uint` per step; no debounce on GSettings write | 80–300 ms debounce mirroring scroll handler |
| **L‑5** | `prefs.js:38` | `_regenTimer` is module-scope | Move into `fillPreferencesWindow` closure |
| **L‑6** | `extension.js:516` (~`_stopFlash`) | Sibling to L-1: writes `_label.opacity = 255` without `_destroyed` guard | `if (!this._destroyed) ...` |
| **MS‑1** | `generate-icon.py:269-278`; sweep at `usage-server.py:502-522` | Per-size icon tmps leak on SIGINT/SIGTERM; sweep only covers `applications/` | `finally` cleanup + extend sweep to icon-theme dirs |
| **MS‑2** | `generate-icon.py:282` (cache refresh predicate) | Stale/corrupt icon-theme.cache never rebuilt; bare except hides timeout | Add `gtk-update-icon-cache --validate`; log timeout |
| **V‑1** | `usage-server.py:91` + validator | `_buffered_at` whitelisted but no bounds | Number + plausibility check mirroring `_timestamp` |
| **V‑2** | `usage-server.py:116-154` | `meters` list length not capped | `len(meters) > 50` rejected |
| **V‑3** | `usage-server.py:176-179`, `generate-icon.py:226-233` | Empty-string `indicator`/`claude_ai_component_status` → broken tier | Either `allow_empty=False` or `or 'none'/'operational'` in derive_tier |
| **D‑1** | `tooltip.py:108-141` | Missing `Name=` / `Icon=` lines silently NOT added | Track saw_name/saw_icon; append if missing |
| **DG‑2** | `generate-icon.py:71-91` | `load_config` `except Exception: return dict(DEFAULTS)` swallows silently | Log to stderr with the exception text |
| **DR‑5** | `popup-preview.py:482, 488` | `/tmp/claude-usage-popup-preview.html` is symlink-followable | `tempfile.NamedTemporaryFile` or PID-suffix + `O_NOFOLLOW` |
| **N‑1** | `.github/workflows/release.yml` | No `actions/setup-node`; Node version drifts with runner image | Add `setup-node@v4` with explicit version |
| **P‑1** | `install.sh:134-136`, `build-deb.sh:38-40` | `cp -r` + `rm -rf test` creates window where test/ exists at dest | `rsync -a --exclude=test/` |
| **P‑2** | `Taskfile.yml` + `packaging/control` + `chrome-extension/manifest.json` + `gnome-extension/metadata.json` | Three-place version triple; `task release` enforces parity but doesn't set | Add `task bump VERSION=…` that writes all three |

---

## 5. Info / observations

| ID | Where | Note |
|----|-------|------|
| **L‑7** | `extension.js:361, 495` | Color settings inserted into `St.set_style` without validation; `popup-font-family` *is* regex-validated. Self-inflicted only — but asymmetric defense. Add `parseHex` validator. |
| **L‑8** | `extension.js:359` | `anyCrit` scans unfiltered `d.meters`; popup uses `visibleMeters`. Today the Sonnet-0% filter makes them equivalent because `pacingPct` short-circuits on `pct === 0`. If anything ever lets a hidden meter report crit pacing, the panel flashes red with no popup row to explain. Document the intent or filter through the shared predicate. |
| **L‑9** | `extension.js:542-547` | `_clearingMetric = false` MUST precede `set_string('')` inside the idle to break re-entrance. Comment doesn't say so. A future re-order would silently lock the orphan-recovery path. Add a comment. |
| **CI‑2** | `chrome-extension/background.js:521-546` | `chrome.alarms` does NOT catch up on wake — one fetch per resume. Laptop suspend > 20 min ⇒ BROKEN tier on wake until first post-wake fetch lands. Add `chrome.idle.onStateChanged` listener that forces a fetch on `'active'`. Requires `"idle"` permission. |

---

## 6. Items reviewed and dismissed

- **`_atomic_write_multisize` `dest.parent.exists()` race** — `exists()` reflects state at read; `mkdir(exist_ok=True)` is idempotent. The race exists, but `new_dir` correctly captures "didn't exist when I looked". Not a bug.
- **`popup-preview.py` excluded from .deb** — confirmed. `build-deb.sh` copies only `server/{usage-server,generate-icon,tooltip}.py` plus `scripts/claude-usage-status.py`. `scripts/popup-preview.py` and all `render-*.py` are never bundled.
- **V-2 (pass-16) cache merge fix** — in place at `usage-server.py:335-336`; test `test_unknown_top_level_keys_filtered_from_cache` verifies.
- **PL-1 (pass-16) period-lengths eviction** — in place at `usage-server.py:378-384`; test `test_partial_post_does_not_wipe_period_lengths` verifies.
- **D-1 (pass-16) .desktop atomic rewrite** — in place at `tooltip.py:122-140`; always pins `Icon=claude-usage` on every rewrite.
- **R-1 (pass-16) auto-scrape race** — fixed; verified the 30s debounce + in-flight check.
- **WP-1 (pass-16) pacing floor** — fixed; verified `max(15, period * 0.05)` in both `pacing_pct` and `pacingPct`. Parity lint covers it.
- **HTTP bind to 127.0.0.1** — confirmed (not 0.0.0.0). Single-threaded `HTTPServer`; subprocess.Popen makes do_POST stay fast.
- **SIGCHLD auto-reap** — `signal.signal(signal.SIGCHLD, signal.SIG_IGN)` at server start; verified Popen children reaped.
- **Mutable default args** — grep found none. ✓
- **render-tooltip-screenshot.py icon pct=20 vs tooltip text 9%** — line 50 comment says "doesn't have to match METERS". Intentional. A reviewer reading the rendered PNG might find it confusing, but it's not a finding.
- **CORS in HTTP server** — verified: `chrome-extension://...` origins get `Access-Control-Allow-Origin`; other Origins do not. ✓

---

## 7. Recommended fix order

Acting on this list as a sequenced set of releases:

**0.11.20 — High-severity fixes (1–2 days work):**
- PR-1 (prefs spinner 99 → 500)
- L-1 + L-6 (flash timeout + stopFlash `_destroyed` guard)
- DG-1 (DEFAULTS thresholds 50/80 → 70/90)
- CI-1 (`run: task test` in workflow)
- T-1 (add test_tooltip.py + test_icon.py — even just smoke coverage)

**0.11.21 — Medium drift + observability (3–5 days):**
- CM-1 (cache type-guard)
- M-1 (multi-size two-phase commit)
- I-1 (install.sh glob)
- PP-1 (REPO path)
- LC-1 + S-1 (lifecycle cleanup)
- AS-1 (Statuspage description truncate)
- O-1 (Chrome ext action.setTitle on every postUpdate)

**0.11.22 — Drift-prevention infrastructure (2–3 days):**
- `scripts/lint-defaults-parity.py` — schema XML ↔ DEFAULTS dict ↔ prefs.js ranges ↔ render-*.py constants
- `task bump VERSION=…` (P-2)
- `actions/setup-node@v4` pin (N-1)
- Extend lint-scraper-parity to use tokenize-aware comment stripping (LK-1)
- IPC-1: SECURITY.md documenting the loopback trust model

**0.11.23+ — Locale & wake handling, validator cleanup:**
- L-2 (scraper i18n + parse-failure signal)
- CI-2 (chrome.idle wake listener)
- V-1, V-2, V-3, D-1, DG-2 (validator tightening, log fallbacks)

After 0.11.20–0.11.22 land, the remaining findings are individually small enough that they can be batched into a single "polish" release.

---

## 8. Cross-cutting recommendations

1. **Single source of truth for schema-tied constants.** Build a small helper (`server/schema_defaults.py` or `scripts/_schema.py`) that parses `gschema.xml` once and exposes both Python and JS-readable defaults. `generate-icon.py:DEFAULTS`, `popup-preview.py:fallback`, `_doc_render.py:CFG`, `render-*.py` color constants all consume from there. Adding a CI lint that the schema XML's `<default>` matches every consumer becomes one grep. Closes DG-1, DR-2, DR-4, and prevents the next instance.

2. **Observability before optimization.** Most of the silent-failure findings (CM-1, MS-2, DG-2, D-1, V-3, L-2) are individually small fixes that compound because the user has no first-line diagnostic. O-1 (Chrome action title or popup) multiplies the value of every other observability fix. Land it before V-1/V-2/V-3/D-1 — those become easier to triage with an ext-side view.

3. **Test the bug-fix paths from passes 14–16.** T-1 isn't just "missing tests" — it's "the regression guard rule has been on the books since pass-15 and the fixes are landing without it". Each finding in pass-15/16 that lacks a corresponding test in `server/tests/` is a candidate to re-emerge in pass-18 or later.

4. **`scripts/popup-preview.py` is hardening surface, not just debug.** It started as scaffolding but is now the prototype substrate for the next pacing-viz release. PP-1, DR-2, DR-3, DR-5 all point at the same thing: this script needs to graduate from "maintainer-local" to "any-contributor". Either commit to that and clean it up, or extract the renderer into something more durable and let the prototype rot.

5. **The pacing-viz prototype is not in extension.js yet — keep documentation accurate.** Today's docs/screenshots correctly render production style (single-tone bars). When the prototype lands in extension.js, every `render-*.py` script and the production_meter_row helper in `_doc_render.py` must switch to `pp.render_meter_row` in the same commit. Track as a single-commit migration, not gradual.

---

## 9. Resolution log

All 39 findings closed in the same session that opened the review. The user opted out of the by-hand review loop; landings done as autonomous commits.

| ID | Title | Commit |
|----|-------|--------|
| PR‑1  | Prefs spinner upper bound stuck at 99 | `6533877` |
| L‑1   | Flash timer no `_destroyed` guard | `2ae190b` |
| DG‑1  | `DEFAULTS` thresholds drift from gschema | `6533877` |
| CI‑1  | `lint-scraper-parity` never runs in CI | `6533877` |
| CM‑1  | Non-dict cache JSON crashes every POST | `8ae9cef` |
| M‑1   | Multi-size icon write not transactional | `b83547e` |
| LC‑1  | `_getPrimary` idle source not stored | `a968970` |
| S‑1   | Scroll EVENT_STOP for nothing-to-do | `a968970` |
| LK‑1  | Python `#` regex eats hex strings | `9b894ad` |
| I‑1   | `install.sh --uninstall` misses 3 of 5 sizes | `6533877` |
| PP‑1  | `popup-preview.py` hardcoded `/home/will` | `6533877` |
| T‑1   | No tests for tier/tooltip/reset/ring | `02e20ba` |
| IPC‑1 | Loopback IPC has no auth | `5c1b033` (SECURITY.md doc) |
| L‑2   | Scraper hardcodes English | `5c1b033` (`_parse_failure` signal) |
| AS‑1  | Statuspage description > MAX_STR_LEN | `9b894ad` |
| O‑1   | Chrome ext has no observable state | `5c1b033` (`chrome.action.setTitle`) |
| DR‑1  | `tWarn > tCrit` permitted | `a968970` (clamp in extension.js) |
| DR‑2  | popup-preview fallback colours wrong | `6533877` |
| DR‑3  | popup-preview line ref `:458` → `:472` | `9b894ad` (textual anchor) |
| DR‑4  | render-panel hardcoded `#d07000` | `6533877` |
| L‑3   | `load_contents_async` not cancellable | `a968970` |
| L‑4   | Spinner GSettings writes not debounced | `5c1b033` (120 ms) |
| L‑5   | `_regenTimer` module scope | `a968970` |
| L‑6   | `_stopFlash` no `_destroyed` guard | `2ae190b` |
| MS‑1  | Multi-size tmps leak on crash | `b83547e` |
| MS‑2  | Corrupt icon-theme.cache never rebuilt | `b83547e` (log timeout) |
| V‑1   | `_buffered_at` not validated | `8ae9cef` |
| V‑2   | `meters` list length not capped | `8ae9cef` (cap at 50) |
| V‑3   | Empty-string status → broken tier | `8ae9cef` (`derive_tier` normalize) |
| D‑1   | `update_desktop` silently drops `Name=` | `8ae9cef` (append if missing) |
| DG‑2  | `load_config` silent GIO fallback | `8ae9cef` (log to stderr) |
| DR‑5  | popup-preview predictable `/tmp` path | `9b894ad` (UID+PID suffix) |
| N‑1   | CI Node version unpinned | `02e20ba` (`setup-node@v4 24`) |
| P‑1   | `cp -r` + `rm -rf test` race | `02e20ba` (`rsync --exclude`) |
| P‑2   | Version triple two-place automation | `6533877` (`task bump`) |
| L‑7   | Color settings no validation | `a968970` (`safeColor` regex) |
| L‑8   | `anyCrit` scans unfiltered meters | `5c1b033` (documented intent) |
| L‑9   | `_clearingMetric` ordering undocumented | `a968970` (comment) |
| CI‑2  | No `chrome.idle` wake listener | `282a996` (adds `idle` permission) |

**Structural change carried by `6533877`:** `server/schema_defaults.py` is now the single source of truth for every gschema-tied constant. Eight findings — DG‑1, PR‑1, DR‑2, DR‑4, I‑1, PP‑1, P‑2, CI‑1 — closed at the architecture level by that single commit. (DR‑1 / DR‑3 / DR‑5 landed in separate commits — see table above; an earlier draft of this paragraph inflated the count to "DR‑1..5" inclusive; pass‑18 RL‑1 corrected the list but undercounted to "Six"; pass‑19 RC‑1 corrected the count to match the list.) The drift class doesn't keep recurring because there's only one place to drift from now, and `test_schema_defaults.py` fails CI on any hand-copy that doesn't match.
