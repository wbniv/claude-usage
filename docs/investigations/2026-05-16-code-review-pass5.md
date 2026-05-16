# Code Review — Pass 5

**Date:** 2026-05-16
**Scope:** Independent comprehensive re-read of all source files after the pass-4 fix batch (`e704f14`), the runtime-cache consolidation (`758acfa`), the panel-metric scroll feature (`cca943c`), and the `.deb` smoke-test additions (`6423c03`..`0e9f8de`).
**Prior art:** Pass 1 (`2026-05-16-code-review.md`), Pass 2, Pass 3, Pass 4.

---

## Method

Read every source file end-to-end with fresh eyes; verified prior-pass fixes are still in place; flagged regressions, missed gotchas, and items only visible once the pass-4 fixes landed.

Files reviewed (full reads, not greps):
`chrome-extension/{background.js,manifest.json}`, `server/{usage-server.py,generate-icon.py}`, `gnome-extension/{extension.js,prefs.js,metadata.json,schemas/*.gschema.xml}`, `scripts/claude-usage-status.sh`, `install.sh`, `Taskfile.yml`, `packaging/{build-deb.sh,build-chrome-zip.sh,test-deb-verify.sh,test-deb.Dockerfile,postinst,postrm,control,claude-usage-setup}`, `systemd/claude-usage-fetch.service`, `desktop/claude-usage.desktop`, `MANUAL.md`, `PRIVACY.md`.

Each finding below is anchored to a precise file:line and (where non-obvious) accompanied by a reproducer or runtime check.

---

## Pass-4 Findings — Verified Current Status

| ID | Description | Status |
|----|-------------|--------|
| BUG-P4-1 | Tab listener `ReferenceError` deadlock | ✓ Fixed — `listener` is a `const` arrow function in enclosing scope (`background.js:42-54`) |
| BUG-P4-2 | `prefs.js` hardcoded source path for `generate-icon.py` | ✓ Fixed — dual-path probe at module load (`prefs.js:10-16`) |
| BUG-P4-3 | `.deb` omits `claude-usage-status` | ✓ Fixed — `install -m 755 ... /usr/bin/claude-usage-status` (`build-deb.sh:75`) |
| BUG-P4-4 | Threshold changes don't regen dock icon | ✓ Fixed — `addSpinRow` has `regen` param; thresholds pass `true` (`prefs.js:46-54, 97-99`) |
| BUG-P4-5 | `PRIVACY.md` drift | ✓ Fixed — paths and storage list accurate (`PRIVACY.md:23-26`) |
| BUG-P4-6 | Orphan tabs on SW suspend | ✓ Fixed — defensive sweep at top of `fetchUsage` (`background.js:29-32`) — **but introduces BUG-P5-4 below** |
| BUG-P4-7 | `MANUAL.md` settings table incomplete | ✓ Fixed — 4 panel-color/spacing rows added (`MANUAL.md:154-156, 161`) |
| Atomic write-then-rename | ✓ Fixed for both `usage.json` and `.desktop` (`usage-server.py:93-96`, `generate-icon.py:209-211`) |
| Request-size cap | ✓ Fixed — 256 KB guard (`usage-server.py:71-77`) — **but see BUG-P5-3** |
| Poll-timer removal | ✓ Done — file monitor is now the only update path (`extension.js:149-162`); `poll-interval` key absent from schema |
| Hoisted GSettings reads in `_updateDisplay` | ✓ Fixed — 8 settings snapshotted up front (`extension.js:192-200`) |
| String-length caps in `_validate` | ✓ Fixed — `MAX_STR_LEN = 128` applied to all string fields (`usage-server.py:17, 20-27`) |
| Stale-notification toast points at `claude-usage-status` | ✓ Fixed (`extension.js:216-217`) |
| `.deb` install smoke test | ✓ Implemented — `test-deb`, `test-deb-fast`, and shared `test-deb-verify.sh` |

---

## New Bugs

### BUG-P5-1 — High: `pct: true / false` passes `isinstance(int)` validation

**File:** `server/usage-server.py:41`

```python
pct = m.get('pct')
if not isinstance(pct, int) or not (0 <= pct <= 100):
    return f"meters[{i}].pct must be an integer in [0, 100]"
```

In Python, `bool` is a subclass of `int`. `isinstance(True, int) == True` and `0 <= True <= 100 == True` (True coerces to 1, False to 0). Verified:

```
isinstance(True, int): True
0 <= True <= 100: True
0 <= False <= 100: True
json.dumps({'pct': True}) == '{"pct": true}'
```

A POST with `{"meters":[{"pct":true,"label":"x"}]}` passes validation, is written to cache as `pct: true`, and the GNOME extension renders `${pct}%` as the literal string `"true%"` in the panel and `bar(true, 10)` as an all-empty bar (Math.round(true/100*10) = 0). The dock-icon `ring_color()` uses `pct >= cfg['threshold_warning']` which coerces — `True >= 50` is `False`, so the ring would render green even for "100% used".

**Reachability:** Only via a malicious local POST (the Chrome extension's `parseInt` never produces bool). Loopback-only binding plus 0o600 cache file means blast radius is one user account. Still a defense-in-depth gap — the validator's job is to reject malformed input, and it doesn't.

**Fix (1-liner):**

```python
if isinstance(pct, bool) or not isinstance(pct, int) or not (0 <= pct <= 100):
    return f"meters[{i}].pct must be an integer in [0, 100]"
```

The `isinstance(pct, bool)` check must come first because the bool/int subclass relationship means an `int` check alone won't catch it.

**Regression test:** `curl -X POST -H 'Content-Type: application/json' -d '{"meters":[{"pct":true,"label":"x"}]}' http://127.0.0.1:7331/update` — expect 422, observe 200 + corrupted display.

---

### BUG-P5-2 — High: `_fetching` deadlocks on `chrome.storage.local.get` throw

**File:** `chrome-extension/background.js:8-24`

```javascript
async function fetchUsage() {
  if (_fetching) return;
  _fetching = true;
  // ← here be dragons
  const { claude_usage: stored } = await chrome.storage.local.get('claude_usage');
  if (stored) {
    try { ... } catch (_) {}
  }
  ...
  try {
    tab = await chrome.tabs.create(...);
    ...
  } catch (err) { ... }
  finally {
    if (tab) { ... }
    _fetching = false;   // ← only reachable if the await above resolves
  }
}
```

The `_fetching = false` reset is in the `finally` of the *second* try block. The `await chrome.storage.local.get(...)` at line 11 runs **before** that try block. If it throws — quota exceeded, extension storage corrupted, MV3 API removal mid-update, async listener cancel — the error propagates out of `fetchUsage()`, the `finally` never runs, `_fetching` stays `true`, and every subsequent alarm-tick + toolbar-click early-returns until the service worker idle-suspends (~5 min) and restarts.

This is the same failure mode pass-4 closed for the listener-timeout path (BUG-P4-1) — caught there, missed here.

**Likelihood:** Low under normal conditions; the only documented `chrome.storage.local.get` throw is "Extension context invalidated" during reload. But the failure is symmetric to BUG-P4-1, and the fix is trivial.

**Fix:** Wrap the entire function body in the in-flight guard:

```javascript
async function fetchUsage() {
  if (_fetching) return;
  _fetching = true;
  try {
    // existing body — storage flush, defensive sweep, scrape, POST
  } finally {
    _fetching = false;
  }
}
```

The inner try/catch blocks for individual operations are still needed for graceful degradation; the outer try/finally is purely for the flag reset.

---

### BUG-P5-3 — Medium: Negative `Content-Length` bypasses the 256 KB cap

**File:** `server/usage-server.py:71-77`

```python
length = int(self.headers.get('Content-Length', 0))
if length > 256 * 1024:
    self.send_response(413)
    ...
    return
...
body = json.loads(self.rfile.read(length))
```

`int("-1")` is `-1`. The check `-1 > 262144` is `False`, so the guard passes. `self.rfile.read(-1)` then reads **until EOF** — i.e. unbounded.

Verified:

```
>>> length = -1
>>> length > 256 * 1024
False
```

**Reachability:** Same threat model as BUG-P5-1 — a malicious local process on the same machine. A network attacker can't reach the loopback port. Real-world risk is low. The fix is one extra condition:

```python
if length <= 0 or length > 256 * 1024:
    self.send_response(413)
    ...
    return
```

`length == 0` should also be rejected as malformed (POST with no body has no meters to write). Currently a zero-length body falls through to `json.loads(b'')` which raises `ValueError`, caught by the outer `except`, returns 400 — wrong status code for "missing body" but functionally correct.

---

### BUG-P5-4 — Medium: Defensive tab sweep closes user-opened usage tabs

**File:** `chrome-extension/background.js:29-32`

```javascript
// Defensive sweep: if a previous fetch was interrupted by SW suspension
// between tabs.create and the finally's tabs.remove, the orphaned tab is
// still open. Clean those up before opening a fresh one.
try {
  const stale = await chrome.tabs.query({ url: USAGE_URL });
  for (const t of stale) { try { await chrome.tabs.remove(t.id); } catch (_) {} }
} catch (_) {}
```

The query matches **any** tab whose URL equals `https://claude.ai/settings/usage`, including a tab the user opened manually (e.g. clicked "Open Usage Page" from the GNOME popup, or navigated there from claude.ai itself). The sweep closes those tabs without warning, twice an hour at minimum, every time the alarm fires.

The pass-4 fix solves a real problem (orphans from SW termination mid-scrape) but the cure has a strictly worse failure mode than the disease — a user has *no* observable harm from one orphan tab they can close manually, but a tab they're actively reading getting yanked closed every 15 minutes is data loss (lost scroll position, partial form input, etc.).

**Fix:** Track scrape-owned tab IDs in `chrome.storage.local`, sweep only those. Two storage I/Os per scrape vs. one cross-user-tab side effect — clear win.

```javascript
// startup recovery (top of fetchUsage):
const { _scrape_tabs = [] } = await chrome.storage.local.get('_scrape_tabs');
for (const id of _scrape_tabs) {
    try { await chrome.tabs.remove(id); } catch (_) {}
}
await chrome.storage.local.set({ _scrape_tabs: [] });

// when creating:
tab = await chrome.tabs.create({ url: USAGE_URL, active: false });
await chrome.storage.local.set({ _scrape_tabs: [tab.id] });

// finally:
if (tab) {
    try { await chrome.tabs.remove(tab.id); } catch (_) {}
    await chrome.storage.local.set({ _scrape_tabs: [] });
}
```

Alternative (simpler but uglier): append a unique fragment to the URL when creating (`https://claude.ai/settings/usage#claude-usage-scrape-${nonce}`) and match exact URL with fragment in the sweep. Chrome `tabs.query` URL matching does include fragments in the comparison when the pattern includes one, but the docs are ambiguous; the storage-based approach is more robust.

---

### BUG-P5-5 — Medium: Panel/popup desync when scrolled to a 0% Sonnet meter

**File:** `gnome-extension/extension.js:225-226, 102-106, 258-268`

The popup hides Sonnet at 0%:

```javascript
const visibleMeters = d.meters.filter(m =>
    !(m.label?.toLowerCase().includes('sonnet') && (m.pct ?? 0) === 0));
```

But the scroll handler's eligibility filter does not:

```javascript
const eligible = (this._data.meters || []).filter(m => this._isEligible(m));
// _isEligible only checks pct !== undefined, not pct !== 0
```

And `_getPrimary` honors the saved `panel-metric` without filtering:

```javascript
const found = meters.find(m => m.label === label && this._isEligible(m));
if (found) return found;
```

**Reproduction:**
1. Sonnet at 7%. User scrolls to Sonnet; panel shows "7%"; popup shows the Sonnet row.
2. Next fetch lands with Sonnet at 0%.
3. Panel re-renders: `_getPrimary` returns the Sonnet meter (still eligible) → panel shows "0%".
4. Popup re-renders with `visibleMeters` → Sonnet row gone.
5. User now sees "0%" in the panel for a meter that doesn't exist in the popup. The popup's `●` (active marker) appears on no row.
6. Scroll wheel works (eligible set includes 0% Sonnet), but the user can scroll *through* a hidden meter — the click rows in the popup don't include it.

**Recommended fix:** Make eligibility consistent with visibility — a meter that's hidden in the popup should not be a scroll-cycle candidate and should not be returned by `_getPrimary`. One line in `_isEligible` or a shared helper:

```javascript
_isSelectable(m) {
    if (m.label?.toLowerCase().includes('sonnet') && (m.pct ?? 0) === 0) return false;
    return this._isEligible(m);
}
```

Use `_isSelectable` in the scroll handler's filter and `_getPrimary`'s explicit lookup. Keep `_isEligible` as the structural-eligibility check (has pct or count/total) used elsewhere.

---

### BUG-P5-6 — Medium: Scroll wheel UP and DOWN both advance forward

**File:** `gnome-extension/extension.js:97-109`

```javascript
this.connect('scroll-event', (_actor, event) => {
    const dir = event.get_scroll_direction();
    if ((dir === Clutter.ScrollDirection.UP ||
         dir === Clutter.ScrollDirection.DOWN) && this._data) {
        ...
        const next = eligible[(idx + 1) % eligible.length];
        this._settings.set_string('panel-metric', next.label);
    }
    return Clutter.EVENT_STOP;
});
```

Both directions advance `idx + 1`. Convention in GNOME panel indicators (Network, Volume, Workspaces) is UP = previous, DOWN = next (mirrors the volume-slider mental model). With only two meters (the typical Max-plan case: "All" + "Sonnet") the bug is invisible — forward and backward end up at the same meter. With three or more eligible meters (e.g. Extra usage enabled), users will notice they can't cycle backward.

**Fix:**

```javascript
const delta = dir === Clutter.ScrollDirection.UP ? -1 : 1;
const next = eligible[(idx + delta + eligible.length) % eligible.length];
```

(`+ eligible.length` before `%` to handle the −1 case in JS, where `%` returns a negative remainder for negative operands.)

---

### BUG-P5-7 — Medium: Plan regex matches common English words

**File:** `chrome-extension/background.js:67-73`

```javascript
for (const line of lines) {
    if (/\b(Max|Pro|Free|Team)\b/.test(line) && line.length < 80) {
        plan = line;
        break;
    }
}
```

Tested against plausible page text:

| Line | Matches | Captured plan |
|------|---------|---------------|
| `Max (5x)` | ✓ | `Max (5x)` |
| `Pro tip: enable extra usage` | ✓ | `Pro tip: enable extra usage` |
| `Free trial expired` | ✓ | `Free trial expired` |
| `Get max value from your subscription` | ✗ (lowercase) | — |

The check is case-sensitive (good) and word-bounded (good), but "Pro", "Free", and "Team" are common enough that any marketing copy or banner that appears before the actual plan label will hijack the field. The captured plan name then surfaces in the popup status line (`plan + " · " + age`) and in `format_tooltip` for the dock launcher.

**Reachability:** Depends on claude.ai's page layout. The current scrape works because today the plan name appears early; one A/B test or banner change breaks it silently. There is no validation in `_validate()` — `plan` is just bounded to 128 chars now (good) but is otherwise free-form.

**Fix:** Narrow the match to known patterns and anchor on context:

```javascript
// Try first: explicit "Plan: X" or X followed by parens (e.g. "Max (5x)")
for (const line of lines) {
    const m = line.match(/^(?:Plan:\s*)?(Max(?:\s*\([^)]+\))?|Pro|Free|Team)$/);
    if (m && line.length < 40) { plan = m[1]; break; }
}
```

Or look only at lines within a few rows of the "Plan usage limits" anchor (which is already found at `planStart`).

---

## Code Quality

### Subprocess zombie accumulation

**File:** `server/usage-server.py:99-100`

```python
subprocess.Popen([sys.executable, str(GENERATE_ICON)],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

The returned `Popen` object is discarded immediately. Without an explicit `.wait()` or `.poll()`, the child becomes a zombie until reaped. CPython's `subprocess._cleanup()` does opportunistic reaping when a *new* `Popen` is constructed, so at the 15-minute scrape cadence each zombie persists for one cycle.

**Impact:** One stale entry in `ps`, ~1 KB kernel structure per zombie. Cosmetic, not a leak — bounded at one zombie at any given moment.

**Fix (one line, at module load):**

```python
import signal
signal.signal(signal.SIGCHLD, signal.SIG_IGN)
```

This tells the kernel to auto-reap children. Alternative: store the `Popen` in a list and `.poll()` it on the next request.

---

### `release` task doesn't verify a clean working tree

**File:** `Taskfile.yml:78-99`

The release task currently checks two things: refusing to release from non-main, and refusing to retag an existing tag. It does **not** check `git status` — a developer with uncommitted changes can `task release` and ship a `.deb` built from the working-tree state, but the git tag points to the last-committed HEAD. The shipped artifact and the source at the tag will not match.

**Fix:** Add to the existing pre-check block (line 82):

```bash
if ! git diff --quiet HEAD; then
  echo "Refusing to release with uncommitted changes:"
  git status --short
  exit 1
fi
```

(Note: `git diff --quiet` exits 1 on dirty tree; with `set -e` the script aborts automatically, but the explicit error message is friendlier.)

---

### `_loadData` swallows all errors silently

**File:** `gnome-extension/extension.js:164-173`

```javascript
_loadData() {
    try {
        const f = Gio.File.new_for_path(CACHE_FILE);
        const [ok, contents] = f.load_contents(null);
        if (!ok) return;
        const text = new TextDecoder().decode(contents);
        this._data = JSON.parse(text);
        this._updateDisplay();
    } catch (_e) {}
}
```

A corrupt cache JSON (mid-write race, disk-full truncation, manual hand-edit) silently fails. The panel keeps showing the previously-loaded data; the user has no signal that the file is corrupt. The next successful POST overwrites the corruption, so this is rarely observable — but when it does bite, debugging is hard.

**Fix:** Log to the journal via `logError` (already used in `_watchFile`):

```javascript
} catch (e) {
    logError(e, 'ClaudeUsage: failed to read cache');
}
```

Visible in `journalctl --user-unit=gnome-shell -f` for diagnostic purposes. Not surfaced to the user.

---

### Pillow `Image.LANCZOS` is deprecated

**File:** `server/generate-icon.py:133`

```python
img.resize((128, 128), Image.LANCZOS).save(dest)
```

Pillow 9.1 added `Image.Resampling.LANCZOS` and deprecated the top-level alias. Pillow 10 emits a `DeprecationWarning`; Pillow 11 (released 2024-10) still allows both. Ubuntu 24.04 ships Pillow 10.x via `python3-pil`. The deprecation won't break the build today, but Ubuntu 26.04+ might.

**Fix:** Use the new path with a fallback for old Pillow:

```python
RESAMPLE = getattr(Image, 'Resampling', Image).LANCZOS
img.resize((128, 128), RESAMPLE).save(dest)
```

---

### `claude-usage-status.sh` invokes Python 3× on the same cache file

**File:** `scripts/claude-usage-status.sh:32-67`

Three separate `python3 - <<EOF` heredocs open and parse the same JSON for `ts`, `plan`, and the meter list. Python startup is ~30 ms per invocation; total ~100 ms wasted on a tool intended for fast diagnostics.

**Fix:** One heredoc producing all three values, parsed in shell with `read`. Or just print a formatted multi-line block from Python and let shell display it directly. Low priority — this is a `-h`-able utility, not a hot path.

---

### `_next_icon_path` imports `time` inside the function

**File:** `server/generate-icon.py:135-141`

```python
def _next_icon_path():
    import time
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f'icon-{time.time_ns()}.png'
```

Other functions (`parse_reset`, the implicit `datetime` import) use module-level imports. The inline `import time` here is harmless (subsequent calls are cached lookups) but inconsistent. Move to the top.

---

### `ring_color` defensive `.get(..., default)` is unreachable

**File:** `server/generate-icon.py:67-70`

```python
def ring_color(pct, cfg):
    if pct >= cfg.get('threshold_critical', 80): ...
    if pct >= cfg.get('threshold_warning',  50): ...
```

`load_config()` unconditionally populates both keys (from GSettings on the success path; from `DEFAULTS` in the except path, which also has them). The `.get` defaults are dead defense. Either trust the contract and use `cfg['threshold_critical']`, or make `load_config`'s contract optional with a `# may be missing` doc — not both.

---

### `update_desktop` Name= field is also the GNOME Activities search match

**File:** `server/generate-icon.py:200, 196`

`Name=` is overwritten with the live tooltip text (`current 5% | all 23% ⏱4:23`). The Name field is also what GNOME Shell's Activities overview indexes for search. Typing "Claude" still matches via the `Claude` substring of `Claude.ai` (in `Comment=`), but the search result title shows the live tooltip — not "Claude Usage". Cosmetic but jarring.

**Fix:** Set `Name=Claude Usage` (static) and `GenericName=` to the live tooltip — or move the dynamic text to `Comment=` (which most launchers use as hover-tooltip secondary text). GNOME-shell dock's tooltip-on-hover behavior would need a quick test to confirm `GenericName`/`Comment` shows up correctly. Out of scope to verify here; flag for follow-up.

---

### `panel-icon-size` requires extension reload despite being live-changeable

**File:** `gnome-extension/extension.js:113-117`, `schemas/*.gschema.xml:82`

```javascript
this._icon = new St.Icon({
    gicon: Gio.icon_new_for_string(ext.path + '/icons/claude-22.png'),
    icon_size: this._settings.get_uint('panel-icon-size'),
    ...
});
```

The size is read once at init. The schema description and the prefs subtitle both say "requires extension reload". But `St.Icon.set_icon_size(n)` exists and works live. The only thing blocking a live update is the missing `changed::panel-icon-size` connect.

**Fix:** Add a one-line specific listener (or fold into the existing `changed` connect which calls `_updateDisplay`, plus update `_updateDisplay` to call `this._icon.set_icon_size(...)`):

```javascript
this._settings.connect('changed::panel-icon-size',
    () => this._icon.set_icon_size(this._settings.get_uint('panel-icon-size')));
```

Then drop "requires extension reload" from schema summary and prefs subtitle.

---

## Security

### No new attack surface

All pass-1 through pass-4 security properties verified intact: cache file `0o600`, schema validation rejects most malformed input (modulo BUG-P5-1 and BUG-P5-3 above), percentage clamping at scrape time, server bound to 127.0.0.1.

### Recommended systemd hardening

**File:** `systemd/claude-usage-fetch.service`

The current unit has no sandboxing. Defense in depth for a localhost-only HTTP server is cheap:

```ini
[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/.local/share/claude-usage/usage-server.py
Restart=always
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.cache/claude-usage %h/.local/share/applications
ProtectKernelTunables=true
ProtectKernelModules=true
RestrictAddressFamilies=AF_UNIX AF_INET
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
```

Notes:
- `ReadWritePaths` must include `%h/.local/share/applications` because `generate-icon.py` updates the `.desktop` file there.
- `RestrictAddressFamilies=AF_INET` blocks accidental IPv6 socket creation; AF_UNIX kept for D-Bus.
- `MemoryDenyWriteExecute=true` is a Python-friendly hardening (CPython doesn't JIT).

Not a bug; defense in depth.

### `SO_REUSEADDR` would smooth service restarts

**File:** `server/usage-server.py:120`

```python
server = HTTPServer(('127.0.0.1', PORT), Handler)
```

`HTTPServer` inherits `allow_reuse_address = True` from `TCPServer` since Python 3.7? Actually verified: `HTTPServer` in `http.server` overrides `allow_reuse_address = 1` explicitly. So this is already taken care of — no action needed. (Noting because pass 4 did not call this out and it deserves explicit confirmation.)

---

## Architecture Observations

### No CI; manual smoke test is opt-in

`task test-deb` and `task test-deb-fast` exist and are well-built (shared `test-deb-verify.sh`, prebaked image variant for fast iteration). But `release` doesn't depend on either, and there's no GitHub Actions workflow. Pass 4 made the same observation; still applies.

Cheapest next step: a single GitHub Actions workflow on tag push that runs `task test-deb-fast` (or even just `task test-deb` cold, ~7 min) and uploads the `.deb` to the release. Two artefacts — `.deb` and `.zip` — both already built locally.

### `metadata.json` version field is stale

**File:** `gnome-extension/metadata.json:7`

`"version": 1`. This is the GNOME extension version (an integer, per the GNOME extensions spec — independent of semver). It's never incremented. For self-hosted extensions this is harmless (GNOME Shell doesn't compare versions across releases when loading by path). For an extensions.gnome.org submission, the field is checked and a stale value blocks publication.

Not a current bug. Flag for whenever EGO publication enters scope.

### Source vs `.deb` install both create user-systemd unit

If a user does both `./install.sh` and later `dpkg -i claude-usage_*.deb`:
- `install.sh` writes `~/.config/systemd/user/claude-usage-fetch.service` with `ExecStart=python3 %h/.local/share/claude-usage/usage-server.py`
- `.deb` writes `/usr/lib/systemd/user/claude-usage-fetch.service` with `ExecStart=python3 /usr/share/claude-usage/usage-server.py`

User units in `~/.config/` override `/usr/lib/`. The source-install unit wins; the user runs the source-install server, not the `.deb` one. The `.deb`'s `claude-usage-status` reports "running" but it's running the wrong code path.

`./install.sh --uninstall` removes the user unit, restoring the `.deb` path. But during overlap, the two installs are silently conflated.

Acceptable for the intended audience (don't do both). Worth a sentence in MANUAL.md: "Use one install method or the other — running both creates a precedence conflict."

---

## Verified-OK (pass 4 fixes confirmed in current source)

| Item | File:Line | Status |
|------|-----------|--------|
| `const` listener in scope for both branches | `background.js:42-54` | ✓ |
| `prefs.js` dual-path probe | `prefs.js:10-16` | ✓ |
| `claude-usage-status` shipped in .deb | `build-deb.sh:75` | ✓ |
| `addSpinRow regen` for thresholds | `prefs.js:46-54, 97-99` | ✓ |
| `PRIVACY.md` paths current | `PRIVACY.md:23-26` | ✓ |
| Atomic JSON write | `usage-server.py:93-96` | ✓ |
| Atomic .desktop write | `generate-icon.py:209-211` | ✓ |
| 256 KB request cap | `usage-server.py:71-77` | ✓ (but see BUG-P5-3 for the negative-length edge) |
| String-length cap on all string fields | `usage-server.py:17, 20-27` | ✓ |
| Hoisted GSettings reads in `_updateDisplay` | `extension.js:192-200` | ✓ |
| Stale toast points at `claude-usage-status` | `extension.js:216-217` | ✓ |
| `.deb` install smoke test | `Taskfile.yml:24-72`, `packaging/test-deb-verify.sh` | ✓ |
| Defensive sweep present | `background.js:29-32` | ✓ (introduces BUG-P5-4) |
| Poll-timer removal | `extension.js`, schema | ✓ |
| `update_desktop` comment passthrough | `generate-icon.py:204-205` | ✓ |
| Time-ns icon path | `generate-icon.py:135-141` | ✓ |

---

## Priority Summary

| Priority | Count | Items |
|----------|-------|-------|
| **High** | 2 | BUG-P5-1 (bool/int validation), BUG-P5-2 (`_fetching` storage-throw deadlock) |
| **Medium** | 5 | BUG-P5-3 (negative Content-Length), BUG-P5-4 (sweep closes user tabs), BUG-P5-5 (panel/popup desync), BUG-P5-6 (scroll direction), BUG-P5-7 (plan regex) |
| **Code quality** | 8 | Subprocess zombies; release dirty-tree guard; `_loadData` logging; Pillow LANCZOS; status.sh Python invocations; `import time` placement; ring_color dead defaults; live `panel-icon-size` |
| **Security** | 1 | Optional systemd hardening (defense in depth, not a bug) |
| **Architecture** | 3 | No CI; metadata.json version stale; source+.deb conflict (doc-only) |

---

## Overall Assessment

**Grade: A−**

Pass 4 left the project at A; pass 5 finds **two new High-severity bugs** that were below the previous passes' attention:

1. **BUG-P5-1** is a Python language gotcha (`bool` ⊂ `int`) — the validator was written correctly against the intent but not against the language. One-line fix.
2. **BUG-P5-2** is the same shape as the pass-4 listener leak (BUG-P4-1): an `await` outside the try/finally that resets the in-flight flag. The fix is structural (move the flag reset into a wrapping try/finally), not a one-liner addition.

Neither is a regression from pass-4 work — they're both pre-existing bugs that previous passes happened not to find. The medium-severity finds are largely about edge cases exposed by recent feature work:
- **BUG-P5-4** is a side effect of the pass-4 defensive sweep (BUG-P4-6 fix) — the sweep is too aggressive.
- **BUG-P5-5 and BUG-P5-6** are exposed by the new panel-metric scroll feature (`cca943c`). The feature's eligibility/filtering logic isn't consistent across the three sites that use it.

The codebase remains overall in very good shape — small, well-organized, and the architectural choices (file-monitor over polling, atomic writes, schema-validated POST, `0o600` cache) hold up. The pattern emerging across five passes is that each round finds 2–4 real issues; this is expected for a mostly-stable codebase still gaining minor features.

### Recommended fix order

1. **BUG-P5-1** — defense-in-depth one-liner, ship same PR as any other server change.
2. **BUG-P5-2** — restructure `fetchUsage` to wrap the whole body in `try/finally`. Same PR as P5-1 if convenient (different files).
3. **BUG-P5-6** — scroll direction fix; 2 lines. Trivial.
4. **BUG-P5-4** — storage-backed orphan-tab tracking; ~10 lines.
5. **BUG-P5-5** — `_isSelectable` helper unified across scroll, `_getPrimary`, popup filter. ~5 lines.
6. **BUG-P5-3** — `length <= 0` guard. One line.
7. **BUG-P5-7** — narrower plan regex. ~3 lines.

### To reach A+

- GitHub Actions wiring `test-deb-fast` on tag push.
- Pillow `LANCZOS` migration (forward-compat).
- Live `panel-icon-size` update (correctness — schema currently lies).
- Live tooltip via `GenericName`/`Comment` rather than overwriting `Name=` (Activities search hygiene).
- Source vs `.deb` install conflict noted in MANUAL.md.
