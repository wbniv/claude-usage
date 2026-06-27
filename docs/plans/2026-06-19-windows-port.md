# Windows Port

## Context

`claude-usage` runs on Linux and macOS today: a browser extension scrapes `claude.ai/settings/usage`, POSTs the meters to a local Python HTTP server (`127.0.0.1:7331‑7340`), the server caches them to `~/.cache/claude-usage/usage.json`, and a desktop frontend renders an indicator. Three frontends exist — GNOME Shell extension, KDE Plasma 6 plasmoid, and a macOS menu‑bar `NSStatusItem` app (see [2026-06-18-macos-port.md](2026-06-18-macos-port.md)). This plan adds a **fourth frontend: a Windows system‑tray app written in Python + pywin32**, plus its service/packaging story.

Two of the four layers are already cross‑platform; two are per‑OS:

| Layer | Component | Windows fate |
|---|---|---|
| Browser extension | `chrome-extension/` | **Unchanged** — talks to the server only over `http://127.0.0.1` + `/hello` discovery. Chrome/Edge/Brave/Firefox on Windows run it as‑is. |
| Local server | `server/usage-server.py`, `tooltip.py`, `usage_core.py`, `schema_defaults.py` | **Small `win32` guards** — one genuinely *dangerous* spot (`_pid_alive`), plus the dock‑icon spawn and a `SIGCHLD` install that needs broadening. |
| Desktop frontend | `desktop/gnome/`, `desktop/kde/`, `desktop/macos/` | **New** — a Windows tray app (`Shell_NotifyIcon` via pywin32). No Windows equivalent exists. |
| Service + packaging | `systemd/`, launchd plist, `.deb` + apt repo, Homebrew cask | **New** — `HKCU\…\Run` autostart + a PyInstaller `.exe` shipped via an Inno Setup installer + a winget manifest. |

The Windows frontend is the faithful analog of `desktop/macos/claude_usage_menubar.py`, which is itself the analog of `desktop/gnome/extension.js`. The pacing/elapsed/tier/format/segment MATH already lives once in importable Python (`server/usage_core.py`, the single source of truth the macOS app imports); the tray app **imports it directly** — no fifth copy, no new parity lint.

### The one structural divergence from macOS/GNOME

The Windows notification area (system tray) renders **only a small icon** — there is no adjacent text slot like the macOS menu bar's `NSStatusItem` title or the GNOME panel label. So the glanceable `%` (the heart of the app on every other platform) is **rendered into the tray bitmap itself** with Pillow, colour‑coded by pacing. Everything downstream of that one fact follows.

### Scope decisions (locked 2026‑06‑19)

1. **Frontend = Python + pywin32** (hand‑rolled `Shell_NotifyIcon`), **not** C#/.NET and **not** `pystray`. Same reasoning that picked PyObjC over Swift/`rumps` on macOS: pywin32 is the direct‑Win32‑API analog of PyObjC, lets the app **import the existing `usage_core` functions** (zero new copies, zero new parity lint), and keeps one language + dep set across server and frontend. `pystray` is referenced but not depended on (hand‑rolled per the project's "prefer hand‑rolled over integration libs" convention).
2. **The `%` is rendered into the tray icon** (Pillow), with the digits coloured by **pacing** (green < warning · amber ≥ warning · red ≥ critical) — because the tray has no text slot. The brand star + red‑tinted *broken* variant + ~40 % ghosted *stale* variant still apply (same three tiers as Linux/macOS). The hover **tooltip** carries the full per‑meter breakdown (`tooltip.format_tooltip`, already exists). Concentric **rings are deferred** (they don't read at 16 px and Cairo is hard to bundle on Windows).
3. **Distribution = PyInstaller `--onedir` `.exe` → Inno Setup installer + winget manifest** (the Homebrew‑cask / apt‑repo analog). Autostart via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (per‑user, interactive desktop session — **not** a Windows Service, which runs in session 0 and cannot own a notification‑area icon for the logged‑in user). Ship **unsigned** for v1 (document the SmartScreen "More info → Run anyway", the Gatekeeper‑quarantine analog); upgrade path = an Authenticode cert + `signtool` (the `notarytool` analog).
4. **Native Preferences window in v1** (tkinter `colorchooser` + `Spinbox`), round‑tripping the **same** `config.json` via `usage_core.write_ui_config` — full parity with the *current* macOS feature set (which added its prefs window in [2026-06-19-macos-prefs-window.md](2026-06-19-macos-prefs-window.md)).

### Cross‑cutting defaults

- **Paths unchanged** from Linux/macOS: cache at `~/.cache/claude-usage/usage.json`, config at `~/.config/claude-usage/config.json`. On Windows `Path.home()` → `C:\Users\<name>`, so these resolve to `C:\Users\<name>\.cache\claude-usage\…`. The server already honours `XDG_*` env vars and defaults to `Path.home() / '.cache'` etc., so the server↔frontend contract is byte‑for‑byte identical on all three platforms and `server/` path logic is untouched. (Native `%LOCALAPPDATA%` is deliberately **not** used — the same contract‑over‑idiom call the macOS port made for `~/Library`.)
- **Minimum OS: Windows 10 22H2 (x64)+.** Classic `Shell_NotifyIcon` balloon notifications route to the Action Center on Win10+. 64‑bit only for v1.
- **No Cairo on Windows.** The tray bitmap is rendered with **Pillow** (already a server dep, trivial wheels on Windows). `generate-icon.py`'s Cairo renderer stays Linux‑only and is guarded off on Windows (exactly as on macOS).
- **Version single source** stays `packaging/control` (already mirrored to `chrome-extension/manifest.json` by `task bump`); the PyInstaller VERSIONINFO, the Inno Setup `AppVersion`, and the winget manifest version derive from it at build time.
- **Runtime deps:** CPython 3.x frozen by PyInstaller; `pywin32` + `Pillow` + stdlib (`http.server`, `ctypes`, `tkinter`). One process: the tray `.exe` hosts the HTTP server on a daemon thread.

---

## Implementation Plan

### 1. Server portability (`server/`) — the load‑bearing change

The macOS port already made most of the server cross‑platform, but Windows surfaces one spot the macOS path never exercised:

- **`_pid_alive` is a Windows footgun (`usage-server.py:579`).** Today it is `/proc/<pid>` on Linux, **else `os.kill(pid, 0)`**. On Windows that is *not* a null‑signal probe: CPython maps any signal other than `CTRL_C_EVENT`/`CTRL_BREAK_EVENT` to `TerminateProcess(handle, sig)`, so `os.kill(pid, 0)` would **terminate** the pid (exit code 0), not check it. It is **inert today** — `_pid_alive` is only reached from `_sweep_orphan_tmps`, which globs Linux‑only dirs (`~/.local/share/applications`, `~/.local/share/icons/hicolor`) that never exist on Windows, so the loop never iterates and the helper is never called. But a cross‑platform helper that silently kills processes is a footgun. **Add a `sys.platform == 'win32'` branch** that probes via `kernel32.OpenProcess(SYNCHRONIZE, …)` + `WaitForSingleObject`/`GetExitCodeProcess` (ctypes; or `win32api.OpenProcess` when pywin32 is present), returning alive/dead with no signalling. Tighten the docstring's "Other platforms (macOS) use `os.kill`" to "POSIX (macOS/BSD) use `os.kill`; Windows uses `OpenProcess`". **Regression‑guard:** add win32‑gated `_pid_alive` unit cases (`self` pid → alive, an absurd pid → dead). This is the #1 correctness item.
- **Icon‑spawn guard (`usage-server.py:25`).** `_SPAWN_ICON = sys.platform != 'darwin'` → broaden to `sys.platform.startswith('linux')` (equivalently, exclude `darwin` **and** `win32`). On Windows the tray app renders its own bitmap in‑process (Pillow); `generate-icon.py` would otherwise try to create Linux `~/.local/share/icons/hicolor/` dirs.
- **`SIGCHLD` install (`serve_forever`, `usage-server.py:656`).** `signal.signal(signal.SIGCHLD, …)` — `signal.SIGCHLD` **does not exist** on Windows, so attribute access raises `AttributeError`, which the existing `except ValueError` won't catch. Guard with `if hasattr(signal, 'SIGCHLD'):` (or broaden the except to `(ValueError, AttributeError)`). On Windows we run `serve_forever` in a worker thread and spawn no children, so there is nothing to reap.
- **`_sweep_orphan_tmps`** — already a harmless no‑op on Windows (the Linux‑path `.is_dir()` guards return early). No change beyond the `_pid_alive` fix making it safe even if a path ever matched.
- **`tooltip.update_desktop`** — already early‑returns when the `.desktop` launcher is absent, so the 60 s `_tooltip_tick` thread is a no‑op on Windows. The tray app computes its own tooltip text via `tooltip.format_tooltip`. No change.
- **`serve_forever()` already exists** (added for the macOS in‑process thread) — reused verbatim by the Windows tray app.

All changes are guarded and behaviour‑neutral on Linux/macOS — `task test` stays green.

### 2. Windows system‑tray app (`desktop/windows/`)

```
desktop/windows/
  claude_usage_tray.py   # entrypoint: Shell_NotifyIcon, hidden message window, menu, timers, server thread
  tray_image.py          # per‑tier HICON: % composited onto the brand star (Pillow), recoloured by pacing
  prefs.py               # tkinter Preferences (colorchooser + Spinbox) → usage_core.write_ui_config
  icons/                 # claude-22.png, claude-22-red.png, claude-64.png (from desktop/gnome/icons)
  claude-usage.ico       # installer / .exe icon
```

The faithful Windows analog of `desktop/macos/claude_usage_menubar.py`. Each responsibility mirrors a named piece of that file (and through it, `extension.js`):

- **Hidden message window.** A Win32 tray icon needs an `HWND` to receive its callback. Register a window class + create a hidden message‑only window; dispatch the `WM_USER+1` callback (and `WM_TIMER`, menu commands, `WM_DESTROY`) through a `WNDPROC` handler dict — the standard hand‑rolled pywin32 pattern (mirrors the macOS controller owning the `NSStatusItem`).
- **Data load + watch.** Read `~/.cache/claude-usage/usage.json`. **Poll the file mtime every 2 s** via `WM_TIMER` — the macOS app polls at `POLL_SECONDS = 2.0` (it dropped FSEvents for a plain `stat` poll); we mirror that exactly rather than wiring `ReadDirectoryChangesW`. Reload + redraw on mtime change. Warn once on a `_schema` mismatch (mirror `_schemaWarned`).
- **Tray icon = rendered `%` bitmap.** `tray_image.py` composites the selected meter's `{pct}%` (or, when any meter is maxed, the live `⏱H:MM` countdown for the soonest‑resetting one) onto the brand star with Pillow, the digits coloured by **pacing** (`usage_core.pacing_pct` vs `threshold-warning`/`-critical`), then converts the PIL image to an `HICON` (32‑bpp DIB → `CreateIconIndirect`) and applies it with `Shell_NotifyIcon(NIM_MODIFY, NIF_ICON)`. Broken tier → the `claude-22-red.png` star; stale tier → ghosted at 40 % alpha (mirrors `extension.js` `opacity = 100/255`). Render at the system tray size (`GetSystemMetrics(SM_CXSMICON)` × the per‑monitor DPI scale) so it stays crisp on HiDPI. **`DestroyIcon` the previous HICON on every update** — the one Win32 resource‑leak trap (the GDI‑handle analog of forgetting to release an NSImage).
- **Tooltip = full breakdown.** `Shell_NotifyIcon(NIM_MODIFY, NIF_TIP)` with `tooltip.format_tooltip(...)`. `NOTIFYICONDATA.szTip` is 128 wchars on modern Windows, multi‑line via `\r\n`; `format_tooltip` already emits a compact multi‑line breakdown — cap/trim to ≤ 127 chars (note the divergence: the GNOME tooltip can run longer).
- **Right‑click menu (`TrackPopupMenu`).** Items: a disabled **status line** (plan + `· N m ago`, or the tier reason `⚠ …` / `🕐 …`; becomes a clickable item → `https://status.claude.com/` when Anthropic reports an incident, mirror `wantLink`), a separator, one **radio‑checked** item per visible meter (`label` + `pct%`/`count/total`; a check/✴ marks the panel‑selected metric; Sonnet‑0 % rows filtered via `is_selectable`/`visible_meters`) that pins `panel-metric` on click, a separator, **Preferences…**, **Open Usage Page** (`ShellExecute`/`os.startfile` → `https://claude.ai/settings/usage`), **Quit**.
  - **Metric cycling divergence:** the GNOME/macOS *scroll‑to‑cycle* affordance does **not** map to the Windows tray (the shell doesn't deliver wheel events to tray icons) → replaced by the radio menu items. Left‑click opens the usage page; right‑click opens the menu. (Flag in MANUAL.)
  - **Coloured‑bar divergence:** Win32 popup menus are plain text — the per‑segment coloured pacing bars the macOS app draws with `NSAttributedString` are **not** reproduced in the menu (they live in the tooltip for v1). Owner‑draw coloured menu items are the deferred upgrade (the Windows analog of macOS deferring dock rings).
- **Tiers + 2 s tick.** The `WM_TIMER` tick recomputes age‑based **stale** (> 15 min) / **broken** (> 20 min, or `_scrape_fail_count >= 2`, or an `_anthropic_status` incident) using `usage_core.derive_tier` for the cache‑encoded signals plus the time thresholds the frontend owns (identical ladder to `extension.js` ~569‑595 and the macOS `_deriveTier`). The same tick advances the live countdown.
- **Critical flash.** Blink the tray icon between the rendered bitmap and a ghosted copy on a 500 ms timer when any meter paces ≥ `threshold-critical`; stop while the menu is open; reset when it clears (mirror `_startFlash`/`_stopFlash`/`_flashSuppressed`). Windows has no per‑item alpha like macOS, so "flash" = swap the `HICON` between full and dimmed.
- **Notifications.** On transition into **broken** (and on critical‑pacing entry) show a **balloon** via `Shell_NotifyIcon(NIM_MODIFY, NIF_INFO)` (`szInfoTitle`/`szInfo`), rate‑limited to 1 per 5 min, persisted via the existing `~/.cache/claude-usage/notif-ts` + `notif-crit-ts` files (mirror `_lastNotifyTs`/`_lastCritNotifyTs`). For Anthropic‑reported outages, handle the balloon‑click message (`NIN_BALLOONUSERCLICK`) → open the status page (the macOS "View Status Page" action analog; classic balloons have no action buttons, so click‑the‑balloon is the affordance). Modern toast action buttons are deferred.
- **Config.** Read colours/thresholds/fonts from `~/.config/claude-usage/config.json` via `usage_core.load_ui_config`. `panel-metric` + the notif timestamps persist to the same cache/config files the rest of the system uses — **no registry config surface** (one config surface, mirroring the macOS "no `NSUserDefaults`" call).

### 3. Native Preferences window (`desktop/windows/prefs.py`)

**tkinter** (ships with CPython, bundles cleanly under PyInstaller; `tkinter.colorchooser.askcolor` is the native Windows colour picker, `ttk.Spinbox` the steppers). The same menu‑relevant fields the macOS `prefs.py` covers:

| Control | Keys | Widget |
|---|---|---|
| Pacing thresholds | `threshold_warning`, `threshold_critical` (1–500) | `Spinbox` |
| Popup bar width | `bar_width` (1–20) | `Spinbox` |
| Popup font size | `popup_font_size` (8–20) | `Spinbox` |
| `%` digit colour | `panel_color_normal/warning/critical` | colour swatch → `askcolor` |
| Popup bar/text colour | `popup_color_normal/warning/critical` | colour swatch → `askcolor` |

Each change calls `usage_core.write_ui_config(...)` (already exists — atomic 0600 merge‑write via the shared `_coerce`, ranges from the gschema). No config‑change signal needed: the tray app's 2 s poll re‑reads `config.json` (≤ 2 s live apply, the same model as macOS/GNOME "applies instantly"). Opened from the **Preferences…** menu item.

**One integration risk to validate live:** a Tk event loop co‑existing with the Win32 `Shell_NotifyIcon` message pump (both want a loop). Simplest robust wiring is to launch prefs as a **separate `pythonw` process** (or the frozen `.exe` with a `--prefs` switch) so each owns its own loop and they communicate only through `config.json`. Note this and pick the separate‑process path unless an in‑process `Tk()` proves clean on‑device.

**Deferred (match macOS):** dock‑ring colours (no rings on Windows v1), the font‑family picker (`popup_font_family` stays hand‑editable), and the GNOME‑panel‑only sizing keys (`panel_font_size`/`panel_label_spacing`/`panel_icon_size`).

### 4. Autostart — `HKCU\…\Run` (replaces the systemd unit / launchd agent)

- Per‑user autostart via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value `ClaudeUsage = "%LOCALAPPDATA%\Programs\claude-usage\claude-usage.exe"`. This runs in the **interactive desktop session** a tray app requires — correct by construction, no admin.
- **Not a Windows Service:** services run in session 0 and cannot own a notification‑area icon for the logged‑in user (the session‑0‑isolation analog of why the macOS agent is a per‑user LaunchAgent, not a LaunchDaemon).
- The tray `.exe` **hosts the HTTP server on a daemon thread** (`serve_forever`) → one process, one autostart entry (the Linux systemd‑server + GNOME‑shell split, or the macOS launchd agent, collapse into a single Run‑key entry).
- **KeepAlive / restart‑on‑crash:** a Run key only relaunches at next login — there is no built‑in `KeepAlive` analog. v1 relies on relaunch‑at‑login + app resilience; an optional Task Scheduler `ONLOGON` trigger with "restart on failure" is the launchd‑`KeepAlive` equivalent (deferred). The installer writes the Run value; the uninstaller removes it.

### 5. Packaging — PyInstaller `.exe` + Inno Setup installer + winget

- **`packaging/windows/build-exe.ps1`** (`$ErrorActionPreference = 'Stop'`; handles `-h`/`-Help`): freeze with **PyInstaller `--onedir --noconsole --name claude-usage`**, bundling `desktop/windows/` + the shared `server/` modules (`usage_core`, `tooltip`, `schema_defaults`, `usage-server.py`) + the gschema XML + the brand icons + Pillow + pywin32 + tkinter. `--onedir` (not `--onefile`) for faster start + fewer AV false positives. Embed the version (from `packaging/control`) into the exe's VERSIONINFO resource. Output: `dist/claude-usage/claude-usage.exe`.
- **`packaging/windows/claude-usage.iss`** (Inno Setup): installs the one‑folder build to `%LOCALAPPDATA%\Programs\claude-usage` (per‑user, no admin), adds a Start‑Menu shortcut, writes the `HKCU\…\Run` value, registers an uninstaller; `AppVersion`/`AppId` from `packaging/control`. Output: `dist/claude-usage-setup-<ver>.exe`. (SmartScreen "Run anyway" note in MANUAL — unsigned v1.)
- **`packaging/windows/winget/`** manifest (the cask/apt analog): `Indri.ClaudeUsage` with `version` / installer `sha256` / `url` → the GitHub Release `setup.exe`; submitted to the community `winget-pkgs` repo (or self‑hosted). Release‑time version/sha bump is a later step — this is **test‑only CI** for v1, no signing secrets (the same staging as the macOS cask `:no_check`).
- **Browser extension:** unchanged. MANUAL gains a Windows "Load the extension" note — identical Load‑unpacked steps on Windows Chrome/Edge/Brave, and the signed‑`.xpi` / temporary‑add‑on flow on Windows Firefox.

### 6. CI — GitHub Actions `windows-latest`

Unlike macOS (which needed **Codemagic** because GitHub has no real Mac hardware for the relevant tier), GitHub Actions provides a real **`windows-latest`** runner for free → Windows CI lives in **GitHub Actions** (new `.github/workflows/windows-test.yml`, or a job in `release.yml`), not Codemagic. Steps: set up Python 3 + `pywin32` + `Pillow` + `pyinstaller` → `task test` (the platform‑neutral server pytest + scraper node suite + parity/security lints) → `build-exe.ps1` → `packaging/windows/ci-smoke.py` (import the real pywin32 modules + assert the ported pure logic — the macOS `ci-smoke.py` analog). The tray GUI itself **cannot** be exercised headlessly (no interactive session delivers `Shell_NotifyIcon` clicks), so it stays a `[verify][live]` item, exactly like the macOS `NSStatusItem` and the KDE QEMU step. `release.yml` remains the home for the `.deb` + Chrome zip; attach the Windows `setup.exe` + bump the winget manifest at release time (later).

### 7. Diagnostics (`scripts/claude-usage-status.py`)

Add a `sys.platform == 'win32'` branch to `_check_service`: replace the `systemctl`/`launchctl` probe with reading the `HKCU\…\Run` value + checking the running process (`tasklist` or `win32process` for `claude-usage.exe`), and report the tray app PID. Extend the existing `if sys.platform != 'darwin':` guard at line 180 to also exclude `win32` so `_check_extension` (GNOME‑only) is skipped. Cache freshness, the meter breakdown, and the `/hello` port probe are platform‑neutral and stay as‑is.

### 8. Tests & lints

- **Refactor safety:** `task test` (server pytest + scraper node + parity/security/qml/gnome lints) green after §1 — all platform‑neutral, unchanged on the Linux dev box + CI.
- **New unit coverage:** win32‑gated `_pid_alive` cases (alive = `os.getpid()`, dead = an absurd pid). The pacing/segment/tier tests already cover the shared `usage_core` the tray app imports — no new copy to test.
- **Tray app + prefs need live verification on Windows** (`Shell_NotifyIcon` + tkinter can't load meaningfully under headless CI) — a `[verify][live]` item, analogous to macOS/KDE. CI does `ast.parse` + pyflakes + a real‑pywin32 import smoke + the `ci-smoke.py` logic asserts.

---

## Critical files

| File | Action |
|------|--------|
| `server/usage-server.py` | Modify — `_pid_alive` `win32` branch (`OpenProcess`, **not** `os.kill`); broaden the icon‑spawn guard to exclude `win32`; guard `SIGCHLD` with `hasattr` |
| `desktop/windows/claude_usage_tray.py` | **Create** — `Shell_NotifyIcon` app (hidden msg window, server thread, mtime poll, menu, timers, flash, balloons) |
| `desktop/windows/tray_image.py` | **Create** — per‑tier `HICON`: `%` composited onto the brand star with Pillow, recoloured by pacing |
| `desktop/windows/prefs.py` | **Create** — tkinter Preferences (`colorchooser` + `Spinbox`) → `usage_core.write_ui_config` |
| `desktop/windows/icons/*`, `claude-usage.ico` | **Create** — reuse `desktop/gnome/icons/claude-22*.png` + a `.ico` for the exe/installer |
| `packaging/windows/build-exe.ps1` | **Create** — PyInstaller `--onedir --noconsole`, version from `packaging/control` |
| `packaging/windows/claude-usage.iss` | **Create** — Inno Setup installer (per‑user, Start Menu, `HKCU\…\Run`, uninstaller) |
| `packaging/windows/winget/Indri.ClaudeUsage.*.yaml` | **Create** — winget manifest (cask/apt analog) |
| `packaging/windows/ci-smoke.py` | **Create** — real‑pywin32 import + ported‑logic asserts (macOS `ci-smoke.py` analog) |
| `scripts/claude-usage-status.py` | Modify — `win32` branch (Run‑key + process, skip `gnome-extensions`) |
| `.github/workflows/windows-test.yml` | **Create** — `windows-latest`: `task test` + build exe + ci‑smoke |
| `.github/workflows/release.yml` | Modify (later) — attach `setup.exe` + bump winget manifest at release |
| `Taskfile.yml` | Add `build-windows`, `install-windows`, `uninstall-windows` |
| `MANUAL.md` | Add a Windows install/config/troubleshooting section |
| `server/tests/test_orphan_sweep.py` (or new) | Modify — win32‑gated `_pid_alive` cases |

## Reused utilities (single source of truth)

- `server/usage-server.py`, `tooltip.py`, `chrome-extension/` — shared, near‑zero changes (the whole point of the architecture).
- `server/usage_core.py` — the tray app **imports** the pacing/colour/tier/segment math **and** `write_ui_config`/`load_ui_config`. No fifth copy, no new parity lint.
- `server/schema_defaults.py` — defaults/ranges read unchanged (the prefs `Spinbox` min/max come from here).
- `desktop/gnome/icons/claude-22*.png` — reused as the Windows tray base art.

---

## Verification

> Run each numbered step on the target platform; paste raw output in a code block below the step, then a PASS/FAIL note (CLAUDE.md plan‑verification format). Steps 1–3 + 8 are runnable on Linux/CI; 4–13 need a real Windows desktop (`[verify][live]`, the `Shell_NotifyIcon`/tkinter analog of the macOS `NSStatusItem` and KDE QEMU gates).

1. **Refactor is behaviour‑neutral:** `task test` — server suite + scraper tests + every parity/security lint green; the new win32‑gated `_pid_alive` cases pass on Linux (skipped) and would pass on Windows.
2. **`generate-icon.py` unchanged on Linux:** render against a populated cache; icon bytes + tier identical to pre‑refactor.
3. **`_pid_alive` cross‑platform and safe:** Linux (`/proc`), POSIX (`os.kill`), Windows (`OpenProcess`) all return alive/dead correctly — and the `os.kill`‑terminates‑on‑Windows trap is gone.
4. **`.exe` builds:** `build-exe.ps1` → `dist/claude-usage/claude-usage.exe`; double‑click launches with **no console window**; the tray icon appears.
5. **Autostart:** the installer writes `HKCU\…\Run`; the tray icon appears after a log‑off/log‑on; the uninstaller removes the app + the Run value.
6. **Server thread serves:** `Invoke-RestMethod http://127.0.0.1:7331/hello` (or `curl`) returns `app = claude-usage`.
7. **End‑to‑end with the extension:** load the unpacked extension in Windows Edge/Chrome logged into claude.ai; within one scrape cycle the tray `%` + tooltip match `claude.ai/settings/usage`.
8. **Render parity:** for a known cache, the rendered tray `%` colour matches the pacing tiers (green/amber/red), *broken* → red star, *stale* → ghosted; the tooltip equals `tooltip.format_tooltip` output.
9. **Tier transitions:** simulate `_anthropic_status` incident → broken (red icon, status menu item links to the status page, balloon fires once per 5 min, clicking the balloon opens the status page); age > 15 min → stale (ghosted); recovery → normal.
10. **Metric pick + countdown:** the right‑click radio cycles which meter the `%` tracks and persists it; a 100 %‑maxed meter shows a minute‑ticking `⏱H:MM`.
11. **Preferences:** open **Preferences…**, change the critical colour + the warning threshold; `config.json` updates and the tray `%` recolours within ~2 s; reopen Preferences and confirm persisted values load back into the swatches/`Spinbox`es.
12. **Installer + winget:** `setup.exe` installs per‑user (no admin), adds autostart + a Start‑Menu shortcut; the uninstaller removes the app, the shortcut, and the Run value; `winget install Indri.ClaudeUsage` resolves the manifest. (SmartScreen "Run anyway" documented.)
13. **Diagnostics:** `claude-usage-status` on Windows reports the Run‑key + process state + cache freshness + meters, with no `systemctl`/`launchctl`/`gnome-extensions` errors.

---

## Deferred / open

- **Mini usage rings in the tray** — deferred (don't read at 16 px; Cairo is hard to bundle on Windows). The render path is Pillow; a later mode could revive `generate-icon.py`'s ring geometry.
- **Owner‑draw coloured menu bars** — the per‑segment coloured pacing bar (macOS `NSAttributedString`) isn't reproduced in the Win32 popup menu (plain text); it lives in the tooltip for v1. Owner‑draw is the upgrade.
- **Code signing / SmartScreen** — an Authenticode (OV/EV) cert + `signtool` is the `notarytool` analog; ship unsigned v1 with the "Run anyway" note. A winget listing smooths reputation over time.
- **KeepAlive / restart‑on‑crash** — the Run key only relaunches at login; a Task Scheduler `ONLOGON` trigger with restart‑on‑failure is the launchd‑`KeepAlive` analog if crash‑resilience matters.
- **Modern toast notifications** with action buttons (Win10+/WinRT, `AppUserModelID`) — v1 uses classic balloons + click‑to‑open; toasts add a real "View Status Page" button.
- **ARM64 (Windows on ARM)** — PyInstaller builds match the runner arch; ship x64 v1 and add an arm64 build if demand appears (Pillow/pywin32 wheels permitting).
- **Prefs Tk‑under‑Win32‑message‑loop wiring** — the one integration risk (§3); the separate‑`pythonw`‑process path is the safe default to validate live.
