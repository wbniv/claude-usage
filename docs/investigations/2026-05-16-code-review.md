# Code Review — claude-usage

**Date:** 2026-05-16  
**Scope:** Exhaustive review of all source files  
**Reviewer:** Claude Code

---

## Project Purpose

`claude-usage` is a Linux (GNOME) system indicator that displays Claude.ai API usage
percentages in real-time. Four integrated components collaborate to show a live percentage
label in the GNOME top panel and a color-coded icon in the application dock.

---

## Architecture

```
Chrome Extension (15-min scrape)
        │  POST JSON
        ▼
usage-server.py  (127.0.0.1:7331)
        │  writes
        ├──▶ ~/.cache/claude-usage.json
        │         │  file-watch (GLib.FileMonitor)
        │         └──▶ GNOME Extension (panel label + popup)
        │  spawns
        └──▶ generate-icon.py
                  │  writes alternating PNG + updates Icon= in
                  └──▶ ~/.local/share/applications/claude-usage.desktop
```

**Data flow:** Chrome Extension → localhost:7331 → cache JSON → GNOME extension + icon
generator.

**Four independent processes:** Chrome, systemd user service, GNOME Shell, and the icon
generator subprocess. If any one fails, the panel shows "--" with no error surfaced to the
user.

---

## File Inventory

| File | Role |
|---|---|
| `chrome-extension/manifest.json` | MV3 extension manifest; host perms for 127.0.0.1:7331 and claude.ai |
| `chrome-extension/background.js` | Scraper, 15-min alarm scheduler, chrome.storage.local fallback |
| `server/usage-server.py` | HTTP POST handler; writes cache; spawns icon generator |
| `server/generate-icon.py` | Cairo + PIL dock icon renderer; updates .desktop Icon= field |
| `gnome-extension/extension.js` | Panel indicator, popup menu, file watcher, poll timer |
| `gnome-extension/prefs.js` | GSettings preferences UI (colors, thresholds, fonts) |
| `gnome-extension/metadata.json` | UUID: `claude-usage@indri.studio`; GNOME 45–49 |
| `gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml` | 14 GSettings keys |
| `install.sh` | Source-install and uninstall script |
| `packaging/build-deb.sh` | Debian package builder |
| `packaging/claude-usage-setup` | Per-user setup script invoked by the .deb postinst |
| `packaging/control` | Debian metadata, v0.9, python3-cairo + python3-pil deps |
| `packaging/postinst` / `postrm` | Debian lifecycle hooks |
| `Taskfile.yml` | `build-deb`, `build-chrome-zip` tasks |
| `MANUAL.md` | User documentation |
| `PRIVACY.md` | Chrome Web Store privacy disclosure |

---

## Bugs

### ~~BUG-1 — Critical: Extension UUID mismatch in .deb setup script~~ ✓ Fixed

**File:** `packaging/claude-usage-setup:45`  
**Symptom:** `.deb` install completes without error but the GNOME extension is never
enabled; panel indicator never appears.  
**Cause:** `gnome-extensions enable claude-usage@wbnorris.gmail.com` — the argument uses
the old email-based UUID, not the actual UUID `claude-usage@indri.studio` declared in
`gnome-extension/metadata.json`.  
**Fix:**
```bash
gnome-extensions enable claude-usage@indri.studio 2>/dev/null \
```

### ~~BUG-2 — High: generate-icon.py crashes on first run (missing cache file)~~ ✓ Fixed

**File:** `server/generate-icon.py:194`  
**Symptom:** Icon generator exits with `FileNotFoundError` before any fetch has populated
the cache; user sees no dock icon until the first successful scrape cycle.  
**Cause:** `CACHE_JSON.read_text()` is called unconditionally; no existence check precedes
it.  
**Fix:** Add an early exit (or placeholder icon) when the cache is absent:
```python
if not CACHE_JSON.exists():
    sys.exit(0)  # nothing to render yet; not an error
data = json.loads(CACHE_JSON.read_text())
```
Alternatively, pre-create a zero-percent placeholder at install time.

### ~~BUG-3 — High: BASE_ICON lookup raises StopIteration on partial install~~ ✓ Fixed

**File:** `server/generate-icon.py:12–20`  
**Symptom:** Cryptic `StopIteration` traceback when neither the user-install nor the
system path contains the GNOME extension icon.  
**Cause:** `next(p for p in [...] if p.exists())` has no default; bare `next()` on an
exhausted iterator raises `StopIteration`.  
**Fix:**
```python
BASE_ICON = next((p for p in CANDIDATES if p.exists()), None)
if BASE_ICON is None:
    sys.exit(f"error: base icon not found in any candidate path")
```

### ~~BUG-4 — Medium: Weekday numbering inconsistency between Python and JavaScript~~ ✗ Not a bug

**Retracted.** The two implementations use different but internally consistent conventions:
Python dict maps Mon=0…Sun=6 matching `datetime.weekday()`; JS `wdMap` maps Sun=0…Sat=6
matching `getDay()`. Verified with test cases (Sunday→Monday, Wednesday→Monday): both
produce identical `ahead` values. The original review made an arithmetic error by applying
the JS mapping to the Python calculation.

### BUG-5 — Low: Sonnet ring ignores warning/critical color thresholds (by design)

**File:** `server/generate-icon.py:109`  
**Resolution:** Intentional design — blue always = Sonnet so users can distinguish the two
rings by color family at a glance. A clarifying comment has been added to the source. No
behavior change.

### ~~BUG-6 — Low: Chrome scraper DOM index lacks lower-bound guard~~ ✗ Not a bug

**Retracted.** Every `lines[i-1]` access is guarded by `i >= 1` and every `lines[i-2]`
access is guarded by `i >= 2` — verified by reading lines 46–54, 62–70, and 80–88 of
`chrome-extension/background.js`. Guards were already consistently applied.

---

## Code Quality Issues

### ~~Silent error swallowing in the HTTP server~~ ✓ Fixed

**File:** `server/usage-server.py`  
Returns 400 on parse/write failure; returns 415 if Content-Type is not `application/json`.
Error is still logged to stderr. Chrome extension's `if (!resp.ok)` branch will now trigger
correctly on failure and fall back to `chrome.storage.local`.

### Concurrent icon generator spawns — theoretical, not fixing

**File:** `server/usage-server.py:30–31`  
The 15-minute Chrome alarm makes two concurrent POST requests essentially impossible in
normal use. The race (last-writer-wins on the PNG) is real in theory but has no practical
consequence. Not worth the complexity of a lock.

### ~~GSettings defaults duplicated in two languages~~ ✓ Fixed

Added `# keep in sync with gschema.xml default= attributes` comment on the `DEFAULTS` dict
in `generate-icon.py` to make the coupling explicit.

### Hardcoded English weekday strings — not applicable

`parse_reset` parses text scraped from `claude.ai`, which is always served in English
regardless of system locale. Hardcoded English abbreviations are correct; `calendar.day_abbr`
would be wrong here.

### Magic numbers in extension.js — already resolved

All significant UI dimensions (`panel-icon-size`, `panel-font-size`, `panel-label-spacing`,
`bar-width`, `popup-font-size`, `popup-font-family`) are now GSettings keys. The remaining
literals (`0.0` alignment, `0, 'right'` panel position) are fixed layout constants, not
configurable values. Nothing to do.

### ~~No validation of hex color strings from GSettings~~ ✓ Fixed

`load_config()` now validates each color string by calling `hex_to_rgba()` on it; any that
raise fall back to the `DEFAULTS` value. Bad prefs input can no longer crash the icon
generator.

---

## Security Observations

### ~~Cache file permissions (Medium)~~ ✓ Fixed

**File:** `server/usage-server.py:27`  
`Path.write_text()` inherits the process umask (typically 0644 — world-readable). The
cache contains the user's plan type, API usage percentages, and remaining balance — all
mildly sensitive. Fix:
```python
OUTPUT.write_text(json.dumps(data, indent=2))
os.chmod(OUTPUT, 0o600)
```

### ~~Unauthenticated local POST endpoint (Low)~~ ✓ Partially fixed

Content-Type is now validated — requests without `application/json` receive 415. Full
schema validation of the JSON body would add more hardening but is not implemented (low
practical risk given loopback-only binding).

### ~~Percentage values not bounds-checked (Low)~~ ✓ Fixed

All three `pct` assignments in `background.js` (Section 1, Section 2 count-based, Section 3
extra usage) now clamp with `Math.min(100, Math.max(0, ...))`. Out-of-range values from the
page can no longer propagate into the cache or display.

---

## Missing Features / Implied TODOs

| # | Gap | Status |
|---|---|---|
| ~~1~~ | ~~Stale-data warning~~ | ✓ Fixed — `⚠` prefix in popup status item when data > 30 min old (`extension.js`) |
| ~~2~~ | ~~Chrome storage → GNOME bridge~~ | ✓ Fixed — flush `chrome.storage.local` data to server at the start of each fetch cycle (`background.js`) |
| 3 | Chrome Web Store publication | Documented in MANUAL.md — external process requiring developer account ($5) |
| ~~4~~ | ~~Config validation UI~~ | ✓ Already resolved — color inputs use `Gtk.ColorDialogButton` (native picker, can't produce invalid hex); server-side validation added in previous pass |
| 5 | Locale/timezone detection | Documented in MANUAL.md — browser timezone matches system timezone in practice (GNOME controls both); only breaks if browser timezone is manually overridden |
| ~~6~~ | ~~Diagnostics command~~ | ✓ Fixed — `scripts/claude-usage-status.sh`; installed to `~/.local/bin/claude-usage-status` by `install.sh` |

---

## Non-obvious Design Decisions (Worth Preserving)

### Alternating PNG filenames for icon cache busting

`generate-icon.py` alternates between `claude-usage-icon-a.png` and `claude-usage-icon-b.png`
on each write, then updates the `Icon=` line in the `.desktop` file to the new path.
This is a deliberate workaround: GNOME caches `.desktop` icons by filename and does not
invalidate on file modification time alone. Changing the filename forces a reload.
**Do not "simplify" this to a single fixed filename — the icon will stop updating.**

### File watcher + poll timer redundancy

`extension.js` uses both a `GLib.FileMonitor` (immediate response to cache writes) and a
configurable poll timer (default 5 min). The watcher is primary; the timer is a safety net
for missed `CHANGES_DONE_HINT` events (known GLib edge case on some filesystems). Both
are intentional.

### Two-library image pipeline

`generate-icon.py` uses Cairo (`ImageSurface`) for vector drawing and PIL for the final
PNG resize. Cairo is used for its arc/stroke API; PIL is used because Cairo's PNG writing
does not easily support palette or resize operations at the correct output size. This
two-library approach is intentional, not redundant.

---

## Dependency Summary

| Dependency | Source | Version constraint |
|---|---|---|
| Python | system | ≥3.8 |
| python3-cairo | apt | any |
| python3-pil | apt | any |
| GNOME Shell | system | 45–49 (metadata.json) |
| systemd (user) | system | any |
| Chrome / Chromium | user-installed | MV3 support |

No PyPI packages. All Python stdlib. Minimal footprint — good for distro packaging.

---

## Priority Summary

| Priority | Count | Items | Status |
|---|---|---|---|
| Critical (blocks release) | 1 | BUG-1: UUID mismatch in .deb | ✓ Fixed |
| High (crash/data loss) | 2 | BUG-2: missing cache guard; BUG-3: StopIteration | ✓ Fixed |
| Medium (correctness) | 2 | ~~BUG-4: weekday inconsistency~~ (not a bug); cache file permissions | ✓ Fixed |
| Low (quality/safety) | 4 | BUG-5: by design (comment added); ~~BUG-6: DOM index~~ (not a bug); bounds-check %; CORS | Partial |
| Nice-to-have | 6 | See Missing Features table | Open |

---

## Overall Assessment

**Grade: B+**

Architecture is clean and well-separated. Configuration surface via GSettings is solid.
The loopback-only server, systemd user service, and file-watcher design are all appropriate
choices. Plans in `docs/plans/` show that recent work was methodical.

**Before the next .deb release:** fix BUG-1 (UUID), BUG-2 (crash on first run), and
set cache file permissions to 0600. The rest can follow.
