# Code Review — wbniv/claude-usage

**Date:** 2026-05-17  
**Reviewer:** Claude (claude-sonnet-4-6)  
**Revision reviewed:** v0.10.6 / v0.10.7 (main branch, ~122 commits)  
**Scope:** Full codebase — chrome-extension, server, gnome-extension, scripts, install

---

## Executive Summary

The tool is well-structured for a single-developer desktop utility: the validation layer in `usage-server.py` is unusually thorough, the atomic-write pattern for the cache file is correct, and the tier/pacing model is a genuinely useful UX idea. Three issues deserve immediate attention before the next release:

1. A regex escaping bug in `extension.js` silently breaks the reset-time countdown display for all users.
2. `pacing_pct` is uncapped, causing the dock ring to overdraw for highly over-pace usage without any visual indication.
3. The server's CORS check admits any locally-installed Chrome extension rather than only this one.

Everything else is medium or low severity.

---

## File-by-File Findings

### `chrome-extension/background.js`

#### B-1 · Reset-minutes parse result not capped (Low)

`parseResetMinutes` returns raw minutes for the `"Resets Tue 5:00 PM"` form, which can be many thousands of minutes for a target far in the future. The server's `_validate()` caps `reset_minutes` at 44 640 (31 days), so malicious inputs are blocked — but a legitimate parsing edge case (e.g. the weekday arithmetic wrapping a second time) could produce an unexpectedly large value that skews `_period_lengths`.

**Recommended fix:** cap the return value at `60 * 24 * 31` inside `parseResetMinutes` to match the server's own bound.

```javascript
// after calculating `return Math.floor((target - now) / 60000);`
return Math.min(Math.floor((target - now) / 60000), 60 * 24 * 31);
```

#### B-2 · Hard-coded 3-second delay before scraping (Low)

```javascript
await new Promise(r => setTimeout(r, 3000));
```

This is a heuristic to wait for React hydration. On a slow machine the page may not be ready; on a fast one it wastes 3 s on every alarm cycle (7-minute period, 3 s = 0.7% overhead — acceptable but avoidable). A `MutationObserver` waiting for the first `%used` text node would be more deterministic, though considerably more complex.

#### B-3 · `_scrape_tabs` cleanup on crash is incomplete (Low)

After `chrome.tabs.create`, the tab ID is written to `_scrape_tabs` to survive a service-worker crash. However, between `chrome.tabs.create` and the `chrome.storage.local.set`, a crash would leave the tab open with no record of it. On restart, the cleanup loop finds `_scrape_tabs: []` and skips it. The leaked tab requires a manual browser restart to remove.

This is an inherently small window and not security-relevant, but worth noting in the crash-recovery story.

#### B-4 · Outer catch in `fetchUsage` reports to local server — which may also fail (Low)

```javascript
} catch (err) {
    // ...
    await fetch(LOCAL_SERVER, { ... });  // this can throw too
} catch (_) {}              // silently swallowed
```

The double-catch means a server-unavailable event during an error report produces no diagnostic output at all. `console.warn` before the inner fetch would surface at least something in the extension background page devtools.

---

### `chrome-extension/manifest.json`

#### M-1 · Version inconsistency with README (Low)

`manifest.json` declares version `0.10.7`; the README header and the Taskfile release notes reference `v0.10.6`. The Taskfile release task enforces consistency between `packaging/control` and `manifest.json` but does not update the README. If the README is the user-facing version anchor, the release task should patch it too.

---

### `server/usage-server.py`

#### S-1 · CORS check admits any Chrome extension (High)

```python
def _cors(self):
    origin = self.headers.get('Origin', '')
    if origin.startswith('chrome-extension://'):
        self.send_header('Access-Control-Allow-Origin', origin)
```

The intent is to allow only this extension. The check instead allows any locally-installed Chrome extension that happens to discover port 7331. The correct check requires knowing this extension's ID at install time (it changes per-device for unpacked installs) — but the practical mitigation is that the server only binds to `127.0.0.1`, so an attacker would need local code execution to reach it at all. The validation layer further limits damage.

**Recommended fix for packaged releases** (where the extension ID is stable): hard-code the published extension ID and compare exactly.

```python
_ALLOWED_ORIGIN = 'chrome-extension://<stable-id>'

def _cors(self):
    origin = self.headers.get('Origin', '')
    if origin == _ALLOWED_ORIGIN:
        self.send_header('Access-Control-Allow-Origin', origin)
        ...
```

For unpacked installs, document the risk and note it in PRIVACY.md.

#### S-2 · `_period_lengths` dict grows unboundedly (Medium)

Each unique meter label seen by the server is stored as a key in `_period_lengths`. The value is capped at 44 640 minutes, but the key count is not bounded. If Claude.ai renames meters over time, stale keys accumulate forever in `usage.json`. After a year of occasional label changes, the dict could contain dozens of stale entries that feed incorrect pacing calculations for any future meter whose name partially matches a stale key.

**Recommended fix:** On each POST that carries a full `meters` list, evict keys from `_period_lengths` whose labels are no longer present in the current meter set:

```python
current_labels = {m.get('label') for m in body.get('meters', []) if m.get('label')}
if current_labels:
    period_lengths = {k: v for k, v in period_lengths.items() if k in current_labels}
```

#### S-3 · `_validate()` missing count bound on `_period_lengths` keys (Medium)

Complementing S-2: even without label churn, a crafted POST could include a `_period_lengths` dict with thousands of keys. Add a key-count guard:

```python
if len(pl) > 100:
    return f"'_period_lengths' must have ≤ 100 keys"
```

#### S-4 · 413 returned for missing Content-Length (Low)

```python
length = int(self.headers.get('Content-Length', 0))
if length <= 0 or length > 256 * 1024:
    self.send_response(413)
```

A request with no `Content-Length` header gets 413 (Payload Too Large). RFC 7231 specifies 411 (Length Required) for this case. Not a functional issue since the only client is the extension (which always sets `Content-Length`), but pedantically incorrect.

---

### `server/generate-icon.py`

#### G-1 · `pacing_pct` is uncapped — Cairo arc overdraws at high pacing (High)

```python
def pacing_pct(meter, period_lens):
    ...
    return pct / fraction   # can be >> 100
```

`draw_ring` computes the arc angle as `2π × (pct / 100)`. When pacing exceeds 100%, the arc spans more than one full revolution. Cairo silently completes the extra arc, making a 200%-pacing ring visually identical to a 100% full ring — there is no visual signal that usage is running ahead of pace.

The `broken` tier explicitly uses `max(all_pct, 100)` for its visual, confirming the author is aware of the >100 case, but the normal tier does not cap.

**Recommended fix:** clamp the value passed to `draw_ring`, or render a distinct visual (e.g., pulsing opacity, different ring color) when pacing > 100%:

```python
# Quick fix — cap at 100 for the ring; display exact value in tooltip
draw_ring(cr, cx, cy, R_OUTER, THICK_OUTER,
          min(100, all_pct), ring_color(all_pct, cfg))
```

A richer fix would use the existing `ring_color` result plus a secondary "overpace" indicator. The tooltip already reflects the true pacing percentage, so capping the ring is not a data-loss concern.

#### G-2 · `find_meter` lambda scoped inside `main` (Low / Style)

```python
find_meter = lambda kw: next(
    (m for m in meters if kw in (m.get('label') or '').lower()), None)
```

This keyword-substring match is duplicated (with slight variation) in `extension.js:_getPrimary` and `tooltip.py:format_tooltip`. Since Python and JS share no code, deduplication is impossible without an API change, but the pattern is worth documenting. If Claude.ai adds a meter whose name contains `"all"` as a substring of a longer word (e.g., `"overall"`), the wrong meter will be selected. A full-string match (with known aliases) would be more defensive.

#### G-3 · `load_config` silently falls back per-key on bad color values (Low)

```python
for key in ('weekly_color_green', ...):
    try:
        hex_to_rgba(cfg[key])
    except Exception:
        cfg[key] = DEFAULTS[key]
```

If a user sets an invalid color string via `gsettings`, the icon silently uses the default color with no warning. A `print(..., file=sys.stderr)` in the except branch would make this discoverable in the journal.

---

### `server/tooltip.py`

#### T-1 · `parse_reset` `[Rr]` regex — correct here, wrong in extension.js (informational)

The `re.match(r'[Rr]esets? in …')` syntax in tooltip.py is correct — `[Rr]` is a character class. See **E-1** below for the extension.js version which incorrectly escapes the brackets.

#### T-2 · `update_desktop` silently drops unrecognised .desktop lines (Low)

```python
elif line.startswith('[') or '=' in line or line == '':
    out.append(line)
# lines that match none of the above are silently dropped
```

A line that is neither `Name=`, `Icon=`, `#…`, `[…]`, nor contains `=` (e.g. a blank comment block marker some editors insert) is silently omitted from the rewritten file. The .desktop format is simple enough that this is unlikely to trigger in practice, but an explicit `else: out.append(line)` catch-all would be safer.

#### T-3 · `format_tooltip` hardcodes meter name keywords (Low)

```python
find = lambda kw: next((m for m in meters if kw in (m.get('label') or '').lower()), None)
current = find('session') or find('current')
all_m   = find('all')
sonnet  = find('sonnet')
```

If Anthropic renames "All models" to something not containing `"all"`, the tooltip silently shows `"Claude Usage"` with no meter data. Adding a `console.warn` / `print` fallback when no meters are found would surface the regression.

---

### `gnome-extension/extension.js`

#### E-1 · `formatReset` regex escaping bug — resets never display as countdown (Critical)

```javascript
// WRONG — \[ and \] match literal bracket characters, not a character class
m = reset.match(/\[Rr\]esets? in (\d+) hr (\d+) min/);
m = reset.match(/\[Rr\]esets? in (\d+) min/);
m = reset.match(/\[Rr\]esets? (\w{3}) (\d+):(\d+) (AM|PM)/);
```

In a JavaScript regular expression, `\[` is an escaped literal `[` character. The pattern `/\[Rr\]esets?/` matches the 9-character string `[Rr]eset` — it will **never** match the actual reset strings delivered by the server (`"Resets in 5 hr 30 min"`, `"resets in 30 min"`, etc.). All three countdown branches are dead code. The function always falls through to `return reset`, outputting the raw server string (e.g. `"Resets in 5 hr 30 min"`) into the popup label rather than `"resets in ⏱5:30"`.

This bug is absent in the functionally-equivalent code in `background.js` and `tooltip.py`, which both use the unescaped form correctly.

**Fix:** remove the backslashes from all three regexes in `formatReset`:

```javascript
// CORRECT
m = reset.match(/[Rr]esets? in (\d+) hr (\d+) min/);
if (m) return `resets in ⏱${m[1]}:${m[2].padStart(2, '0')}`;
m = reset.match(/[Rr]esets? in (\d+) min/);
if (m) return `resets in ⏱0:${m[1].padStart(2, '0')}`;
m = reset.match(/[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)/);
```

#### E-2 · `logError` deprecated in GNOME Shell 48+ (Medium)

```javascript
logError(e, 'ClaudeUsage: file monitor failed');
logError(e, 'ClaudeUsage: failed to read cache');
```

`logError` was deprecated in GNOME Shell 48 and removed in 49. `metadata.json` declares `"shell-version": ["45", "46", "47", "48", "49"]`, so all supported versions should use `console.error` instead:

```javascript
console.error('ClaudeUsage: file monitor failed', e);
console.error('ClaudeUsage: failed to read cache', e);
```

#### E-3 · `_loadData` performs synchronous I/O on the GNOME Shell main thread (Medium)

```javascript
const [ok, contents] = f.load_contents(null);  // blocking
```

`Gio.File.load_contents(null)` blocks the GJS main loop. The cache file is small (a few KB) and on a local tmpfs-backed path, so latency is negligible in practice. But GNOME extension best practice is to use `load_contents_async` to avoid contributing to shell jank on a slow or NFS-mounted home directory.

#### E-4 · Panel metric preference not validated against available meters (Low)

```javascript
const label = this._settings.get_string('panel-metric');
if (label) {
    const found = meters.find(m => m.label === label && this._isSelectable(m));
    if (found) return found;
}
```

If the stored `panel-metric` label no longer exists (e.g. after a Claude plan change), the fallback silently selects the first "all" meter. This is correct behaviour, but the stale preference string is never cleared, so `gsettings` always shows the obsolete label. Clearing the preference when the label is not found would keep settings consistent:

```javascript
if (!found) this._settings.set_string('panel-metric', '');
```

#### E-5 · `_anyCrit` and `_flashSuppressed` not initialised in `_init` (Low / Style)

Both are read in `_updateDisplay` before they are first written. In GJS, reading an uninitialised instance property returns `undefined` (falsy), so there is no runtime error. Explicit initialisation makes intent clear:

```javascript
this._anyCrit = false;
this._flashSuppressed = false;
```

#### E-6 · Notification cooldown (`_lastCritNotifyTs`) resets on extension reload (Low)

The 5-minute cooldown for critical notifications is stored only in the instance. A GNOME Shell restart or extension disable/enable resets the cooldown, potentially firing a duplicate notification. For a status indicator this is acceptable but worth noting.

---

### `gnome-extension/prefs.js`

#### P-1 · Warning and critical thresholds not enforced relative to each other (Medium)

Both threshold spin rows allow any value in `[1, 99]` independently. A user can set warning=90 and critical=50, resulting in the critical threshold being lower than the warning threshold. The popup comment says "must be below Critical" / "must exceed Warning" but there is no enforcement. The pacing colour would then behave inverted: usage at 60% would show as critical while 95% shows as warning.

**Recommended fix:** connect the two `SpinRow` adjustments so each clamps to stay on the correct side of the other:

```javascript
warningAdj.connect('value-changed', () => {
    const wVal = Math.round(warningAdj.get_value());
    if (wVal >= Math.round(criticalAdj.get_value()))
        criticalAdj.set_value(wVal + 1);
    settings.set_uint('threshold-warning', wVal);
    regenIcon();
});
// symmetric for criticalAdj
```

---

### `scripts/claude-usage-status.py`

No issues found beyond the source rendering artefact (indentation collapsed in the fetched representation). The logic — checking service status, cache age, scrape fail count, Anthropic status, and GNOME extension state — is correct and provides good diagnostics.

---

### `install.sh`

The install script was reviewed at summary level. One observation:

#### I-1 · `set -euo pipefail` not confirmed (Low)

The summary did not show the shebang/preamble. Bash install scripts should use `set -euo pipefail` to prevent silent failures when `cp`, `mkdir`, or `systemctl` commands fail midway. If it is absent, a failed `python3-cairo` install, for example, would silently proceed to registering the systemd service against a broken setup.

---

## Cross-Cutting Concerns

### Architecture: Reset-string parsing triplicated

`parseResetMinutes` (background.js), `parse_reset` (tooltip.py), and `formatReset` (extension.js) all independently parse the same four string formats emitted by claude.ai. Any format change requires three coordinated edits in two languages. The partial fix already in place — the server stores `reset_minutes` as an integer and both Python consumers use it — should be extended: **the raw `reset` string should be treated as opaque/display-only in the extension**. Instead, `extension.js` should derive its countdown purely from `reset_minutes` and a locally-computed elapsed time, matching what tooltip.py already does via `anchor_ts`.

### Architecture: `pacing_pct` duplicated in JS and Python

`pacing_pct` (generate-icon.py) and `pacingPct` (extension.js) are identical in logic. This is unavoidable given the cross-language constraint, but both should be kept in sync and the business rules (e.g., the `fraction <= 0.01` guard) documented in one canonical place.

### Scraper fragility and lack of tests

The scraper (`background.js:scrapeAndPost`) relies on line-by-line text layout of `document.body.textContent`. Any DOM restructuring or whitespace change at claude.ai silently fails, detected only by rising `_scrape_fail_count`. There are no automated tests anywhere in the repository.

**Recommended:** extract the scraping logic into a pure function that takes a string and returns a `{meters, plan}` object, then add a test file with captured `textContent` snapshots that exercise boundary cases (plan boundaries, extra-usage toggle on/off, additional-features section, empty page).

---

## Severity / Effort Matrix

| ID  | Severity | Effort | File | Summary |
|-----|----------|--------|------|---------|
| ~~E-1~~ | ~~Critical~~ | ~~XS~~ | ~~extension.js~~ | ~~`\[Rr\]` regex never matches — reset countdown always broken~~ |
| ~~G-1~~ | ~~High~~ | ~~S~~ | ~~generate-icon.py~~ | ~~Uncapped pacing → Cairo arc overdraws at >100%~~ |
| ~~S-1~~ | ~~High~~ | ~~S~~ | ~~usage-server.py~~ | ~~CORS allows any Chrome extension, not just this one~~ |
| ~~S-2~~ | ~~Medium~~ | ~~S~~ | ~~usage-server.py~~ | ~~`_period_lengths` keys accumulate without pruning~~ |
| ~~S-3~~ | ~~Medium~~ | ~~XS~~ | ~~usage-server.py~~ | ~~No key-count bound on `_period_lengths`~~ |
| ~~E-2~~ | ~~Medium~~ | ~~XS~~ | ~~extension.js~~ | ~~`logError` deprecated in GNOME 48+~~ |
| ~~E-3~~ | ~~Medium~~ | ~~M~~ | ~~extension.js~~ | ~~Synchronous file I/O on GNOME Shell main thread~~ |
| ~~P-1~~ | ~~Medium~~ | ~~S~~ | ~~prefs.js~~ | ~~Warning/critical thresholds not constrained relative to each other~~ |
| T-2 | Low | XS | tooltip.py | Unrecognised .desktop lines silently dropped |
| T-3 | Low | XS | tooltip.py | Meter keyword match fragile for future label changes |
| E-4 | Low | XS | extension.js | Stale `panel-metric` preference never cleared |
| E-5 | Low | XS | extension.js | `_anyCrit`/`_flashSuppressed` not initialised in `_init` |
| E-6 | Low | — | extension.js | Notification cooldown resets on extension reload |
| B-1 | Low | XS | background.js | `reset_minutes` return not capped at parse site |
| ~~B-2~~ | ~~Low~~ | ~~—~~ | ~~background.js~~ | ~~3-second scrape delay is a heuristic~~ |
| B-3 | Low | S | background.js | Tab leak window between create and storage write |
| B-4 | Low | XS | background.js | Error-report fetch failure fully silenced |
| G-2 | Low | — | generate-icon.py | Substring `find_meter` vulnerable to label prefix collisions |
| G-3 | Low | XS | generate-icon.py | Silent color-fallback gives no journal entry |
| M-1 | Low | XS | manifest.json | Version mismatch with README |
| I-1 | Low | XS | install.sh | `set -euo pipefail` not confirmed |

**Effort key:** XS = 1–5 min, S = 15–30 min, M = 1–2 h

---

## Recommended Priority Order

1. **E-1** — one-line fix, fixes a visible display regression for all users.
2. **E-2** — two-line fix, required for GNOME 49 compatibility.
3. **G-1** — cap pacing at 100 for ring rendering, or add an over-pace visual.
4. **P-1** — prevent inverted threshold configuration in prefs.
5. **S-2 + S-3** — prune stale `_period_lengths` keys, add key-count bound.
6. **S-1** — pin CORS to a stable extension ID once the extension is published.
7. **E-3** — async cache read (low urgency, high quality-of-life for edge cases).
8. Tests for the scraper — invest once, saves repeated debugging.
