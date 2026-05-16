# Code Review — Pass 2

**Date:** 2026-05-16  
**Scope:** Fresh exhaustive re-read of all source files against the current state of the repo  
**Prior art:** `2026-05-16-code-review.md` (pass 1 — all issues there are verified closed)

---

## What This Pass Does

Pass 1 found and fixed 7 bugs plus code quality / security issues. This pass reads every
file independently and asks: what did pass 1 miss?

Findings are ordered by severity.

---

## Bugs

### BUG-P2-1 — Medium: `claude-usage-setup` creates a config.json that nothing reads

**File:** `packaging/claude-usage-setup:7–18`

The per-user .deb setup script writes a JSON color config:

```bash
cat > "$HOME/.config/claude-usage/config.json" <<'EOF'
{
  "weekly_color_green": "#8cff8c",
  ...
}
EOF
```

Since the GSettings migration (`docs/plans/2026-05-16-configurable-ux-vars.md`),
`generate-icon.py::load_config()` reads exclusively from
`Gio.Settings.new('org.gnome.shell.extensions.claude-usage')`. `config.json` is never opened
by any current code path. A user who edits this file expecting it to change ring colors will
see no effect, and there is no error or warning to tell them why.

**Impact:** Silent user-visible failure if anyone follows old documentation or intuition to
edit the config file.

**Fix:** Replace the file-creation block with the equivalent `gsettings set` calls (so the
.deb install path lands on the same source of truth as install.sh), or remove it entirely
and add a comment pointing to `gnome-extensions prefs claude-usage@indri.studio`.

---

### BUG-P2-2 — Medium: `packaging/control` version out of sync with Chrome extension

**Files:** `packaging/control:2`, `chrome-extension/manifest.json:4`

```
packaging/control          Version: 0.9
chrome-extension/manifest  "version": "1.0"
```

The `dist/` directory already contains `claude-usage_1.0_all.deb`, confirming a 1.0 build
was done at some point, but `packaging/control` was never bumped to match. The next `task
build` will produce a 0.9 .deb from 1.0 Chrome extension source.

**Fix:** Bump `packaging/control` to `Version: 1.0`.

---

### BUG-P2-3 — Low: `install.sh --uninstall` misses the alternating icon files

**File:** `install.sh:33`

The uninstall path removes `~/.cache/claude-usage-icon.png` (the old, non-alternating name)
but not the files actually written by the current `generate-icon.py`:

```bash
rm -f "$HOME/.cache/claude-usage-icon.png"    # old name — never written now
# missing:
# rm -f "$HOME/.cache/claude-usage-icon-a.png"
# rm -f "$HOME/.cache/claude-usage-icon-b.png"
```

After `./install.sh --uninstall`, the alternating icon PNGs remain in `~/.cache/`.

**Fix:**
```bash
rm -f "$HOME/.cache/claude-usage-icon.png" \
      "$HOME/.cache/claude-usage-icon-a.png" \
      "$HOME/.cache/claude-usage-icon-b.png"
```

---

### BUG-P2-4 — Low: `claude-usage-setup` desktop icon path uses the old filename

**File:** `packaging/claude-usage-setup:31`

The initial `.desktop` file written by `claude-usage-setup` is:

```
Icon=$HOME/.cache/claude-usage-icon.png
```

`generate-icon.py` no longer writes `claude-usage-icon.png`. It writes to
`claude-usage-icon-a.png` / `claude-usage-icon-b.png` and updates the `Icon=` field in the
desktop file — but **only when the cache JSON exists** (i.e., after the first Chrome scrape).

Because step 5 of `claude-usage-setup` runs `python3 ... generate-icon.py 2>/dev/null || true`
immediately after install (before any scrape has run), and `generate-icon.py` exits early
when the cache is absent, the `Icon=` path is never updated. The user sees a broken dock
icon until the first successful Chrome fetch 15 minutes later (or on manual click).

This is only visible on the .deb install path; `install.sh` runs `generate-icon.py` after
the desktop file is written using the same `%HOME%` template path, same problem.

**Fix options:**
- Pre-write the desktop file with `Icon=claude-usage` (the system icon name, always
  resolvable) as the placeholder; `generate-icon.py` will replace it on first run.
- Or update `generate-icon.py` to write both alternating paths on first-run (when no
  existing `Icon=` entry is found).

---

## Code Quality

### `formatRows` count column overflows at double-digit counts

**File:** `gnome-extension/extension.js:66`

For count-type meters (e.g., "Daily included routine runs"), the second column is:

```javascript
const col2 = `${m.count}/${m.total}`.padStart(4);
```

`padStart(4)` pads to a minimum of 4 characters. With values like `0/15` (4 chars) or
`1/15` (4 chars) this aligns with the `pct` column (`" 1%"`, `"100%"` — also 4 chars).
But `10/15` is 5 chars and `100/200` is 7 chars: the column overflows, breaking alignment
with adjacent percentage rows.

In practice, the only known count meter is "Daily included routine runs" with a total of 15.
Until usage reaches 10, the column aligns. At 10+, it visually shifts right one character.

**Severity:** Cosmetic, affects only users with double-digit count meter values.

**Fix:** Use `padStart(Math.max(4, ...meters.map(m => m.count !== undefined ? \`${m.count}/${m.total}\`.length : 0)))` to compute the column width across all count meters, or widen the fixed width to 7.

---

### `addlIdx` recomputed in `background.js` when `addlStart` already holds the same value

**File:** `chrome-extension/background.js:116`

```javascript
// line 73 — used for section parsing
const addlStart = lines.findIndex(l => /^Additional features$/i.test(l));

// ... 40+ lines later ...

// line 116 — recomputed for debug payload, always equals addlStart
const addlIdx = lines.findIndex(l => /^Additional features$/i.test(l));
return { ..., _debug: { addlIdx, addlLines: lines.slice(...) } };
```

`addlIdx` will always equal `addlStart`. One unnecessary O(n) scan per fetch.

**Fix:** Replace `addlIdx` in the return statement with `addlStart`.

---

### `_debug` field permanently shipped in production payloads

**File:** `chrome-extension/background.js:116–118`

The debug instrumentation added in `2026-05-16-scraper-server-install-fixes.md` is
explicitly documented as "permanent". It adds up to 9 lines of page text to every POST and
to the cache JSON. The plan notes it is "invaluable when something stops being scraped."

The cache is 0o600 (user-only), so privacy exposure is minimal. However, the field is
included in every POST response even when the scraper is working correctly, adding
unnecessary payload weight and storing page content the user may not expect in a cache file.

**Recommendation:** Acceptable as-is given the 0o600 cache permissions and the diagnostic
value. Document in the non-obvious design decisions section of pass 1, or gate it behind a
dev flag if the payload size becomes a concern.

---

### Missing `build-chrome-zip` task in `Taskfile.yml`

**File:** `Taskfile.yml`, `packaging/build-chrome-zip.sh`

`packaging/build-chrome-zip.sh` exists but is not wired into `Taskfile.yml`. The
`release` task only includes the `.deb` in the GitHub release:

```yaml
gh release create "{{.TAG}}" "{{.DEB}}" \
```

If the Chrome zip should also be attached to releases, both the task and the `release` task
need to be updated.

**Fix:** Add to `Taskfile.yml`:
```yaml
build-chrome-zip:
  desc: Build the Chrome extension zip
  cmds:
    - bash packaging/build-chrome-zip.sh
  generates:
    - dist/claude-usage-chrome-*.zip
```
And add `deps: [build-chrome-zip]` + `"dist/claude-usage-chrome-${VERSION}.zip"` to the
`release` task command.

---

## Security

### Nothing new found.

Pass 1 addressed all security issues: cache file 0o600, POST body schema validation,
Content-Type enforcement, percentage clamping. No new attack surface visible.

---

## Architecture / Correctness Observations

### `_timestamp` always-zero regression: already fixed but worth noting the residual

**File:** `server/usage-server.py:59–61`

The server now conditionally normalises the legacy `timestamp` field:

```python
if '_timestamp' not in body:
    ts = body.pop('timestamp', None)
    body['_timestamp'] = int(ts / 1000) if ts else 0
```

If a new Chrome extension version sends `_timestamp: 0` (a valid but unusual value meaning
epoch origin), the server passes it through unchanged, and the GNOME extension would compute
an absurdly large age and fire the stale-data `⚠` warning. This can't happen with the
current extension (it always sends `Math.floor(Date.now() / 1000)`), but the absence of a
range check means a mis-behaving client could trigger spurious stale-data notifications.

**Verdict:** Not worth fixing — the server is localhost-only and the Chrome extension is the
only client. Noting for completeness.

---

### `generate-icon.py`: `BASE_ICON` failure raises `FileNotFoundError`, not `sys.exit`

**File:** `server/generate-icon.py:21–23`

Pass 1 recommended `sys.exit(f"error: ...")`. The current code raises `FileNotFoundError`
instead:

```python
if BASE_ICON is None:
    raise FileNotFoundError(
        "Base icon not found: checked ~/.local/share and /usr/share")
```

`main()` wraps the body in `try/except Exception`, catches this, prints to stderr, and
calls `sys.exit(1)`. The visible effect is identical. `raise` here is slightly more
Pythonic than `sys.exit` at module level.

**Verdict:** No change needed. Calling it out because pass 1 recommended a different form.

---

## Verified-OK (pass 1 fixes confirmed present)

| Item | File | Verified |
|------|------|----------|
| UUID fix | `packaging/claude-usage-setup:45` | `gnome-extensions enable claude-usage@indri.studio` ✓ |
| Cache guard | `generate-icon.py:204` | `if not CACHE_JSON.exists(): sys.exit(0)` ✓ |
| StopIteration | `generate-icon.py:14–23` | `next(..., None)` + explicit None check ✓ |
| File permissions | `usage-server.py:64` | `os.chmod(OUTPUT, 0o600)` ✓ |
| Schema validation | `usage-server.py:12–31` | `_validate()` returns field-level error ✓ |
| Pct clamping | `background.js:65,83,102` | `Math.min(100, Math.max(0, ...))` ✓ |
| Stale-data warning | `extension.js:211–213` | `⚠` prefix + `Main.notify` on transition ✓ |
| Offline flush | `background.js:7–20` | `chrome.storage.local` flush at top of `fetchUsage` ✓ |
| Sonnet ring track | `generate-icon.py:120` | No `track=False` — default `track=True` ✓ |
| DEFAULTS sync comment | `generate-icon.py:33` | `# keep in sync with gschema.xml default= attributes` ✓ |
| `sawExtra` declaration | `extension.js:226` | `let sawExtra = false` inside loop ✓ |
| Schema in user glib path | `install.sh:64–67` | `~/.local/share/glib-2.0/schemas/` install step ✓ |
| Diagnostics script | `scripts/claude-usage-status.sh` + `install.sh:75–78` | Installed to `~/.local/bin/` ✓ |

---

## Priority Summary

| Priority | Count | Items |
|----------|-------|-------|
| Medium | 2 | BUG-P2-1 (obsolete config.json); BUG-P2-2 (version mismatch 0.9 vs 1.0) |
| Low | 2 | BUG-P2-3 (uninstall misses alternating icons); BUG-P2-4 (broken initial dock icon in .deb path) |
| Code quality | 4 | `padStart(4)` overflow; `addlIdx` duplication; `_debug` in production; missing Taskfile task |

---

## Overall Assessment

**Grade: A (unchanged from pass 1)**

Pass 2 finds no regressions in the fixes from pass 1. The remaining items are:

- Two medium issues in packaging paths (config.json no-op; version mismatch) — neither
  affects users of the source-install path, only .deb installs.
- Two low issues in install/uninstall hygiene (leftover cache files; initial broken dock
  icon for .deb users before first scrape).
- Four cosmetic/convenience code quality items, none user-impacting for typical Max plan
  usage counts.

The core data pipeline (Chrome → server → cache → GNOME extension + dock icon) is
correct, well-validated, and secure. All actionable findings from pass 1 are confirmed
present in the source.
