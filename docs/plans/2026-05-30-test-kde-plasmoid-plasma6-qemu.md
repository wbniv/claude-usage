# Test the KDE plasmoid on real Plasma 6, via the Foundry Linux ISO in QEMU

## Context

`claude-usage` 0.11.27 shipped a KDE Plasma plasmoid that was **completely
non-functional** — `main.qml` used `StandardPaths` with no `import QtCore`, so
`loadData()` threw on every call and the plasmoid never loaded data. Commit
`8818294` (code-review fixes, KDE‑1..5) fixed the static defects, but the fix
was landed with **static checks only** — the dev box runs GNOME, so the
plasmoid has never actually been loaded into a running Plasma 6 shell.

Two TODO items track the gap:

- `docs/plans/2026-05-30-code-review-fixes.md` **step 10 [live]** — "KDE plasmoid
  loads: `task kde-install`; add widget; `journalctl --user` shows no QML
  errors; panel shows `%`, popup shows meters + reset + status/age; config
  round-trip writes `~/.config/claude-usage/config.json`." → **DEFERRED, no Plasma
  session on this box.**
- TODO.md: `[verify] [live] KDE plasmoid on real Plasma 6 … (no Plasma/Chrome
  runtime on the dev box)`.

The sibling project `../foundrylinux.org/` builds a **Plasma 6 Wayland** live ISO
and already ships a QEMU boot harness — that is exactly the missing runtime.
This plan uses that ISO to close step 10.

**Out of scope:** step 11 [live] (GNOME‑45 notify fallback) needs a *GNOME* 45
shell, not KDE — the Foundry ISO cannot verify it. It stays deferred.

---

## What already exists (reuse, don't rebuild)

| Asset | Path | Use |
|---|---|---|
| Built ISO | `../foundrylinux.org/foundry-iso/dist/foundry-anvil-0.9.30-amd64.iso` | Plasma 6 Wayland live session |
| QEMU harness | `../foundrylinux.org/foundry-iso/test/boot-smoke.sh` | KVM + VirtGL + OVMF UEFI + `hostfwd 2222→22` boot |
| SSH-in-live hook | `…/config/hooks/1200-live-ssh.hook.chroot` | sshd is **on** in the live session — `user`/`live`, `root`/`foundry`, port 2222 |
| Plasmoid | `kde-plasmoid/` (id `org.indri.claude-usage`, API min 6.0) | the thing under test |
| Field allowlist | `scripts/lint-kde-parity.py` (`TOP_FIELDS`, `METER_FIELDS`) | source of truth for the synthetic `usage.json` fixture |
| Install task | `Taskfile.yml: kde-install` | rsync recipe to mirror over SSH |

**Host preconditions (all confirmed present):** `qemu-system-x86_64`, `/dev/kvm`
writable, `/usr/share/OVMF/OVMF_CODE_4M.fd` + `…_VARS_4M.fd`.

---

## Critique of the current verification approach — and the fixes

The verification text in `2026-05-24-kde-desktop-support.md` and the code-review
plan's step 10 is written for a generic, hand-driven KDE desktop. Problems:

1. **No concrete runtime named.** "On a KDE session…" — there was none, which is
   why it got deferred indefinitely. **Fix:** pin it to the Foundry ISO + QEMU,
   which is reproducible and already on disk.
2. **Plasma‑5 commands.** The implementation plan prints
   `kquitapp5 plasmashell && kstart5 plasmashell` and greps
   `journalctl --user -u plasmashell`. The Foundry session is **Plasma 6**: the
   unit is `plasma-plasmashell.service`, restart is
   `systemctl --user restart plasma-plasmashell` (or `kquitapp6 plasmashell;
   kstart plasmashell`). **Fix:** use the Plasma‑6 names.
3. **"Add the widget" is unspecified and assumes a human clicking.** On a
   Wayland live VM there is no operator. **Fix:** add the widget headlessly via
   the Plasma scripting API over D-Bus:
   `qdbus6 org.kde.plasmashell /PlasmaShell evaluateScript
   'panels()[0].addWidget("org.indri.claude-usage")'`.
4. **Depends on a live scraper to populate `usage.json`.** That drags in Chrome,
   a logged-in claude.ai session, and the server — none of which the step-10
   assertion is about. **Fix:** drop a **synthetic `usage.json` fixture** built
   from the lint allowlist into `~/.cache/claude-usage/usage.json`. Deterministic,
   and it exercises exactly the load/render path that was broken.
5. **"Confirm it appears without error" is unobservable headless.** **Fix:**
   two concrete signals — (a) `journalctl --user -u plasma-plasmashell` shows no
   QML error/warning referencing the plasmoid, and (b) a Wayland screenshot
   (`spectacle -b -n -f -o`) copied back to the host shows the `%` label and the
   popup meter rows.
6. **Config round-trip never names where the file lands or how it's triggered.**
   **Fix:** the plasmoid writes `~/.config/claude-usage/config.json` via its
   `Plasma5Support` executable-engine save path; assert the file appears with the
   changed key, then run `server/generate-icon.py` *in the guest* and confirm the
   dock icon picks up the JSON (the decoupling that motivated the whole KDE
   effort).

---

## Procedure

All steps run from `~/SRC/claude-usage/`. The flow is: boot the ISO → push the
plasmoid + fixture over SSH → install + add widget headlessly → capture
evidence → config round-trip → tear down.

### 1. Boot the ISO (background)

```bash
ISO=../foundrylinux.org/foundry-iso/dist/foundry-anvil-0.9.30-amd64.iso
QEMU_MEM=4096 bash ../foundrylinux.org/foundry-iso/test/boot-smoke.sh "$ISO"
```

Run it backgrounded; it opens a GTK display and forwards `2222→22`. Wait for SSH
to answer (~60 s):

```bash
until ssh -p 2222 -o StrictHostKeyChecking=no -o ConnectTimeout=3 \
  user@localhost true 2>/dev/null; do sleep 3; done
```

(`sshpass -p live`, or pre-seed a key — sshd allows password auth per the hook.)

### 2. Synthesize a `usage.json` fixture

Build it from `scripts/lint-kde-parity.py` allowlists so it is parity-correct:
- top: `meters[]`, `plan`, `_timestamp`, `_anthropic_status`
- meter: `label`, `pct`, `reset_minutes`

A 3-meter fixture (e.g. Sonnet 72 %, Opus 31 %, Weekly 88 %, one with a degraded
`_anthropic_status`, varied `reset_minutes`) exercises the compact `%`, the
color/pacing branches, the popup `MeterRow` reset countdown, and the status/age
line in one shot.

### 3. Push + install over SSH

```bash
ssh -p 2222 user@localhost 'mkdir -p ~/.local/share/plasma/plasmoids ~/.cache/claude-usage ~/.config/claude-usage'
scp -P 2222 -r kde-plasmoid/        user@localhost:~/.local/share/plasma/plasmoids/org.indri.claude-usage
scp -P 2222 server/generate-icon.py user@localhost:~/                # for the round-trip check
scp -P 2222 /tmp/usage-fixture.json user@localhost:~/.cache/claude-usage/usage.json
```

(Mirrors `Taskfile.yml: kde-install`, but into the **guest** home, not the dev
box's.)

### 4. Load it + add the widget headlessly

```bash
ssh -p 2222 user@localhost '
  systemctl --user restart plasma-plasmashell
  sleep 5
  qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
    "var p = panels()[0]; p.addWidget(\"org.indri.claude-usage\");"
  sleep 3
'
```

### 5. Capture evidence

```bash
ssh -p 2222 user@localhost '
  journalctl --user -u plasma-plasmashell --no-pager | grep -iE "qml|claude-usage|StandardPaths" || echo "NO QML ERRORS"
  spectacle -b -n -f -o /tmp/panel.png
  # then open the popup and re-shoot:
  qdbus6 org.kde.plasmashell /PlasmaShell evaluateScript "panels()[0].widgets(\"org.indri.claude-usage\")[0].action(\"toggle\").trigger()" || true
  spectacle -b -n -f -o /tmp/popup.png
'
scp -P 2222 user@localhost:/tmp/panel.png user@localhost:/tmp/popup.png docs/plans/screenshots/
```

### 6. Config round-trip

Change one key through the plasmoid config (drive `ConfigGeneral.qml`'s
`saveConfigJson()` via the scripting API, or write a known config and trigger
save), then:

```bash
ssh -p 2222 user@localhost '
  cat ~/.config/claude-usage/config.json
  python3 ~/generate-icon.py && ls -l ~/.local/share/icons/hicolor/*/apps/claude-usage.png
'
```

Assert the JSON holds the changed key and `generate-icon.py` consumed it (its
JSON branch ran, not the GSettings/`DEFAULTS` fallback — GSettings is absent on
KDE, so this is the real exercise of the `load_config()` change).

### 7. Tear down

Close the QEMU window (the harness traps cleanup) or `kill` the backgrounded PID.

---

## Proposed reusable harness

Wrap steps 1–6 in **`scripts/test-kde-qemu.sh`** (claude-usage), parameterized on
`ISO=` (default: newest `foundry-anvil-*.iso` in the sibling repo's `dist/`), and
add a `task test-kde-live` entry. Rationale per the SRC guide ("everything must
be reproducible", "automate; minimize manual steps"): the verification becomes a
single command instead of a one-off manual session, and it can be re-run on every
plasmoid change. The fixture builder lives in the script (or
`server/tests/fixtures/usage-sample.json`). Screenshots land in
`docs/plans/screenshots/` for the `[verify]` evidence block.

---

## Verification — maps 1:1 to code-review plan step 10

Paste raw output under each, mark PASS/FAIL, write back to
`docs/plans/2026-05-30-code-review-fixes.md`, then promote the TODO item to `[x]`.

1. **Boots:** SSH answers on 2222 within ~90 s → live Plasma 6 session up.
2. **Installs:** `~/.local/share/plasma/plasmoids/org.indri.claude-usage/metadata.json` present in guest.
3. **Loads without throwing:** `journalctl --user -u plasma-plasmashell` shows **no** QML error / `StandardPaths` / `ReferenceError` referencing the plasmoid. *(This is the exact regression KDE‑1 introduced — the headline of the whole fix.)*
4. **Compact shows `%`:** `panel.png` shows the top meter's percentage in the pacing color.
5. **Popup renders:** `popup.png` shows one `MeterRow` per meter with label, bar, and reset countdown, plus the status/age line.
6. **Config round-trip:** `~/.config/claude-usage/config.json` contains the changed key; `generate-icon.py` regenerates the dock icon from it (JSON branch, not DEFAULTS).
7. **GNOME regression (already PASS, static):** unchanged — JSON file absent on GNOME, GSettings path still taken.

**Deferred (unchanged):** step 11 [live] GNOME‑45 notify fallback — needs a
GNOME‑45 shell; the KDE ISO can't cover it.

---

## Risks & fallbacks

- **Plasma scripting API names drift between 6.x point releases.** If
  `panels()[0].addWidget(...)` errors, fall back to adding via
  `plasma-interactiveconsole` or hand-adding through the GUI over the QEMU
  display (the boot harness opens one). Screenshot path is unaffected.
- **`qdbus6` vs `qdbus` binary name.** Foundry/Plasma 6 ships `qdbus6`; if absent,
  try `qdbus`. Probe with `command -v qdbus6 || command -v qdbus` first.
- **VirtGL/llvmpipe.** The harness uses `virtio-vga-gl`; if the host GPU can't do
  VirtGL it falls back to llvmpipe (slower but renders) — fine for a screenshot.
- **`spectacle` missing on Wayland‑only minimal builds.** Fall back to `grim` or
  the scripting API's `org.kde.KWin.Screenshot` D-Bus call.
- **ISO is 0.9.30 (pre‑1.0).** Confirms sshd hook is baked (built 2026‑05‑26 with
  hook present). If a newer ISO drops the hook, rebuild with
  `EDITION=anvil task iso-build` after re-adding `1200-live-ssh`.

---

# FOLLOW-UP (active): config dialog shows no settings

## Context

After the plasmoid loads + renders (above), opening **Configure → the config
dialog shows only the built-in "Keyboard Shortcuts" + "About" pages** — none of
the Colors / Thresholds / Sizes / Font settings. A third runtime-only defect the
static checks missed.

## Root cause (diagnosed live on Plasma 6 / Qt 6.10, 2026-05-30)

Ruled out the obvious (missing QML modules): **both `qml6-module-org-kde-kquickcontrols`
and `qml6-module-qtquick-dialogs` are installed on the Foundry ISO**, and
`qmllint` resolves every import in `ConfigGeneral.qml`. So this is **our bug, not
a Foundry gap.**

`qmllint` on the guest (where the real Plasma modules exist — unlike the GNOME
dev box) flags **`plasmoid` as "Unqualified access"** on every
`plasmoid.configuration.X` line. `ConfigGeneral.qml` uses the **Plasma 5 idiom**
(lowercase `plasmoid.configuration` direct read/write); in Plasma 6 the config
page gets no lowercase `plasmoid` context → the bindings throw at load → Plasma
silently drops the page and shows only the built-ins.

Confirmed against the distro's own working config pages: across 25 shipped config
QML files the idiom is overwhelmingly **`cfg_<key>`** (150 uses) inside a
`KCM.SimpleKCM` that `import org.kde.plasma.plasmoid` (e.g.
`/usr/share/plasma/plasmoids/org.kde.plasma.systemmonitor/contents/ui/config/ConfigAppearance.qml`).
The config framework auto-loads/saves `cfg_<key>` ↔ KConfig on OK/Apply.

## Fix (claude-usage) — `kde-plasmoid/contents/ui/config/ConfigGeneral.qml`

1. **Adopt the Plasma 6 `cfg_<key>` convention.** Make the root a
   `KCM.SimpleKCM` (`import org.kde.kcmutils as KCM`); for each of the 13 KConfig
   keys declare a `property alias cfg_<Key>: <control>.<value>` (names must match
   `contents/config/main.xml` exactly). Bind each control's value to its
   `cfg_<Key>`. Delete all `plasmoid.configuration.X` access. The framework then
   handles load + OK/Apply/Defaults automatically.
2. **Preserve the `config.json` side-effect** (so `generate-icon.py` picks up
   KDE colours/thresholds) but move it OUT of the config page: in `main.qml`,
   watch `Plasmoid.configuration` changes and write
   `~/.config/claude-usage/config.json` via the existing executable-engine
   `reader`/DataSource pattern. This fires on every change (not just dialog OK)
   and removes the page's dependency on a custom save path.
3. **Graceful degradation (per the host-features requirement).** Keep the native
   `org.kde.kquickcontrols` ColorButton + `QtQuick.Dialogs` FontDialog as the
   rich path, but load each via a `Loader`/`Qt.createComponent` status check so a
   host lacking those modules falls back to a hex `TextField` + colour swatch and
   a font-family `TextField`/`ComboBox` instead of failing the whole page. (Not
   needed on Foundry — both modules present — but satisfies "support what the host
   exposes, degrade gracefully.")
4. Verify `contents/config/main.xml` declares all 13 keys with defaults
   (`cfg_<key>` needs the KCfg entry to bind/persist).

## Regression guard

- **Extend `scripts/lint-kde-parity.py`** (or `lint-qml`): fail if any
  `kde-plasmoid/**/config/*.qml` references lowercase `plasmoid.configuration` or
  omits the `cfg_<key>` convention. Cheap, runs on the GNOME box, catches the
  exact class.
- **Extend `scripts/test-kde-qemu.sh`**: install `qt6-declarative-dev-tools` in
  the guest and run `qmllint -I <qt6 qml path>` over the plasmoid's config QML
  (the guest has the real Plasma modules; the dev box does not) → assert no
  "Unqualified access" on `plasmoid`. Optionally open the config KCM and assert
  the General page registers.

## Foundry Linux (separate, lower priority)

The config bug is **not** a Foundry gap (modules present). The "full KDE
experience" ask is a distinct enhancement — write
`../foundrylinux.org/docs/plans/2026-05-30-full-kde-experience.md`: audit
`0020-strip-kubuntu-bloat` + `strip.list.chroot.purge` to confirm no KDE config
modules (kquickcontrols, qtquick-dialogs, KCMs) get stripped, and decide which
KDE apps/round out the default kit. Verify on both `anvil` and `atelier`.

## QEMU resolution

All VM boots (harness + ad-hoc) must run at **≥1024×768** — add
`xres=1280,yres=800` to the `virtio-vga-gl` device in `scripts/test-kde-qemu.sh`
(QEMU ≥6.1 honours it; fall back to `kscreen-doctor output.<name>.mode.1280x800`
post-boot). Saved as a standing preference in memory.

## Verification

1. `qmllint -I /usr/lib/x86_64-linux-gnu/qt6/qml ConfigGeneral.qml` in-guest →
   **no** "Unqualified access" on `plasmoid` (currently fails).
2. `task test-kde-live` → open the widget's config dialog → the **General** page
   appears with Colours / Thresholds / Sizes / Font controls (screenshot).
3. Change a threshold + a colour → values persist across a plasmoid reload
   (KConfig) **and** `~/.config/claude-usage/config.json` updates → re-run
   `generate-icon.py` → dock icon reflects the change.
4. On a host *without* the kquickcontrols/dialogs modules (simulated), the
   General page still loads with the fallback controls (no blank dialog).
5. `task test` (incl. the new config-QML lint) is green on the dev box.
