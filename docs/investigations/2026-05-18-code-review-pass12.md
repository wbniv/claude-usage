# Code Review — Pass 12 (exhaustive, post-pass-11 verification)

**Date:** 2026-05-18 (late, after pass 11 + pass-11 fixes shipped as `0.11.0`)
**Reviewer:** Claude (Opus 4.7, max effort, 1M context)
**Scope:** Full codebase, runtime verification, packaging, CI, systemd, cross-installer parity
**Prior work:** Passes 1–11 + the [2026-05-18 comprehensive review](2026-05-18-code-review-comprehensive.md); permanent deferrals in [docs/wont-fix.md](../wont-fix.md)

This pass starts where [pass 11](2026-05-18-code-review-pass11.md) left off — it verifies every pass-11 fix against the running system, audits the changes that landed in commits `d5f8025`, `5555e67`, `c281f23`, then asks: *what's left that 11 prior passes haven't seen?*

The answer is **13 new items**, none critical, but two of them are real cross-installer parity bugs that the .deb-focused pass 11 missed because it only inspected the `claude-usage-setup` path. The source-install (`install.sh`) path was not updated to match. Several others are subtle JS bugs uncovered by a deeper trace of GSettings re-entry and GLib timeout lifetime.

---

## 1. Executive Summary

All 13 findings fixed in `0.11.1` (commit `fix(pass12): I-2 install.sh reset-failed + 12 other findings; bump 0.11.1`). Strike-through indicates closed.

| Sev | # | ID | Title |
|-----|---|----|-------|
| ~~High~~ | ~~1~~ | ~~**I‑2**~~ | ~~`install.sh` missing `reset-failed` parity with `claude-usage-setup` — source-install upgrades from a broken state still fail~~ |
| ~~Medium~~ | ~~2~~ | ~~**E‑10**~~ | ~~`_watchFile` retry timeout is untracked — `destroy()` cannot cancel it; callback fires on torn-down wrapper~~ |
| ~~Medium~~ | ~~3~~ | ~~**E‑11**~~ | ~~`_getPrimary()` writes `panel-metric=''` inside `_updateDisplay()` — GSettings `changed` re-enters synchronously and renders twice~~ |
| ~~Medium~~ | ~~4~~ | ~~**K‑3**~~ | ~~`install.sh` `cp` is non-recursive — emits `cp: -r not specified; omitting directory 'chrome-extension/test'` warning on every install~~ |
| ~~Medium~~ | ~~5~~ | ~~**K‑4**~~ | ~~`.deb` ships `chrome-extension/test/` into `/usr/share/claude-usage/` — visible to users who load-unpacked from that path~~ |
| ~~Medium~~ | ~~6~~ | ~~**V‑1**~~ | ~~Silent Chrome‑extension version skew — live cache shows `plan: "Max plan"` and zero `reset_minutes`, both impossible under HEAD scraper. No handshake/visibility~~ |
| ~~Low~~ | ~~7~~ | ~~**S‑5**~~ | ~~`_anthropic_status` validator accepts unknown keys — persists junk in cache without bound (capped only by 256 KB POST limit)~~ |
| ~~Low~~ | ~~8~~ | ~~**S‑6**~~ | ~~`_period_lengths: {}` from a malicious or stale POST clobbers accumulated state — merge precedence accepts explicit empty dict~~ |
| ~~Low~~ | ~~9~~ | ~~**J‑2**~~ | ~~`extension.js::_spawnIconRegen` re-runs the candidate-file probe on every call; `prefs.js` caches at module load — asymmetry~~ |
| ~~Low~~ | ~~10~~ | ~~**I‑3**~~ | ~~`install.sh` apt-get fallback only works on Debian/Ubuntu — Fedora/Arch users see "command not found" with no guidance~~ |
| ~~Info~~ | ~~11~~ | ~~**A‑1**~~ | ~~Cache schema versioning (ARCH‑1 from comprehensive review) still unaddressed — `usage.json` has no `_schema` field~~ |
| ~~Info~~ | ~~12~~ | ~~**T‑4**~~ | ~~`_validate()` still has zero unit tests (pass-10 high, comprehensive §6, both unresolved)~~ |
| ~~Info~~ | ~~13~~ | ~~**C‑3**~~ | ~~Live smoke test posts only the current payload shape — no backcompat test for older Chrome → newer server~~ |

**Bottom line:** the [pass-11](2026-05-18-code-review-pass11.md) and [comprehensive](2026-05-18-code-review-comprehensive.md) findings are all verified resolved on the running system. The pass-11 R-1 critical regression is closed (service is `Active: active (running) since 2026‑05‑18 01:42:31; 8m ago`), the live-smoke CI gate is wired in `release.yml`, and the 25.10 matrix is in place. What remains is a smaller, lower-severity set: a half-finished `reset-failed` migration that only touched the .deb path, a couple of subtle GJS lifecycle bugs, and a slow accumulation of structural debt around schema/versioning/test-coverage that no pass has bottomed out.

---

## 2. Verification of pass‑11 fixes (live evidence)

Each pass‑11 finding was verified against the running system at review time.

| ID | Status | Live evidence |
|----|--------|---------------|
| **R‑1** crash-loop | ✓ Resolved | `systemctl --user is-active claude-usage-fetch.service` → `active`; PID 962557, running since 01:42:31, memory 11 M, no `218/CAPABILITIES` in `journalctl --user -u claude-usage-fetch -n 30` |
| **R‑2** missing `ReadWritePaths` | ✓ N/A | All namespace/mount directives removed from `systemd/claude-usage-fetch.service`; only seccomp-based hardening remains (lines 20–24) |
| **C‑1** no CI start-test | ✓ Resolved | `packaging/test-deb-live.sh` exists (94 lines, full POST-and-cache-write flow) and is wired into `.github/workflows/release.yml` lines 108–113 |
| **C‑2** 24.04-only CI | ✓ Resolved | `release.yml` has separate cache + build + test steps for both `ubuntu:24.04` and `ubuntu:25.10` images (lines 33–100) |
| **D‑1** stale 15-min docstrings | ✓ Resolved | `grep -n "15 min" server/*.py` → empty; both docstrings now read "between scrape POSTs" |
| **J‑1** `parseInt` radix in extension.js | ✓ Resolved | `grep -n "parseInt(" *.js \| grep -v ", 10)"` → empty across the GNOME extension |
| **X‑1** XDG dirs | ✓ Mostly resolved | Python uses `os.environ.get('XDG_*')` in 5 files; GJS uses `GLib.get_user_cache_dir()`. **Partial gap:** GJS still hardcodes `~/.local/share` for the script-path probe (`extension.js:213`, `prefs.js:11`) — see J‑2 below |
| **I‑1** restart spam | ✓ Resolved | `StartLimitBurst=5` + `StartLimitIntervalSec=60` present in the unit (lines 4–5); restart counter no longer climbs into the thousands |

The comprehensive review's six findings (PREFS‑1, JS‑1, JS‑6, JS‑7, CI‑1, CI‑2) were all addressed in commit `c281f23` and are recorded as struck-through in the original review's summary table.

---

## 3. New Findings

### I‑2 · `install.sh` missing `reset-failed` parity with `claude-usage-setup` (High)

**Files:** `install.sh:107–108`, `packaging/claude-usage-setup:23–29`

Pass 11 identified that a service stuck in `StartLimitBurst` exhaustion would not start under `systemctl --user enable --now`, and commit `5555e67` ("fix(setup): reset-failed before enable --now in claude-usage-setup") added the fix. But the fix landed only in the **.deb postinst path** (`claude-usage-setup`), not in **install.sh** (the source-install path):

```bash
# claude-usage-setup:23–29 (correct)
systemctl --user daemon-reload
systemctl --user reset-failed claude-usage-fetch.service 2>/dev/null || true
systemctl --user enable --now claude-usage-fetch.service

# install.sh:107–108 (still broken)
systemctl --user daemon-reload
systemctl --user enable --now claude-usage-fetch.service
```

**Concrete impact:** A user who installed `0.10.x` from source, then ran `./install.sh` to upgrade to `0.11.0` after suffering the pass-11 R-1 crash-loop, will not have their service start. `enable --now` is a no-op when the unit is in `failed/start-limit-hit` state, and there is no error printed — `install.sh` proudly prints `✓ Systemd service enabled and started` and exits 0. The user discovers the broken state via `claude-usage-status` only after wondering why the panel still shows `--`.

The fix is exactly the line that landed in `claude-usage-setup`. There is no reason these two installers should diverge.

**Fix:**

```bash
# install.sh:107–108
systemctl --user daemon-reload
systemctl --user reset-failed claude-usage-fetch.service 2>/dev/null || true
systemctl --user enable --now claude-usage-fetch.service
```

This is a 1-line change. While there, the two installers should share an "install-or-upgrade systemd unit" helper to prevent future drift.

---

### E‑10 · `_watchFile` retry timeout is untracked (Medium)

**File:** `gnome-extension/extension.js:240–244`

```js
} catch (e) {
    console.error('ClaudeUsage: file monitor failed, retrying in 30 s', e);
    GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 30, () => {
        this._watchFile();
        return GLib.SOURCE_REMOVE;
    });
}
```

The source ID returned by `GLib.timeout_add_seconds` is discarded. `destroy()` (lines 473–495) cancels `this._monitor`, `this._tickId`, `this._flashId`, `this._settingsId`, and `this._menuOpenId` — but it does not know about this retry source. If the extension is disabled within the 30 s window (user toggling extensions, GNOME Shell `r` reload, swapping themes), the callback fires on a torn-down wrapper.

Tracing what then happens:
1. The arrow function captures `this` lexically; the JS wrapper is still reachable, so accessing `this` doesn't throw.
2. `this._watchFile()` is called, which does `this._monitor = f.monitor_file(...)`. Setting a property on a destroyed `GObject` wrapper does not throw in GJS — but the new `GFileMonitor` is created and never canceled (it has no path back into `destroy()`).
3. Its `changed` signal handler eventually fires `this._loadData()`, which on success calls `this._updateDisplay()`, which calls `this._label.set_text(...)` on a destroyed `St.Label` — this *does* throw, and GNOME Shell logs the stack trace in `journalctl --user -t gnome-shell`.

**Cost:** one leaked `GFileMonitor` per disable-during-retry, one stack trace per cache write afterward. Not catastrophic, but it's the kind of slow-growing GNOME Shell symptom that drains memory across long Wayland sessions and shows up as "GNOME Shell is using 800 MB after 3 days" complaints with no obvious cause.

**Fix:**

```js
} catch (e) {
    console.error('ClaudeUsage: file monitor failed, retrying in 30 s', e);
    this._retryId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 30, () => {
        this._retryId = null;
        this._watchFile();
        return GLib.SOURCE_REMOVE;
    });
}

// In destroy():
if (this._retryId) {
    GLib.source_remove(this._retryId);
    this._retryId = null;
}
```

---

### E‑11 · `_getPrimary()` causes a re-entrant render via GSettings write (Medium)

**File:** `gnome-extension/extension.js:460–471`

```js
_getPrimary(meters) {
    const label = this._settings.get_string('panel-metric');
    if (label) {
        const found = meters.find(m => m.label === label && this._isSelectable(m));
        if (found) return found;
        this._settings.set_string('panel-metric', '');  // ← line 465
    }
    return meters.find(m => /all/i.test(m.label ?? '') && this._isSelectable(m))
        || meters.find(m => this._isSelectable(m))
        || meters[0]
        || null;
}
```

`_getPrimary()` is called from inside `_updateDisplay()` (line 293). When the stored `panel-metric` no longer matches any current meter (renamed/removed by Anthropic), line 465 writes `''` to clear the stale value. GSettings dispatches the resulting `changed` signal **synchronously** within `set_string()` — it is not deferred to the next main-loop tick.

Trace:
1. `_updateDisplay` runs.
2. → `_getPrimary` finds stale label, calls `set_string('panel-metric', '')`.
3. → `changed` handler at line 171 fires synchronously, recursively calling `_updateDisplay`.
4. → recursive `_updateDisplay` reaches `_getPrimary` again, sees `label === ''` (empty), takes the false branch, falls through to "all" / first-eligible. Returns. Recursive render completes: meters section rebuilt, all popup items allocated.
5. Outer `_updateDisplay` continues past line 465 with the same `_data` / `_settings` snapshots, computes the same primary, and rebuilds the meters section *again* — discarding the popup items the inner call allocated.

This is not an infinite loop (the inner call doesn't re-enter the `set_string`), but it does a full double-render on every tick where the panel-metric is stale. Cost: 2× `St.Label` + `PopupMenuItem` allocations, 2× GSettings reads for color/style. Visually, GNOME Shell coalesces relayout so the user sees no flicker — but there is a measurable CPU spike on stale-label ticks.

**Fix:** guard the write so re-entry is impossible:

```js
if (label) {
    const found = meters.find(m => m.label === label && this._isSelectable(m));
    if (found) return found;
    // Defer the clear so we finish this render first.
    if (!this._clearingMetric) {
        this._clearingMetric = true;
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this._clearingMetric = false;
            this._settings.set_string('panel-metric', '');
            return GLib.SOURCE_REMOVE;
        });
    }
}
```

Or simpler: clear it once at extension load time if there's no matching meter, not on every render.

---

### K‑3 · `install.sh` `cp` is non-recursive — `test/` skipped with a stderr warning (Medium)

**File:** `install.sh:96`

```bash
# 2b. Chrome extension install copy (Chrome loads unpacked from this path)
mkdir -p "$SERVER_DIR/chrome-extension"
cp "$REPO_DIR/chrome-extension/"* "$SERVER_DIR/chrome-extension/"
```

`chrome-extension/` contains a `test/` subdirectory. Without `-r`, `cp` skips the directory and prints:

```
cp: -r not specified; omitting directory 'chrome-extension/test'
```

Verified live:

```bash
$ cp chrome-extension/* /tmp/dest/
cp: -r not specified; omitting directory 'chrome-extension/test'
$ echo $?
0
```

Exit is `0` (so `set -e` doesn't abort), but the user sees the warning. It's harmless — Chrome doesn't need `test/` — but it makes a clean install look like something is broken.

`packaging/build-deb.sh:37` uses `cp -r` correctly. The two paths diverge.

**Fix:** `install.sh:96` should either match `build-deb.sh` (use `cp -r`) and then explicitly delete `test/` after copying, or use `find ... -maxdepth 1 -type f -exec cp` to copy only files. The cleaner approach mirrors what `build-chrome-zip.sh:10` already does for the CWS zip:

```bash
# Copy everything except test/
cp -r "$REPO_DIR/chrome-extension/." "$SERVER_DIR/chrome-extension/"
rm -rf "$SERVER_DIR/chrome-extension/test"
```

---

### K‑4 · `.deb` ships `chrome-extension/test/` (Medium)

**File:** `packaging/build-deb.sh:37`

```bash
cp -r "$REPO_DIR/chrome-extension" "$PKG/usr/share/claude-usage/"
```

This is `cp -r` — correct in that it doesn't warn, but it copies `test/scraper.test.js` (332 lines) into the .deb. After install, `/usr/share/claude-usage/chrome-extension/test/scraper.test.js` is present on the user's machine. When they `chrome://extensions` → Load unpacked → `/usr/share/claude-usage/chrome-extension/`, Chrome scans the whole directory tree and silently includes the test file in the loaded extension package — harmless because it's not in `manifest.json`, but it's bloat in every .deb (332 lines × N user installs) and a leak of dev-only artifacts into a published package.

`build-chrome-zip.sh:10` explicitly excludes `test/*` — the CWS zip is clean. The `.deb` is not.

**Fix:**

```bash
# build-deb.sh:37
cp -r "$REPO_DIR/chrome-extension" "$PKG/usr/share/claude-usage/"
rm -rf "$PKG/usr/share/claude-usage/chrome-extension/test"
```

Or move the exclude logic into a shared helper so the three install paths (install.sh, build-deb.sh, build-chrome-zip.sh) can't drift again.

---

### V‑1 · Silent Chrome-extension version skew (Medium)

**Files:** `chrome-extension/manifest.json`, `chrome-extension/background.js` vs runtime cache state

The live cache on the maintainer's own machine contains:

```json
{
  "plan": "Max plan",
  "meters": [
    {"label": "Current session", "pct": 43, "reset": "Resets in 2 hr 58 min"},
    {"label": "All models",      "pct": 41, "reset": "Resets Tue 1:00 PM"},
    ...
  ],
  "_period_lengths": {}
}
```

Two impossible signals:
1. **`plan: "Max plan"`** — the HEAD regex at `background.js:103` is `^(?:Plan:\s*)?(Max(?:\s*\([^)]+\))?|Pro|Free|Team)$` and captures group 1, which is `"Max"` (or `"Max (5x)"`), never `"Max plan"`. No version of the scraper that exists in this repo's history captures with the `" plan"` suffix.
2. **Every meter has `reset_minutes` absent**, despite reset strings like `"Resets in 2 hr 58 min"` that `parseResetMinutes()` (lines 48–77) would happily turn into 178. The current code unconditionally enriches at lines 214–216: `for (const m of data.meters) { if (m.reset) m.reset_minutes = parseResetMinutes(m.reset); }`.

The cache must therefore be written by a **Chrome extension older than HEAD**. The user installed the `0.11.0` `.deb`, which updated `/usr/share/claude-usage/chrome-extension/` to HEAD, but Chrome continues to run the version it loaded — there is no auto-reload on file change for unpacked extensions. The result: server is `0.11.0`, GNOME extension is `0.11.0`, Chrome extension is `0.10.x` or earlier. The user has no visible signal that anything is wrong; the panel happily shows colored bars from stale-shape data.

Downstream consequences:
- `_period_lengths` never accumulates → pacing calculations fall back to raw `pct` → the warning/critical thresholds (defined in pacing %) effectively become raw-% thresholds, which is a *different* color rule than the one documented in MANUAL.md.
- The "Max plan" mismatch hides any plan-tier-specific behavior the GNOME extension might want to gate on (none currently, but it limits future work).

**Fix:** add a `version` field to every Chrome POST and have the server check it. On mismatch, log a warning to the journal and (optionally) inject a synthetic `_anthropic_status.description = "Chrome extension v0.10.x outdated — reload chrome://extensions"` so the GNOME extension shows it in the broken-tier popup line. Manifest version is already available — just include it:

```js
// background.js, top of scrapeAndPost
const EXT_VERSION = chrome.runtime.getManifest().version;
// then in each POST body:
{ ...data, _ext_version: EXT_VERSION }
```

```python
# usage-server.py, _validate or do_POST
EXPECTED = '0.11.0'  # or read from a sibling VERSION file
if body.get('_ext_version') and body['_ext_version'] != EXPECTED:
    print(f"warning: ext_version mismatch: got {body['_ext_version']}, server is {EXPECTED}",
          file=sys.stderr, flush=True)
```

This is the minimal-touch fix. A nicer version surfaces the mismatch in `claude-usage-status` output ("Chrome extension: ⚠ v0.10.7 — server expects 0.11.0; reload chrome://extensions").

---

### S‑5 · `_anthropic_status` validator accepts unknown keys (Low)

**File:** `server/usage-server.py:100–111`

```python
astat = body.get('_anthropic_status')
if astat is not None:
    if not isinstance(astat, dict):
        return "'_anthropic_status' must be an object"
    for k in ('indicator', 'description', 'claude_ai_component_status'):
        err = _bounded_str(astat.get(k), f"_anthropic_status.{k}")
        if err:
            return err
    ind = astat.get('indicator')
    _VALID_INDICATORS = (None, 'none', 'minor', 'major', 'critical', 'maintenance')
    if ind not in _VALID_INDICATORS:
        return f"_anthropic_status.indicator must be one of {_VALID_INDICATORS}"
```

Only the three known keys are length-bounded. Any other key in `_anthropic_status` passes validation, is preserved through `body = {**prev, **body}`, and persists in `usage.json` forever. A malicious or buggy POST could include `_anthropic_status: {"junk": "x" * 100000}` (bounded only by the 256 KB whole-payload cap at line 150).

**Realistic exposure:** server binds to 127.0.0.1 and CORS guards Origin to `chrome-extension://*`, so the attack requires either a malicious Chrome extension already installed by the user (in which case they have bigger problems) or a process running as the user POSTing locally. Not a real attack vector.

**But:** if Anthropic adds new fields to the status-page response, the current code silently passes them through. That's actually a *feature* for forward-compat — but it means we should be deliberate. Either:
- Reject unknown keys: `if set(astat.keys()) - {'indicator', 'description', 'claude_ai_component_status'}: return "..."` (strict, breaks on Anthropic adding fields)
- Drop unknown keys: `body['_anthropic_status'] = {k: astat.get(k) for k in ('indicator', 'description', 'claude_ai_component_status')}` (forgiving, keeps cache clean) ← recommended

---

### S‑6 · `_period_lengths: {}` clobbers accumulated state (Low)

**File:** `server/usage-server.py:184–202`

```python
body = {**prev, **body}    # body['_period_lengths'] overrides prev['_period_lengths']
...
period_lengths = body.get('_period_lengths', {}) or {}    # gets body's value
```

If a POST includes `_period_lengths: {}` (empty), the merge replaces `prev`'s accumulated values with the empty dict, and the accumulation loop only re-fills from the current POST's meters. All historical max-reset_minutes data is lost.

The Chrome extension at HEAD does not include `_period_lengths` in its POST body (only the server populates it). The validator accepts `_period_lengths` as a top-level field (lines 112–123) without restricting writers. So a buggy or malicious POST can wipe the accumulator.

**Real impact:** zero today, because nothing sends it. Worth a 1-line fix while in the area:

```python
# Inside the merge, just before assignment:
period_lengths = prev.get('_period_lengths', {}) or {}
incoming = body.get('_period_lengths')
if incoming:    # merge, never replace with empty
    period_lengths.update(incoming)
```

---

### J‑2 · `extension.js::_spawnIconRegen` re-runs candidate probe (Low)

**Files:** `gnome-extension/extension.js:212–219`, `gnome-extension/prefs.js:10–16`

```js
// extension.js — probe on every tier transition
_spawnIconRegen(tier) {
    const candidates = [
        GLib.get_home_dir() + '/.local/share/claude-usage/generate-icon.py',
        '/usr/share/claude-usage/generate-icon.py',
    ];
    const script = candidates.find(p =>
        Gio.File.new_for_path(p).query_exists(null));
    ...
}

// prefs.js — probe at module load
const ICON_SCRIPT = _ICON_SCRIPT_CANDIDATES.find(
    p => GLib.file_test(p, GLib.FileTest.EXISTS)
) || _ICON_SCRIPT_CANDIDATES[0];
```

Trivial inconsistency. Tier transitions are rare (<5/day in normal use), so the cost is negligible — but two `query_exists` calls per transition is unnecessary, and asymmetry with `prefs.js` is exactly the kind of "why is this written two ways?" wart that prompts unnecessary re-reading by the next maintainer.

Also note the inconsistency in *which* probe API is used: `Gio.File.new_for_path().query_exists()` vs `GLib.file_test(GLib.FileTest.EXISTS)`. Pick one — the GLib one is cheaper and idiomatic for boolean existence checks. Both files should use the same form.

**Fix:** hoist to a module-level constant in `extension.js`, mirror `prefs.js`:

```js
const _ICON_SCRIPT_CANDIDATES = [
    GLib.get_home_dir() + '/.local/share/claude-usage/generate-icon.py',
    '/usr/share/claude-usage/generate-icon.py',
];
const ICON_SCRIPT = _ICON_SCRIPT_CANDIDATES.find(
    p => GLib.file_test(p, GLib.FileTest.EXISTS)
) || null;

// _spawnIconRegen becomes:
if (!ICON_SCRIPT) return;
Gio.Subprocess.new(['python3', ICON_SCRIPT, '--tier', tier], ...);
```

---

### I‑3 · `install.sh` apt-get fallback is Debian/Ubuntu-only (Low)

**File:** `install.sh:57–63`

```bash
_missing=()
python3 -c "import cairo" 2>/dev/null || _missing+=(python3-cairo)
python3 -c "import PIL"   2>/dev/null || _missing+=(python3-pil)
if [ ${#_missing[@]} -gt 0 ]; then
    echo "  Installing Python dependencies: ${_missing[*]}"
    sudo apt-get install -y "${_missing[@]}"
fi
```

A Fedora user runs `./install.sh`, hits this block, gets `sudo: apt-get: command not found`, and the install aborts. MANUAL.md's "Requirements" says "Ubuntu 22.04+", which is *technically* true, but `gnome-extension` and `usage-server.py` work fine on any GNOME-shipping distro — only the apt-get assumption blocks them.

**Fix:** detect package manager and either print actionable instructions or call the right one:

```bash
if command -v apt-get >/dev/null; then
    sudo apt-get install -y "${_missing[@]}"
elif command -v dnf >/dev/null; then
    sudo dnf install -y python3-cairo python3-pillow
elif command -v pacman >/dev/null; then
    sudo pacman -S --noconfirm python-cairo python-pillow
else
    echo "  ✗ Unknown package manager. Install: ${_missing[*]} manually and re-run."
    exit 1
fi
```

Low priority because the project's stated audience is Ubuntu, but the fix is small and the failure mode otherwise is opaque.

---

### A‑1 · Cache schema versioning still unaddressed (Informational)

**File:** `server/usage-server.py:209–213`, `gnome-extension/extension.js:254`

Raised in the [comprehensive review §5](2026-05-18-code-review-comprehensive.md), marked "informational" then; still unresolved. The cache shape has grown over the project: `meters`, `plan`, `_timestamp`, then `_period_lengths`, `_scrape_fail_count`, `_anthropic_status`. Any future addition or rename produces a silent half-state when a new-version reader sees an old cache or vice versa.

A 1-key `"_schema": 1` write at server-side + a `data._schema ?? 0` check in the GNOME extension's loader would let future versions detect-and-migrate or detect-and-warn. Cost: 5 lines.

Carried as Informational because the schema hasn't actually broken yet — it becomes Medium the moment the next field is added.

---

### T‑4 · `_validate()` still has zero unit tests (Informational)

**File:** `server/usage-server.py:49–129`

Raised in [pass 10](2026-05-17-code-review-pass10.md), again in the [comprehensive review §6](2026-05-18-code-review-comprehensive.md). 80 lines of input-validation contract, no Python test exercises it. The live-smoke test in CI hits one happy-path POST. Edge cases (bool-subclass `pct`, oversized strings, integer `reset_minutes` exactly at 44640 / 44641, `_period_lengths` exactly at 100/101 keys, all the `_bounded_str` paths, bool-subclass `_timestamp`) have never been exercised.

Recommended structure: a `server/tests/test_validate.py` with `pytest`, ~30 lines, covering each numbered failure path. The validator's failure-mode is "silent cache rejection with a journal-only error" — exactly the kind of surface where regressions go unnoticed until a user complains.

---

### C‑3 · CI live-smoke posts only the current shape (Informational)

**File:** `packaging/test-deb-live.sh:73–76`

```bash
run_as curl -sf -X POST "http://127.0.0.1:$PORT/update" \
    -H 'Content-Type: application/json' \
    -d '{"meters":[{"pct":42,"label":"live-smoke","reset":null}]}' >/dev/null
```

The probe is a minimal current-shape payload. It would **not** catch a regression where the server tightens validation in a way that breaks an older Chrome-extension POST shape (V‑1). A future fix to V‑1 should be paired with a CI probe that POSTs the *previous* shape too — explicitly, with `_period_lengths` absent and `reset_minutes` not enriched — and asserts the server accepts it (or rejects it cleanly, depending on the policy).

This isn't a bug today; it's a gap that becomes a bug the moment the validator is tightened.

---

## 4. Items Verified as Non-issues (12th pass — new investigations)

Sanity-checked during this pass and ruled out. Recorded so they don't surface again.

| Item | Verdict | Why |
|------|---------|-----|
| Scroll-handler stale `_data` race | Non-issue | GNOME main loop is single-threaded; scroll cannot interleave between `_loadData` callback and `_updateDisplay`. |
| 30 s tick does GSettings IPC even when no meters present | Non-issue | `s.get_uint('panel-icon-size')` is ~µs local D-Bus; even at 30 s cadence the cost is invisible. |
| Sync `GLib.file_set_contents` for notification TS files | Non-issue | Writes <16 bytes, at most once per 5 min per channel; sub-ms on a healthy disk. |
| `_updateDisplay` rewrites style/icon-size every tick | Non-issue | `St.Label.set_style` is a string-compare in Clutter, identical strings are a no-op; same for `set_icon_size`. No flash, no relayout. |
| `_flashSuppressed` lifecycle stuck-true | Non-issue | Reset at line 312 on the `anyCrit → !anyCrit` transition. Sequence stale→broken→normal→stale→broken correctly re-arms the flash. |
| Two Sonnet meters at 0% with one previously selected | Non-issue | `_getPrimary` falls through via `_isSelectable` to "All" then first-eligible. Confirmed by trace through lines 463–471. |
| `subprocess.Popen` of `generate-icon.py` from POST handler may flood | Non-issue | POST rate is 1 / 7 min from Chrome plus rare tier transitions; concurrent spawns are bounded by `_next_icon_path` using `time_ns()` for uniqueness and the 1 s grace cleanup window. |
| `_anthropic_status: {}` empty object validation edge case | Non-issue | `astat.get('indicator')` returns `None`; `None in _VALID_INDICATORS` is true; passes. Empty status object is identical to absent — no tier change. |
| `parse_reset` divide-by-zero / negative period | Non-issue | `tooltip.py:32` uses `max(0, ...)` on both elapsed and remaining; sign-flipped clocks produce 0:00, not a crash. |
| HTTP `do_POST` exception → 400 mask | Non-issue (carried) | Pass 7 noted this; covered by the explicit JSON/Unicode handlers at line 161–166; the outer `except Exception` catches programming errors which is correct for a long-running daemon. |

---

## 5. Architecture & Coverage Notes

**Cross-installer parity is the dominant theme of this pass.** I‑2, K‑3, K‑4 are all examples of the same root cause: three install paths (`install.sh`, `build-deb.sh` + `claude-usage-setup`, `build-chrome-zip.sh`) each implement "copy chrome-extension files, set up systemd, exclude test/" slightly differently, and the differences drift over time. The pass-11 fix to `claude-usage-setup` was the most recent example; before that, the chrome-zip's `test/` exclusion was the only path that got it right.

A shared helper (e.g., `packaging/lib.sh` with `install_systemd_unit()`, `copy_chrome_extension_payload()`) would prevent the next drift. Cost: one file. Value: every future install-path bug is closed in one place instead of three.

**The pass-11 R-1 root cause has a structural parallel.** R-1 was "the live system was never tested before release." V‑1 is "the live Chrome extension version was never checked against the server version." Both are the same class: a static review/test catches the contract on paper but not in the wild. The fix pattern is the same: add a runtime probe (live-smoke for R-1, version handshake for V-1) and surface mismatches loudly.

**Test coverage** continues to lean heavily on `scraper.test.js` (45 tests in the suite as of HEAD — pass 11 cited 44, one was added in the comprehensive-review fixes for JS-1). The validator and the GNOME extension's tier/pacing/flash logic remain untested. The validator is the higher-ROI test target (T‑4); the GNOME extension is harder because of the GJS/Shell embedding.

---

## 6. Recommended Action Order

| # | Priority | Effort | Action |
|---|----------|--------|--------|
| 1 | High | XS | **I‑2** — add `reset-failed` to `install.sh:107`. 1-line fix, mirrors `claude-usage-setup`. |
| 2 | Medium | XS | **E‑10** — track `_watchFile` retry source ID; cancel in `destroy()`. ~5 lines. |
| 3 | Medium | XS | **K‑3 + K‑4** — share a "copy chrome-extension excluding test/" helper between `install.sh` and `build-deb.sh`. |
| 4 | Medium | S | **E‑11** — defer the `panel-metric` clear via `GLib.idle_add` so it doesn't re-enter `_updateDisplay`. |
| 5 | Medium | S | **V‑1** — Chrome extension stamps `_ext_version` on POST; server logs mismatches; `claude-usage-status` surfaces them. |
| 6 | Low | XS | **S‑6** — change `_period_lengths` merge from replace-with-incoming to dict-update. |
| 7 | Low | XS | **S‑5** — drop unknown keys from `_anthropic_status` rather than passing them through. |
| 8 | Low | XS | **J‑2** — hoist `ICON_SCRIPT` to module scope in `extension.js`, mirror `prefs.js`. |
| 9 | Low | S | **I‑3** — detect package manager in `install.sh`; print actionable failure on unsupported distros. |
| 10 | Info | S | **A‑1** — add `_schema: 1` to cache writes; reader checks for unknown versions and warns. |
| 11 | Info | M | **T‑4** — `server/tests/test_validate.py` with pytest coverage of each `_validate` branch. |
| 12 | Info | XS | **C‑3** — add a second probe POST to `test-deb-live.sh` mimicking an older Chrome payload shape. |

**Effort key:** XS = 1–5 min · S = 15–30 min · M = 1–2 h

The first three items together are <10 min of work and close the entire cross-installer-parity class. Items 4–5 are the next-most-valuable: they address the two structural patterns (re-entrant render, silent version skew) that prior passes haven't seen because they only show up under specific runtime sequences.

---

## Appendix A — Verification commands

Reproducible end-to-end verification of each pass-11 fix on the current system:

```bash
# Pass-11 R-1 (must be active, not activating)
systemctl --user is-active claude-usage-fetch.service

# Pass-11 D-1 (must be empty — no "15 min" docstrings)
grep -n "15 min" server/*.py

# Pass-11 J-1 (must be empty — no radix-less parseInt)
grep -n 'parseInt(' gnome-extension/*.js chrome-extension/*.js | grep -v ', 10)'

# Pass-11 I-1 (must show StartLimitBurst=5)
grep -E "^StartLimit" systemd/claude-usage-fetch.service

# Pass-11 C-1 (must exist and be executable)
test -x packaging/test-deb-live.sh && echo present

# Pass-11 C-2 (must reference 25.10 image)
grep -c "ubuntu:25.10\|claude-usage-test:25.10" .github/workflows/release.yml
```

Reproducible verification of the new findings:

```bash
# I-2 — confirm install.sh missing reset-failed
diff <(grep -A3 'systemd/' install.sh | grep -E '^systemctl') \
     <(grep -E '^systemctl' packaging/claude-usage-setup)

# K-3 — confirm install.sh cp warning
( cd /tmp && mkdir -p cu-k3 && cp ~/SRC/claude-usage/chrome-extension/* cu-k3/ )

# V-1 — confirm version skew on live cache
python3 -c "
import json, re
d = json.load(open('$HOME/.cache/claude-usage/usage.json'))
print('plan:', d.get('plan'))
print('plan matches HEAD regex?:',
      bool(re.match(r'^(Max(\\s*\\([^)]+\\))?|Pro|Free|Team)\$', d.get('plan') or '')))
print('any reset_minutes populated?:',
      any('reset_minutes' in m for m in d.get('meters', [])))
print('period_lengths:', d.get('_period_lengths'))
"

# E-10 — confirm _watchFile retry id is discarded
grep -A4 'file monitor failed' gnome-extension/extension.js | grep -E 'this\._retryId|timeout_add'
```

---

## Appendix B — What this pass cost vs. what it caught

This pass took ~15 min of human-equivalent attention: one full read of every source file, one runtime probe of the live service, one targeted sub-agent investigation of GJS lifecycle, one diff against the pass-11 and comprehensive reviews to subtract already-known items.

It produced **13 new findings**, of which 1 is High (a 1-line fix) and 5 are Medium. The High finding (I‑2) is the kind of regression that would surface as a support ticket from the next source-install user who upgrades from a broken state — exactly the same failure mode pass 11 fixed for the .deb path, missed for the source path.

The take-away from running 12 passes on a small codebase: **diminishing returns are real but not yet exhausted.** Each pass finds fewer items, and the items shift from "obvious bug" to "subtle drift / cross-path inconsistency / structural debt". The signal-to-noise stays positive as long as the reviewer reaches past the previous pass's framing — pass 11 was a runtime-evidence pass, pass 12 was a cross-installer-parity + GJS-lifecycle pass. Future passes should pick a similarly fresh frame (e.g., "what's the lifecycle of state across Chrome extension reload + GNOME extension disable + service restart, simultaneously?") rather than re-read the same files looking for the same bugs.
