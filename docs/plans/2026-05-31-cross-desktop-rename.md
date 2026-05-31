# Plan: De-GNOME-ify naming — make `claude-usage` a cross-desktop project

## Context

`claude-usage` began as a GNOME-only "Claude Usage Indicator" and grew a second
backend, the KDE Plasma plasmoid (shipped in 0.11.27, `kde-plasmoid/`). The code
is now cross-desktop, but the **naming and docs still present the whole project
as GNOME**: the settings schema is `org.gnome.shell.extensions.claude-usage`,
the two backends sit at the repo root with no neutral grouping, user docs never
mention KDE, and the build/CI machinery is littered with GNOME-shaped paths.

The user asked to "rename all the things" and chose (1) a **full deep rename
including the schema ID**, and (2) **nesting both backends under a neutral
parent**. The outcome: one neutral namespace (`org.indri.claude-usage`) shared
by both backends, a `desktop/{gnome,kde}/` layout, and docs that describe a
GNOME-*and*-KDE tool.

**No dconf migration** — there are no released users yet (confirmed 2026-05-31),
so the schema rename is a clean break with no settings to carry forward. The
codebase reads as though the schema was always `org.indri.claude-usage`.

A separate doc bug surfaced mid-planning and is folded in: the manual claims the
reset countdown (`⏱h:mm`) shows "when less than **24 h** away" — the code
(`extension.js:75`, `tooltip.py:78`) uses **12 h** (`mins < 12 * 60`). Fix to 12 h.

## Decisions (locked)

- **Unified namespace `org.indri.claude-usage`** — already the KDE plugin Id.
  The GNOME schema adopts it too:
  - id   `org.gnome.shell.extensions.claude-usage` → `org.indri.claude-usage`
  - path `/org/gnome/shell/extensions/claude-usage/` → `/org/indri/claude-usage/`
  - file `…/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml`
         → `…/schemas/org.indri.claude-usage.gschema.xml`
  - keys (kebab-case names) **unchanged** — only id/path/filename move.
- **GNOME UUID `claude-usage@indri.studio` stays.** It contains no "gnome" and
  is already neutral; a GNOME UUID must be `name@domain` form, so it can't become
  the dotted `org.indri.…`. Changing it would only orphan the enabled-extensions
  list and the install dir for zero naming benefit. (The mandatory
  `gnome-shell/extensions/` *install location* is fixed by GNOME and also stays.)
- **Layout under `desktop/`** (resolves the collision with the existing
  `desktop/` launcher dir):
  - `gnome-extension/` → `desktop/gnome/`
  - `kde-plasmoid/`    → `desktop/kde/`
  - `desktop/claude-usage.desktop` → `desktop/launcher/claude-usage.desktop`
  - Use `git mv` to preserve history.
- **No migration** — no released users, so the schema rename is a clean break.

## Work

### 1. Directory moves (do first; everything else updates paths to match)
- `git mv gnome-extension desktop/gnome`, `git mv kde-plasmoid desktop/kde`,
  `git mv desktop/claude-usage.desktop desktop/launcher/claude-usage.desktop`.
- The generated `desktop/gnome/_defaults.js` moves with it (regenerated in step 3).

### 2. Schema rename (the high-risk core)
- `desktop/gnome/schemas/…` → rename file to `org.indri.claude-usage.gschema.xml`;
  edit `<schema id=… path=…>` to the new id/path. Keys untouched.
- `desktop/gnome/metadata.json` → `settings-schema: org.indri.claude-usage`.
- Grep JS for any hardcoded schema id: `extension.js`/`prefs.js` use
  `Extension.getSettings()` (reads metadata), but verify no literal remains.

### 3. Python server + scripts (read the GNOME schema at runtime)
- `server/schema_defaults.py` — `_SCHEMA_FILENAME` → new filename; candidate
  paths: `desktop/gnome/schemas/…` (source) and keep the installed
  `gnome-shell/extensions/claude-usage@indri.studio/schemas/…` path.
- `server/generate-icon.py` — `Gio.Settings.new('org.gnome.shell.extensions.claude-usage')`
  → new id; update the hardcoded icon-path comment/path.
- `scripts/gen-js-defaults.py` — `SCHEMA`/`OUT` → `desktop/gnome/…`; header text.
- `scripts/lint-kde-parity.py` — GNOME-schema path/filename it reads for parity.
- `scripts/popup-preview.py`, `scripts/_doc_render.py`, `scripts/render-*.py`,
  `scripts/claude-usage-status.py` (note: `EXT_ID` = UUID, **unchanged**).
- Regenerate: `python3 scripts/gen-js-defaults.py` → fresh `desktop/gnome/_defaults.js`.

### 4. install.sh + setup
- `GNOME_EXT_DIR` source copies: `gnome-extension/` → `desktop/gnome/`; schema
  filename in copy/compile lines; launcher path → `desktop/launcher/…`.
- KDE: `kde_install_plasmoid()` source `kde-plasmoid/` → `desktop/kde/`.
- Uninstall: the `claude-usage@*` wildcard stays; remove the renamed
  `org.indri.claude-usage.gschema.xml` glib file.
- No migration shim — no released users (see Context); clean break.

### 5. packaging/
- `build-deb.sh` — source paths (`gnome-extension/`→`desktop/gnome/`,
  `kde-plasmoid/`→`desktop/kde/`, launcher), schema filename in the
  `usr/share/claude-usage/schemas` copy. **Install targets**
  (`/usr/share/gnome-shell/extensions/claude-usage@indri.studio/`,
  `/usr/share/plasma/plasmoids/org.indri.claude-usage/`) are OS-mandated — keep.
- `postinst` — compile new schema filename; comment text.
- `postrm` — remove `org.indri.claude-usage.gschema.xml`.
- `control` — description: mention both GNOME and KDE Plasma panels,
  keep `Recommends: gnome-shell (>= 45) | plasma-desktop`.
- `claude-usage-setup` — schema/UUID lines.
- `test-deb-verify.sh`, `test-gnome.Dockerfile`, `test-gnome-verify.sh`,
  `test-deb-live.sh` — source paths + schema filename + verify-path assertions.

### 6. Taskfile.yml + CI
- All task bodies: `gnome-extension/`→`desktop/gnome/`, `kde-plasmoid/`→`desktop/kde/`,
  schema filename.
- Harmonize task names to `<action>-<platform>` while touching them:
  `kde-install`→`install-kde`, `kde-uninstall`→`uninstall-kde`
  (GNOME side already `test-gnome`/`lint-gnome`; keep). Update `release`/`bump`
  refs to `desktop/gnome/metadata.json`.
- `.github/workflows/gnome-version-check.yml` — path
  `gnome-extension/metadata.json` → `desktop/gnome/metadata.json`. Keep the
  filename: it genuinely checks GNOME Shell versions.
- `release.yml` — no path change expected; verify it doesn't reference moved dirs.

### 7. Docs (the user-facing payoff)
- **MANUAL.md / README.md** (README is a symlink to MANUAL):
  - Fix the reset threshold: "less than **24 h** away" → "less than **12 h** away".
  - Lead line "GNOME top panel" → "GNOME or KDE Plasma panel".
  - Requirements: add Plasma 6 alongside GNOME Shell 45–50; add a KDE row to the
    distro table.
  - Add a KDE install path (`task install-kde` / plasmoid dir) and KDE config
    (right-click plasmoid → Configure) beside the `gnome-extensions prefs` /
    `gsettings` examples.
  - Repo-layout block: `desktop/gnome/`, `desktop/kde/`, `desktop/launcher/`.
  - Troubleshooting: KDE-equivalent of the "indicator missing" / "not updating" steps.
- **PRIVACY.md** — add KDE KConfig (`~/.config/…`) storage next to GSettings;
  update the schema id mention to `org.indri.claude-usage`.
- **SECURITY.md** — add a KDE plasmoid row to the threat-model table and the
  architecture description (Qt/QML monitoring vs Gio.FileMonitor).
- After each `.md` edit, run `task md -- <file>` (per project convention).

## Out of scope (flag, don't fix here)
- The server reads the **GNOME** schema for icon defaults even on KDE-only boxes;
  the .deb installs that gschema regardless so it resolves, but it's an
  architectural quirk, not a naming issue. Note in TODO, don't refactor now.

## Critical files
`desktop/gnome/metadata.json`, `desktop/gnome/schemas/org.indri.claude-usage.gschema.xml`,
`server/schema_defaults.py`, `server/generate-icon.py`, `scripts/gen-js-defaults.py`,
`scripts/lint-kde-parity.py`, `install.sh`, `packaging/{build-deb.sh,postinst,postrm,control,claude-usage-setup,test-deb-verify.sh}`,
`Taskfile.yml`, `.github/workflows/gnome-version-check.yml`, `MANUAL.md`, `PRIVACY.md`, `SECURITY.md`.

## Verification
1. `grep -rIn 'org\.gnome\.shell\.extensions\.claude-usage' .` → only intentional
   migration-shim references to the **old** path remain; nothing else.
2. `grep -rIn 'gnome-extension/\|kde-plasmoid/' .` → no source references to old
   dir names (GNOME *install* paths `gnome-shell/extensions/…` are expected).
3. `task gen-js-defaults && task lint-js-defaults` → `_defaults.js` in sync at new path.
4. `task lint-kde-parity && task lint-qml && task lint-gnome` → pass.
5. `task test-gnome-format` (node) → pass.
6. Build the .deb (`task` build target) → `bash packaging/test-deb-verify.sh`
   passes against new schema filename + plasmoid path.
7. `task test-gnome` (Docker headless gnome-shell 45–50) → extension loads.
8. `task test-kde-live ISO=<foundry.iso>` (QEMU Plasma 6, ≥1280x800) → plasmoid renders.
9. `gsettings set org.indri.claude-usage threshold-warning 55 && gsettings get
   org.indri.claude-usage threshold-warning` (after install) → `55` — confirms the
   renamed schema compiles and is writable end-to-end.
10. Re-render screenshots (`scripts/render-*.py`) and confirm `git status` PNGs
    unchanged except where text moved; manual reads correctly via `task md`.
