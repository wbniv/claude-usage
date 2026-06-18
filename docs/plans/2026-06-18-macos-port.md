# macOS Port

## Context

`claude-usage` runs on Linux today: a browser extension scrapes `claude.ai/settings/usage`, POSTs the meters to a local Python HTTP server (`127.0.0.1:7331‑7340`), the server caches them to `~/.cache/claude-usage/usage.json`, and a desktop frontend (GNOME Shell extension **or** KDE Plasma 6 plasmoid) renders a panel indicator plus a dock icon with concentric usage rings.

Two of those four layers are already cross-platform; two are Linux-only:

| Layer | Component | macOS fate |
|---|---|---|
| Browser extension | `chrome-extension/` | **Unchanged** — talks to the server only over `http://127.0.0.1` + `/hello` discovery. Chrome/Brave/Edge/Firefox on macOS run it as-is. |
| Local server | `server/usage-server.py`, `tooltip.py`, `generate-icon.py`, `schema_defaults.py` | **Small `sys.platform` guards** — one `/proc/<pid>` check and the dock-icon spawn are the only Linux-isms. |
| Desktop frontend | `desktop/gnome/`, `desktop/kde/` | **New** — a macOS menu-bar app (`NSStatusItem`). No macOS equivalent exists. |
| Service + packaging | `systemd/`, `install.sh`, `.deb`, apt repo | **New** — launchd LaunchAgent + a `.app` bundle distributed via a Homebrew cask. |

This plan adds a **macOS menu-bar app written in Python + PyObjC**, alongside the existing GNOME and KDE frontends.

### Scope decisions (locked 2026-06-18)

1. **Frontend = Python + PyObjC** (hand-rolled `NSStatusItem`), **not** Swift. The pacing/elapsed/tier/format math already lives in three implementations (`extension.js`, `generate-icon.py`, KDE QML) held in sync by `lint-scraper-parity.py` + `lint-kde-parity.py`. A Swift app would be a **fourth** copy plus a new parity lint. PyObjC instead **imports the existing Python functions directly** → zero new copies, zero new lint. Same language and deps (Cairo + PIL) as the server. `rumps` is referenced but not depended on (hand-rolled `NSStatusItem` per the project's "prefer hand-rolled over integration libs" convention).
2. **Menu-bar only** for v1 (`LSUIElement` — no Dock presence). The menu bar mirrors the GNOME **panel** (star icon + color-coded `%` label + scroll-to-cycle + dropdown breakdown). The concentric **rings are a Dock concept** and don't read at 18 pt; the renderer in `generate-icon.py` stays wired so an optional Dock-tile mode is a later follow-up, not a rewrite.
3. **Homebrew cask** via a tap repo (the `apt.indri.studio` parallel) — `brew install --cask claude-usage`. Ship **ad-hoc-signed** (`codesign -s -`, required for Apple Silicon to launch an unsigned bundle at all); upgrade path to a notarized `.dmg` is left for when distribution goes beyond the author.

### Cross-cutting defaults

- **Universal2** bundle (Apple Silicon + Intel); **macOS 13 Ventura+** minimum.
- **Paths unchanged** from Linux: cache at `~/.cache/claude-usage/usage.json`, config at `~/.config/claude-usage/config.json`. The server already honours `XDG_*` env vars and defaults to these; keeping them identical means the server↔frontend contract is byte-for-byte the same on both platforms and `server/` path logic is untouched. (Native `~/Library/...` locations are deliberately **not** used — the contract value outweighs idiomatic placement.)
- **Version single source** stays `packaging/control` (already mirrored to `chrome-extension/manifest.json` by `task bump`); the `.app` `Info.plist` version is derived from it at build time.

---

## Implementation Plan

### 1. Extract the shared pacing/color/tier core (`server/usage_core.py`)

**Why first:** `server/generate-icon.py` carries the canonical Python implementations of `hex_to_rgba`, `ring_color`, `pacing_pct`, `elapsed_fraction`, `viz_colors`, `derive_tier`, and `load_config` — but its filename has a **hyphen**, so it cannot be `import`ed by a sibling module. The macOS app can't reuse those functions until they live in an importable module. `scripts/popup-preview.py` separately holds the popup-bar segment logic (`pacing_segments` / `color_for`) — the Python twin of `extension.js`'s `pacingSegments` / `colorFor`.

Create `server/usage_core.py` and move the **pure** (I/O-free) functions there:

- From `generate-icon.py`: `hex_to_rgba`, `ring_color`, `pacing_pct`, `elapsed_fraction`, `viz_colors`, `derive_tier`, plus the 6-key `DEFAULTS`. **Implemented decision (revised):** `load_config` + `_gsettings_or_none` **stay in `generate-icon.py`** — `test_icon.py` monkeypatches `g._gsettings_or_none` and relies on same-module resolution, which moving the function would silently break. Instead `usage_core` gets a new **GSettings-free `load_ui_config()`** (config.json → schema defaults, all UI keys) for non-GNOME frontends like the macOS app. Cairo/PIL rendering (`_render`, `draw_ring`, `_atomic_write_multisize`) stays in `generate-icon.py`. Also added: a `CLAUDE_USAGE_SCHEMA_DIR` override in `schema_defaults._find_schema` so the zipped-in-bundle module can still locate the gschema XML (the app sets it from the bundled `server/schemas/`).
- From `scripts/popup-preview.py`: `pacing_segments`, `color_for` → `usage_core` (popup-preview imports them back).
- `tooltip.py` (`parse_reset`, `format_tooltip`) and `schema_defaults.py` are already importable — leave them; the macOS app imports them directly.

`generate-icon.py` becomes `from usage_core import pacing_pct, elapsed_fraction, ...`. **Behaviour must not change on Linux** — `task test` (server suite + parity lints) stays green.

**Parity-lint retarget:** `scripts/lint-scraper-parity.py` compares numeric constants in `extension.js:pacingPct`/`elapsedFraction` against `generate-icon.py:pacing_pct`/`elapsed_fraction`. After the move, point the Python side of the lint at `server/usage_core.py`. `lint-kde-parity.py` is unaffected (it reads QML + gschema).

### 2. macOS menu-bar app (`desktop/macos/`)

```
desktop/macos/
  claude_usage_menubar.py     # entrypoint: NSStatusItem, NSMenu, file watch, timers
  statusbar_image.py          # menu-bar NSImage per tier (reuses the brand PNGs / Cairo renderer)
  Info.plist.in               # bundle manifest template (LSUIElement, identifier, version)
  claude-usage.icns           # Finder/cask icon (present even though LSUIElement hides the Dock)
  icons/                      # claude-22.png + @2x, claude-22-red.png + @2x (from desktop/gnome/icons)
```

The app is the faithful macOS analog of `desktop/gnome/extension.js`. Responsibilities, each mirroring a named piece of `extension.js`:

- **Data load + watch.** Read `~/.cache/claude-usage/usage.json`; watch its directory with **FSEvents** (`FSEventStreamCreate` on the cache dir — the file is replaced via atomic rename, exactly like the GNOME `Gio.FileMonitor` watches the file and reacts to `CREATED`/`CHANGES_DONE_HINT`). Reload + redraw on change. Warn once on a `_schema` mismatch (mirror `_schemaWarned`).
- **Status-item button.** A full-color (non-template) `NSImage` of the Anthropic star — `claude-22.png` normal, `claude-22-red.png` broken, 40 % opacity for stale (mirrors `_iconNormal`/`_iconRed`/`opacity = 100`). **Not** an `NSImage` template, because template images are monochrome and would drop the orange brand + red tint. Title is an `NSAttributedString` showing `{pct}%` or, when any meter is maxed, the live `⏱H:MM` countdown for the soonest-resetting meter (reuse `liveRemaining` logic via `_timestamp` + `reset_minutes`), colored by **pacing** (`usage_core.pacing_pct`) against the `threshold-warning`/`-critical` config.
- **Dropdown `NSMenu`.** Rebuilt on data change (skip rebuild when open + fingerprint unchanged, mirroring `_lastMenuFp`/UX-1): a status row (plan + `· N m ago`, or the tier reason `⚠ …` / `🕐 …`), then one `NSMenuItem` per visible meter whose title is an `NSAttributedString` with **per-segment colored bar cells** built from `usage_core.pacing_segments` + `color_for` (the `█`/`░`/`┊` cells, on-pace vs over-pace vs tick colors). Sonnet-0 % rows filtered out (mirror `_isSelectable`/`visibleMeters`). `✴` prefix marks the panel-selected metric. Then a separator, the extra-usage section (spent/balance sub-rows), a separator, and an **"Open Usage Page"** item (`NSWorkspace.openURL_` → `https://claude.ai/settings/usage`). When Anthropic itself reports an incident, the status row becomes a clickable item → `https://status.claude.com/` (mirror `wantLink`).
- **Tiers + 30 s tick.** An `NSTimer` every 30 s recomputes age-based **stale** (`> 15 min`) / **broken** (`> 20 min`, or `_scrape_fail_count >= 2`, or `_anthropic_status` incident) using `usage_core.derive_tier` for the cache-encoded signals plus the time-based thresholds the frontend owns (identical ladder to `extension.js` lines 569‑595). The same tick advances the live countdown.
- **Critical flash.** Blink the status-item title alpha on a 500 ms timer when any meter paces `>= threshold-critical`; stop when the menu opens; reset when it clears (mirror `_startFlash`/`_stopFlash`/`_flashSuppressed`).
- **Notifications.** On transition into **broken** (and on critical-pacing entry) post a `UNUserNotificationCenter` notification, rate-limited to 1 per 5 min, persisted via the existing `~/.cache/claude-usage/notif-ts` + `notif-crit-ts` files (mirror `_lastNotifyTs`/`_lastCritNotifyTs`). "View Status Page" action only for Anthropic-reported outages (mirror EXT-1's `wantLink` gate).
- **Scroll-to-cycle.** Override `scrollWheel:` on the status-item view to cycle `panel-metric` through selectable meters with the same 80 ms debounce idea as the GNOME scroll handler. Persist the choice (see config below).
- **Config.** Read colors/thresholds/fonts from `~/.config/claude-usage/config.json` via the shared `usage_core.load_config` (the neutral config the KDE port already established and `generate-icon.py` already reads). `panel-metric` and the notif timestamps persist to the same cache/config files the rest of the system uses — **no `NSUserDefaults`**, to keep one config surface. A native preferences window is **deferred**; v1 is configured by editing `config.json` (documented in MANUAL).

### 3. Server portability (`server/`)

Minimal, guarded changes — the server already runs on macOS except for two spots:

- **`usage-server.py:_sweep_orphan_tmps`** uses `Path(f'/proc/{pid}').exists()` for liveness. Replace the inline check with a `_pid_alive(pid)` helper: `/proc` on Linux, else `os.kill(pid, 0)` catching `ProcessLookupError`/`PermissionError` (alive). This also lets `server/tests/test_orphan_sweep.py` (currently `skipif(not Path('/proc').is_dir())`) run on macOS.
- **`usage-server.py` icon spawn** (`subprocess.Popen([... GENERATE_ICON ...])` on POST and at startup): guard with `sys.platform != 'darwin'`. On macOS the menu-bar app renders its own icon in-process, and `generate-icon.py` would otherwise create Linux `~/.local/share/icons/hicolor/` dirs. The app owns rendering; the server stops spawning the dock generator on Darwin.
- **`tooltip.update_desktop`** already early-returns when the `.desktop` launcher is absent (`if not DESKTOP.exists(): return`) — so the 60 s `_tooltip_tick` thread is a **harmless no-op** on macOS (no `.desktop` file is ever written). The menu-bar app computes its own tooltip text via `tooltip.format_tooltip`. No change needed beyond confirming the no-op.
- **`generate-icon.py`** stays Linux-only as an executable; its pure functions move to `usage_core` (§1) and the Cairo renderer is unused on macOS in v1.

### 4. launchd LaunchAgent (replaces the systemd unit)

`packaging/macos/studio.indri.claude-usage.plist` (installed to `~/Library/LaunchAgents/`):

- `Label = studio.indri.claude-usage`
- `ProgramArguments` = the bundled app's python launching `claude_usage_menubar.py`. **The menu-bar app hosts the HTTP server on a background thread** → one process, one LaunchAgent (the systemd unit + the GNOME extension collapse into a single agent). This matches "minimize manual steps" and gives `Restart=always` parity via `KeepAlive`.
- `RunAtLoad = true`, `KeepAlive = true` (restart-on-crash, the systemd `Restart=always` analog).
- LaunchAgents in `~/Library/LaunchAgents` run in the per-user **Aqua GUI session**, which a menu-bar (`LSUIElement`) app requires — correct by construction; no LaunchDaemon.
- Loaded/unloaded with `launchctl bootstrap gui/$(id -u) <plist>` / `bootout` (modern) with a `load -w`/`unload` note for older macOS.

### 5. Packaging — `.app` bundle + Homebrew cask

- **`packaging/macos/build-app.sh`** (`set -euo pipefail`, handles `-h`): build `claude-usage.app` with **py2app**, bundling `desktop/macos/` + `server/` + Cairo/PIL. `Info.plist` from `Info.plist.in` with `LSUIElement=true`, `CFBundleIdentifier=studio.indri.claude-usage`, `LSMinimumSystemVersion=13.0`, and `CFBundleShortVersionString` read from `packaging/control`. Ad-hoc sign: `codesign -s - --deep --force claude-usage.app`. Verify Cairo/PIL ship **universal2**.
- **`packaging/macos/Casks/claude-usage.rb`** in a `homebrew-tap` repo (the apt-repo parallel): `version`/`sha256`, `url` → GitHub Release `.zip`, `app "claude-usage.app"`, a `postflight` that `xattr -dr com.apple.quarantine`s the app and `launchctl bootstrap`s the LaunchAgent, `uninstall launchctl: "studio.indri.claude-usage", quit: "studio.indri.claude-usage"`, and `zap trash:` for `~/.cache/claude-usage`, `~/.config/claude-usage`, and the LaunchAgent plist.
- **CI** — macOS runs on **Codemagic** (`codemagic.yaml`, `mac_mini_m1`, Node 24), not a GitHub `macos-latest` job: real Mac runners are the whole point (py2app + PyObjC + bundle checks). The `macos-test` workflow runs `task test`, `task build-macos`, verifies the bundle (`lipo`/`codesign`), and runs `packaging/macos/ci-smoke.py` (real-PyObjC import + ported-logic assertions). GitHub Actions `release.yml` stays Linux-only (.deb + Chrome zip). Release-time `.app` attach + cask `version`/`sha256` bump is a later step (this workflow is test-only — ad-hoc signed, no secrets).
- **Browser extension:** unchanged. MANUAL gains a macOS "Load the extension" note — identical Load-unpacked steps on macOS Chrome/Brave/Edge, and the signed-`.xpi`/temporary-add-on flow on macOS Firefox.

### 6. Diagnostics (`scripts/claude-usage-status.py`)

Add a `sys.platform == 'darwin'` branch: replace the `systemctl --user is-active claude-usage-fetch.service` probe with `launchctl print gui/$(id -u)/studio.indri.claude-usage` (running + last exit), skip the `gnome-extensions show` check, and report the menu-bar app PID. Cache-freshness, meter breakdown, and `/hello` port probe are platform-neutral and stay as-is.

### 7. Tests & lints

- **Refactor safety:** `task test` (server pytest + scraper node tests + all parity lints) green after §1; `lint-scraper-parity.py` retargeted to `server/usage_core.py`.
- **New unit coverage:** move the pacing/segment tests to exercise `usage_core` directly; add cases for `_pid_alive`. `test_orphan_sweep.py` now runs on macOS.
- **Menu-bar app** needs **live verification on a Mac** (PyObjC/`NSStatusItem` can't load under headless CI without a GUI session) — analogous to KDE needing QEMU. Tracked as a `[verify][live]` item. CI does an `import`-guard smoke (`python3 -c "import ast; ast.parse(open('desktop/macos/claude_usage_menubar.py').read())"`) plus a pyflakes pass so syntax/obvious breakage is caught without a runner.

---

## Critical files

| File | Action |
|------|--------|
| `server/usage_core.py` | **Create** — importable home for `pacing_pct`, `elapsed_fraction`, `viz_colors`, `derive_tier`, `ring_color`, `hex_to_rgba`, `pacing_segments`, `color_for`, `load_config` |
| `server/generate-icon.py` | Modify — import the moved functions from `usage_core`; Cairo renderer + multisize write stay |
| `scripts/popup-preview.py` | Modify — import `pacing_segments`/`color_for` from `usage_core` |
| `scripts/lint-scraper-parity.py` | Modify — retarget the Python side to `server/usage_core.py` |
| `server/usage-server.py` | Modify — `_pid_alive()` helper; guard the dock-icon spawn on `darwin` |
| `desktop/macos/claude_usage_menubar.py` | **Create** — `NSStatusItem` app (server thread, FSEvents watch, menu, timers, flash, notifications, scroll-cycle) |
| `desktop/macos/statusbar_image.py` | **Create** — per-tier menu-bar `NSImage` |
| `desktop/macos/Info.plist.in` | **Create** — `LSUIElement`, identifier, version template |
| `desktop/macos/claude-usage.icns`, `icons/*` | **Create** — Finder icon + @1x/@2x brand PNGs |
| `packaging/macos/studio.indri.claude-usage.plist` | **Create** — LaunchAgent (`RunAtLoad`, `KeepAlive`) |
| `packaging/macos/build-app.sh` | **Create** — py2app build + ad-hoc codesign |
| `packaging/macos/Casks/claude-usage.rb` | **Create** — Homebrew cask (postflight loads agent, zap removes state) |
| `scripts/claude-usage-status.py` | Modify — `darwin` branch (launchctl, skip gnome-extensions) |
| `.github/workflows/release.yml` | Modify — `macos-latest` build/zip/release + cask bump |
| `Taskfile.yml` | Add `build-macos`, `install-macos`, `uninstall-macos` |
| `MANUAL.md` | Add a macOS install/config/troubleshooting section |
| `server/tests/test_orphan_sweep.py` | Modify — un-skip on macOS now that `_pid_alive` is cross-platform |

## Reused utilities (single source of truth)

- `server/usage-server.py`, `server/tooltip.py`, `chrome-extension/` — shared, near-zero changes (the whole point of the architecture).
- `server/schema_defaults.py` — defaults/ranges read unchanged.
- `server/usage_core.py` — the menu-bar app **imports** the pacing/color/tier/segment math instead of re-implementing it. No fourth copy, no new parity lint.
- `desktop/gnome/icons/claude-22*.png` — reused as the macOS menu-bar images.

---

## Verification

**Status (2026-06-18, implementation landing).** Linux-runnable steps pass; the macOS bundle/launchd/cask/end-to-end steps (4–7, 9–12) are `[verify][live]` — they need a Mac.

- **Step 1 — PASS.** `task test` exits 0: server pytest 115 passed, node scraper + gnome-format tests, and all parity/security/qml/gnome lints. `lint-scraper-parity` now reads `server/usage_core.py` and matches all four JS↔Python pairs.
- **Step 2 — PASS.** `python3 server/generate-icon.py --baseline` renders (8.9 KB PNG); `test_icon` + `test_pacing` + `test_schema_defaults` = 42 passed — the refactor is behaviour-neutral on Linux.
- **Step 3 — PASS.** `test_orphan_sweep.py` un-skipped (now POSIX-gated) — 7 passed; `_pid_alive(self)=True`, `_pid_alive(99999999)=False`.
- **Step 8 (logic half) — PASS.** The ported pure logic (`fmt_countdown`, `live_remaining`, `is_selectable`, `get_primary`, `reset_hint`) unit-tested against `extension.js` semantics with stubbed PyObjC — 14/14. The pixel-for-character bar parity remains `[verify][live]`.
- **macOS files** compile (`py_compile`) and the changed shell scripts pass `bash -n`; the cask/plist/Info.plist are well-formed.

1. **Refactor is behaviour-neutral:** `task test` — server suite + scraper tests + every parity/security lint green, with `lint-scraper-parity` now reading `server/usage_core.py`.
2. **generate-icon.py unchanged on Linux:** run `python3 server/generate-icon.py` against a populated cache; icon bytes + tier identical to pre-refactor.
3. **`_pid_alive` cross-platform:** `test_orphan_sweep.py` passes on both Linux (`/proc`) and macOS (`os.kill(pid, 0)`).
4. **`.app` builds:** `task build-macos` produces an ad-hoc-signed universal `claude-usage.app`; `codesign -dv` shows the signature; `lipo -archs` shows `x86_64 arm64`.
5. **LaunchAgent runs the app:** `launchctl bootstrap gui/$(id -u) …plist`; menu-bar icon appears; `launchctl print …/studio.indri.claude-usage` shows it running; killing the process triggers a `KeepAlive` restart.
6. **Server thread serves:** `curl -s http://127.0.0.1:7331/hello | python3 -c 'import json,sys;print(json.load(sys.stdin)["app"])'` → `claude-usage`.
7. **End-to-end with the extension:** load the unpacked extension in macOS Chrome logged into claude.ai; within one scrape cycle the menu-bar `%` + dropdown meters match `claude.ai/settings/usage`.
8. **Pacing/color parity:** for a known cache, the menu-bar bar segments + colors match the GNOME popup pixel-for-character (same `usage_core` output).
9. **Tier transitions:** simulate `_anthropic_status` incident → broken (red icon, status row links to status page, notification fires once per 5 min); age `> 15 min` → stale (ghosted); recovery → normal.
10. **Scroll-to-cycle + countdown:** scroll over the menu-bar item cycles the metric; a 100 %-maxed meter shows a minute-ticking `⏱H:MM`.
11. **Cask install/uninstall:** `brew install --cask <tap>/claude-usage` installs the app, clears quarantine, loads the agent; `brew uninstall --cask` + `--zap` removes the app, agent, and `~/.cache`/`~/.config` state.
12. **Diagnostics:** `claude-usage-status` on macOS reports agent state + cache freshness + meters with no `systemctl`/`gnome-extensions` errors.

---

## Deferred / open

- **Dock-tile rings** — the `generate-icon.py` Cairo renderer stays wired; a later mode can drop `LSUIElement` and paint the concentric rings onto `NSApp.dockTile`. Promote into v1 only if the dock rings are part of daily glance use.
- **Native preferences window** — v1 reads `config.json`; a PyObjC prefs panel (color wells + threshold steppers, writing the same `config.json`) is a follow-up matching the GNOME/KDE prefs round-trip.
- **Notarized `.dmg`** — needed only for distribution beyond the author (Apple Developer ID, `notarytool`, `stapler`). The cask upgrades to it cleanly.
- **Universal Cairo/PIL** — confirm `py2app` bundles universal2 wheels; if a dep is x86_64-only, either build it universal or ship arm64 + Rosetta note.
