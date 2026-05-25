# KDE Plasma support — port the panel indicator to a Plasmoid

## Status

**Implemented (2026-05-25)** — phases 1–4 landed; loads cleanly in real
Plasma 6.6.4 (container-verified). What shipped:

- `kde-plasmoid/` — Plasma 6 plasmoid (PlasmoidItem root polling `usage.json`
  via a P5Support executable DataSource; compact rep = ring Canvas + colour
  percent + scroll-cycle; full rep = pacing-bar popup; KConfigXT config UI).
- `kde-plasmoid/contents/ui/lib/usage.js` — pacing/tier/reset math ported from
  `extension.js`; verified byte-identical to the Python source on a case sweep.
- `scripts/gen-kde-config.py` + `task gen-kde-config`/`lint-kde-config` —
  `main.xml` generated from the gschema (added to `task test`).
- `lint-kde-parity` (in `scripts/lint-scraper-parity.py`) — asserts
  `pacingPct`/`elapsedFraction`/`pacingSegments`/`bar`/`fmtAge` literals match
  `extension.js`.
- `packaging/test-kde.Dockerfile` + `test-kde-verify.sh` + `task test-kde` —
  headless `plasmoidviewer` load check (Xvfb + xcb) with a load-marker assertion
  so a non-loading applet can't pass blind; negative-control verified.
- `install-kde.sh` — installs the plasmoid + shared backend (server, systemd,
  chrome-extension), skipping the GNOME-only pieces.

**Deviations from the design below** (all deliberate):

- Base image is `ubuntu:26.04` + `plasma-workspace`/`plasma-desktop`/`plasma-sdk`,
  not KDE neon — neon's Docker tags are stale (22.04 + Plasma 5.27). The build
  needs `--network=host` in restricted-egress sandboxes.
- No `kpackagetool6` (Ubuntu doesn't ship the CLI standalone) — the verify
  script and `install-kde.sh` copy into `…/plasma/plasmoids/<id>/`, which
  KPackage discovers by scanning.
- Install is a separate `install-kde.sh`, not DE-detection inside `install.sh`
  (lower risk to the GNOME path; could be merged later).
- `PacingBar.qml` folded into `FullRepresentation.qml` (single RichText row).
- KDE parity lint lives inside `lint-scraper-parity.py`, not a separate
  `lint-kde-parity.py`.

**Not yet done:** Part 5 phase 5 (MANUAL.md gains a full KDE section — a brief
pointer was added), .deb packaging of the plasmoid (`build-deb.sh`), and live
visual acceptance on a real Plasma session (vs. the headless container check).

The original design follows, unchanged, as the rationale of record.

## Context

Today the desktop indicator is **GNOME-only**: a GNOME Shell extension
(`gnome-extension/extension.js` + `prefs.js`) reads the local cache and renders
the panel label, popup, and Dash-to-Dock ring overlay. GNOME Shell extensions
do **not** run under KDE — they're a different runtime (GJS + St/Clutter +
`resource:///org/gnome/shell/...` imports). KDE Plasma's equivalent of a panel
widget is a **Plasmoid**: a KPackage of QML (Qt Quick) + a KConfigXT config
schema, loaded by `plasmashell`.

The good news is that the data plane is already decoupled. The architecture is:

```
chrome-extension ──HTTP POST──▶ server/usage-server.py ──writes──▶ ~/.cache/claude-usage/usage.json
                                                          │
                                                          └─invokes─▶ server/generate-icon.py (PNG rings, GNOME dock)
                                                                                                        ▲
gnome-extension/extension.js ──load_contents_async + file monitor──▶ usage.json ───────────────────────┘
```

The Chrome extension, the server, and the `usage.json` cache file are the
**contract**. Anything that reads `usage.json` can be a front end. KDE support
means writing a second front end (a Plasmoid) against that same contract — no
changes to the scraper or the write path.

---

## Part 1 — Reuse boundary (what is and isn't DE-agnostic)

I audited `server/` for GNOME coupling. The boundary is **not** simply
"server = reusable":

**Reusable as-is (no GNOME dependency):**

| Component | Why it's portable |
|-----------|-------------------|
| `chrome-extension/` | Pure browser scraper → HTTP POST. DE-blind. |
| `server/usage-server.py` | stdlib `http.server`; writes `~/.cache/claude-usage/usage.json` + dynamic-port file. No GTK/Gio. |
| `server/tooltip.py` | Pure text formatting from the cache dict. |
| `server/schema_defaults.py` | Parses the gschema **XML** for `<default>`/`<range>` — just `xml.etree`, no live gsettings read. Usable as the defaults SOT for KDE too. |
| `systemd/claude-usage-fetch.service` | User service that runs the fetch loop. DE-blind. |
| `usage.json` cache contract + `CACHE_SCHEMA` versioning | The whole interop surface. |

**GNOME-coupled — must be reimplemented in QML for KDE (NOT reused):**

| Component | The coupling |
|-----------|-------------|
| `gnome-extension/extension.js` | St/Clutter/PanelMenu/PopupMenu; panel label, popup, scroll-to-cycle, color tiers, pacing-viz, dock ring. |
| `gnome-extension/prefs.js` | Adw/Gtk preferences window. |
| `gnome-extension/schemas/*.gschema.xml` | gsettings schema; KDE uses KConfigXT. |
| `gnome-extension/_defaults.js` | Generated from gschema for GJS. |
| **`server/generate-icon.py`** | **Surprise coupling:** its `load_config()` reads *live* thresholds/colors via `Gio.Settings` (`s.get_string('weekly-color-green')`, …). It is **not** DE-neutral. KDE won't have those gsettings keys. |

**Design consequence:** the Plasmoid renders its rings/label **itself in QML
Canvas**, reading its own KConfig values — it does **not** call
`generate-icon.py`. That keeps `generate-icon.py` as a GNOME-dock concern (the
PNG-overlay trick only exists because GNOME has no first-class way to draw on a
dock icon; a Plasmoid draws its compact representation natively). So
`generate-icon.py` stays out of the KDE path entirely.

---

## Part 2 — Plasmoid architecture (Plasma 6 / Qt 6)

Target **Plasma 6** only. Plasma 5 is a different QML API (`Item` root +
`plasmoid.*` globals + Plasma5 components) and is EOL on current LTS releases —
declare it out of scope.

Package layout under `kde-plasmoid/` in the repo, installed to
`~/.local/share/plasma/plasmoids/studio.indri.claudeusage/`:

```
kde-plasmoid/
  metadata.json                      # KPackage / KPlugin manifest (Id: studio.indri.claudeusage)
  contents/
    config/
      main.xml                       # KConfigXT schema — GENERATED from the gschema (Part 3)
      config.qml                     # config-page registry (maps gschema groups → pages)
    ui/
      main.qml                       # PlasmoidItem root; owns the poll Timer + JSON model
      CompactRepresentation.qml      # panel label + ring (QML Canvas) — replaces extension.js panel + generate-icon.py
      FullRepresentation.qml         # popup (meters, pacing bars, reset times) — replaces extension.js popup
      PacingBar.qml                  # the ┊ tick + over-pace two-tone split, ported from popup-preview.py
      configGeneral.qml              # thresholds/colors prefs page — replaces prefs.js
      lib/usage.js                   # shared JS: tier/color/pacing math (port of the parity'd helpers)
```

**Reading the cache.** The Plasmoid does not hit the HTTP port — it reads the
same `usage.json` the GNOME extension reads. The data updates on the order of
minutes, so a lightweight poll is sufficient and avoids a native file watcher:

- A QML `Timer` (interval ~5 s) issues an `XMLHttpRequest` against
  `file://$XDG_CACHE_HOME/claude-usage/usage.json`, parses JSON, updates a
  `property var data`.
- On each read, check `data._schema` against the Plasmoid's `CACHE_SCHEMA`
  constant and warn once per session on mismatch — exactly mirroring
  `extension.js:395` so old-writer/new-reader bugs stay visible.
- Resolve `$XDG_CACHE_HOME` in `main.qml` via
  `StandardPaths.writableLocation(StandardPaths.GenericCacheLocation)` (Qt
  Labs Platform) so it matches the server's `_CACHE_HOME` resolution.

**Compact representation (panel).** A `PlasmaComponents.Label` for the percent
(color-coded green/amber/red on current pacing, red icon-tint on the *broken*
tier) plus a `Canvas` that paints the outer (All models) / inner (Sonnet) rings
— the QML analog of `generate-icon.py`'s `draw_ring`. Scroll handler on the
compact rep cycles the displayed meter (`WheelHandler`), replacing extension.js
scroll-to-cycle.

**Full representation (popup).** Kirigami/`PlasmaExtras` list of meters with the
`✴` panel-marker, pacing bars (`PacingBar.qml`), Anthropic-status banner, and
reset countdowns. The reset-time and tooltip text can reuse `tooltip.py` logic —
either port it to `lib/usage.js` or shell out to `python3 tooltip.py` via a
`P5Support.DataSource` `executable` engine. **Recommendation: port to JS** to
avoid a subprocess per tick; add a parity lint (Part 3) so the two don't drift.

---

## Part 3 — Config parity (the repo's SOT discipline, extended to KDE)

This codebase is aggressive about single-source-of-truth + parity lints
(`lint-scraper-parity`, `lint-pacing-parity`, `lint-js-defaults`,
`gen-js-defaults.py`). A hand-written KDE `main.xml` would immediately become a
fourth copy of the defaults/ranges that drifts — exactly the DG-1/PL-* class of
bug the project already fights.

**So generate the KDE config schema from the gschema, the same way
`_defaults.js` is generated:**

- New `scripts/gen-kde-config.py` — reads
  `gnome-extension/schemas/...gschema.xml` (via the existing
  `schema_defaults.py` parser) and emits `kde-plasmoid/contents/config/main.xml`
  in KConfigXT format (each gschema key → `<entry>` with mapped type +
  `<default>` + min/max from `<range>`).
- New `task lint-kde-config` (and a `scripts/lint-kde-config.py`) — asserts the
  generated `main.xml` is byte-identical to a fresh generation, mirroring
  `lint-js-defaults`. CI fails if someone hand-edits it.
- `install.sh` / the .deb build regenerate it, same as `gen-js-defaults.py`.

Color/threshold key name mapping (gschema kebab → KConfigXT camel), e.g.
`weekly-color-green` → `weeklyColorGreen`, recorded in `gen-kde-config.py` so
the JS in `lib/usage.js` reads the KConfig names.

If `tooltip.py` logic is ported to `lib/usage.js` (Part 2), add it to the parity
surface too (extend `lint-scraper-parity`-style checks) so the panel/popup math
stays identical across the GNOME and KDE front ends.

---

## Part 4 — Install & packaging

**`install.sh`** — detect the session and branch:

- Detect via `$XDG_CURRENT_DESKTOP` (`KDE` vs `GNOME`), with a `--kde` /
  `--gnome` override flag for headless/multi-DE machines.
- Shared steps (server, systemd user service, schema regeneration) run for both.
- KDE branch: `kpackagetool6 --type Plasma/Applet --install kde-plasmoid/`
  (or `--upgrade` on reinstall), then `kquitapp6 plasmashell && kstart
  plasmashell` to reload. GNOME branch: unchanged.
- Add the symmetric uninstall path (`kpackagetool6 --remove
  studio.indri.claudeusage`).

**Packaging.** Either (a) one `.deb` that ships both front ends — GNOME
extension under `/usr/share/gnome-shell/extensions/...` and the plasmoid under
`/usr/share/plasma/plasmoids/studio.indri.claudeusage/` — with `Recommends:`
rather than hard deps on either shell; or (b) split into `claude-usage-gnome`
and `claude-usage-kde` binary packages sharing a `claude-usage-common`
(server + systemd + chrome-extension + icons). **Recommendation: start with
(a)** — one package, both widgets present, each shell ignores the other's
files — and split later only if the dependency footprint becomes a complaint.

---

## Part 5 — Phasing

1. **Read-only MVP plasmoid.** `main.qml` + `CompactRepresentation.qml` showing
   the All-models percent with color tiers, polling `usage.json`. No popup, no
   config (uses gschema-derived hard defaults baked into `lib/usage.js`). Proves
   the cache contract works under Plasma 6.
2. **Popup + rings.** `FullRepresentation.qml`, the ring Canvas, scroll-to-cycle,
   pacing-viz, Anthropic-status banner, reset countdowns.
3. **Config.** `gen-kde-config.py` + `main.xml` + `configGeneral.qml` +
   `lint-kde-config`; wire thresholds/colors to KConfig.
4. **Install + package + smoke test** (Part 4 + Part 6).
5. **Docs.** MANUAL.md "Installation" gains a KDE path; reuse boundary noted.

---

## Part 6 — Smoke-test infrastructure (mirror `task test-gnome`)

Mirror the existing GNOME Docker smoke test (`packaging/test-gnome.Dockerfile`
+ `test-gnome-verify.sh` + `task test-gnome`):

- **`packaging/test-kde.Dockerfile`** — `FROM kdeneon/plasma:current` (or an
  Ubuntu with `plasma-workspace` + `plasma-sdk`), install the plasmoid with
  `kpackagetool6 --install`, then validate headless.
- **`packaging/test-kde-verify.sh`** — assert: `kpackagetool6 --type
  Plasma/Applet --show studio.indri.claudeusage` resolves; `metadata.json`
  KPlugin.Id matches the package dir; `main.xml` is in sync
  (`scripts/lint-kde-config.py`); and `plasmoidviewer -a
  studio.indri.claudeusage` (from `plasma-sdk`) loads without QML errors under
  `xvfb-run` / `QT_QPA_PLATFORM=offscreen`. Print a `PASS`/`FAIL` summary like
  the GNOME verifier.
- **`Taskfile.yml`** — add `test-kde` (parameterised by base image), same shape
  as `test-gnome`.

Per project policy (SV-1): **claim KDE support only after `task test-kde`
passes.** Don't add a "KDE supported" line to MANUAL.md until the viewer loads
clean.

---

## Files to create/modify

| File | Change |
|------|--------|
| `kde-plasmoid/metadata.json` | New — KPlugin manifest, Id `studio.indri.claudeusage`, Plasma 6 API |
| `kde-plasmoid/contents/ui/main.qml` | New — PlasmoidItem root, poll Timer, schema check |
| `kde-plasmoid/contents/ui/CompactRepresentation.qml` | New — panel label + ring Canvas + scroll-cycle |
| `kde-plasmoid/contents/ui/FullRepresentation.qml` | New — popup |
| `kde-plasmoid/contents/ui/PacingBar.qml` | New — pacing tick/over-pace split (port of popup-preview.py) |
| `kde-plasmoid/contents/ui/lib/usage.js` | New — tier/color/pacing/tooltip math (ported, parity-linted) |
| `kde-plasmoid/contents/config/main.xml` | New — **generated** from gschema |
| `kde-plasmoid/contents/config/config.qml` | New — config page registry |
| `kde-plasmoid/contents/ui/configGeneral.qml` | New — thresholds/colors page |
| `scripts/gen-kde-config.py` | New — gschema XML → KConfigXT main.xml |
| `scripts/lint-kde-config.py` | New — assert main.xml in sync (CI) |
| `Taskfile.yml` | Add `lint-kde-config`, `test-kde` |
| `packaging/test-kde.Dockerfile` | New — Plasma 6 container |
| `packaging/test-kde-verify.sh` | New — plasmoidviewer headless load check |
| `install.sh` | Detect DE; KDE branch via kpackagetool6; shared server/systemd |
| `packaging/build-deb.sh` (+ control) | Ship plasmoid files; regenerate main.xml |
| `MANUAL.md` | KDE install path — **only after `task test-kde` passes** |
| `server/*` | **No change** — reused as-is across both front ends |
| `chrome-extension/*` | **No change** |

---

## Open questions (resolve before Part 2)

1. **`tooltip.py`: port to JS or subprocess?** Recommendation: port to
   `lib/usage.js` + parity lint (avoids a python subprocess per popup tick).
2. **Single `.deb` vs split packages?** Recommendation: single first (Part 4a).
3. **Ring in QML Canvas vs reuse generated PNG?** Recommendation: native QML
   Canvas — crisper at panel scale, and `generate-icon.py` is gsettings-coupled
   anyway (Part 1).
4. **Plasma 5 at all?** Recommendation: no — Plasma 6 only.

---

## Verification (when implemented)

1. `task test` — existing suite still green (no server changes expected).
2. `task lint-kde-config` — `main.xml` matches a fresh generation from gschema.
3. `task test-kde` — Docker build succeeds; `plasmoidviewer` loads
   `studio.indri.claudeusage` with zero QML errors under offscreen Qt.
4. Manual on a real Plasma 6 session: add widget to panel; with the server
   running, panel shows the All-models percent and color tier; scroll cycles
   meters; click opens the popup with pacing bars and reset times; changing a
   threshold in the config page recolors live.
5. Only then: add the KDE install path to MANUAL.md.
